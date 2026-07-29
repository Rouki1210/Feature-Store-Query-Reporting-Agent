"""Evaluator — chạy golden set, tính metric theo tầng×category, ghi query_test_run.

LLM-optional (degrade gracefully):
  - Không LLM: retrieval_hit@k (retriever trực tiếp) + refusal_accuracy (router trực
    tiếp) + gold_sql_executes. Đủ tín hiệu để đo lớp ngữ nghĩa + guardrail.
  - Có LLM: thêm execution_accuracy (so gold vs SQL agent sinh) + feature_selection
    + repair + latency, qua full pipeline.
"""
from __future__ import annotations

import json
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text

from app.agent.contracts import IntentType
from app.agent.generator import PROMPT_VERSION, SQLGenerator
from app.agent.llm_client import OpenAIJSONClient
from app.agent.pipeline import AgentPipeline
from app.agent.router import RuleRouter
from app.config import get_settings
from app.db import get_engine
from app.eval.comparator import result_sets_equal
from app.eval.golden import assert_holdout_unchanged, cases_for_split, validate_cases
from app.semantic.retriever import get_semantic_layer
from app.sql.guards import GuardError, validate_sql

_INTENT_STATUS = {
    IntentType.out_of_scope: "out_of_scope",
    IntentType.clarify: "clarify",
}


@dataclass
class CaseResult:
    code: str
    difficulty: str
    category: str
    kind: str  # answerable | guardrail | skipped
    expected_status: str = "ok"
    retrieval_correct: bool | None = None
    retrieval_recall_at_5: float | None = None
    retrieval_top_5: list[str] = field(default_factory=list)
    expected_feature_ranks: dict[str, int | None] = field(default_factory=dict)
    retrieval_latency_ms: int | None = None
    refusal_correct: bool | None = None
    actual_status: str | None = None
    result_correct: bool | None = None
    gold_executes: bool | None = None
    expected_result_available: bool | None = None
    feature_selection_correct: bool | None = None
    generated_sql_present: bool | None = None
    generated_sql_parses: bool | None = None
    schema_valid: bool | None = None
    generated_sql_executes: bool | None = None
    llm_latency_ms: int | None = None
    sql_latency_ms: int | None = None
    repairs: int = 0
    latency_ms: int = 0
    failure: str | None = None
    actual_sql: str | None = None
    actual_features: list[str] = field(default_factory=list)


def _run_gold(sql: str) -> list[list[Any]]:
    """Chạy gold SQL read-only (qua guard, KHÔNG ghi audit) → rows."""
    safe = validate_sql(sql)
    with get_engine().connect() as conn:
        return [list(r) for r in conn.execute(text(safe)).fetchall()]


def _retrieval_for(router: RuleRouter, layer, question: str, top_k: int = 5) -> list[str]:
    _, route = router.route(question)
    if route.intent in (IntentType.out_of_scope, IntentType.clarify):
        return []  # router chặn answerable → retrieval coi như trượt
    # Phải gọi ĐÚNG như pipeline: truyền business_unit vào retrieve, không tự lọc lại.
    # Bản cũ lọc theo TIỀN TỐ TÊN BẢNG nên `CROSS_BU` không khớp `customer_cross_bu_feature`
    # ⇒ mọi case cross-BU bị chấm 0% retrieval trong khi pipeline lấy đúng cột ở rank 1.
    # Thước đo lệch khỏi hệ thống thật thì mọi kết luận tối ưu sau đó đều đáng ngờ.
    return [f.name for f in layer.retrieve(
        question, business_unit=route.business_unit, top_k=top_k,
    )]


def _recall_at_5(expected: set[str], retrieved: list[str]) -> float | None:
    if not expected:
        return None
    return len(expected & set(retrieved[:5])) / len(expected)


def _sql_parses(sql: str | None) -> bool | None:
    if not sql:
        return False
    try:
        import sqlparse

        statements = [statement for statement in sqlparse.parse(sql) if str(statement).strip()]
        return len(statements) == 1 and statements[0].get_type() in {"SELECT", "UNKNOWN"}
    except Exception:
        return None


def _trace_duration(trace: list[dict[str, Any]], *stages: str) -> int | None:
    durations = [
        event.get("duration_ms")
        for event in trace
        if event.get("stage") in stages and isinstance(event.get("duration_ms"), int)
    ]
    return sum(durations) if durations else None


def _trace_schema_valid(trace: list[dict[str, Any]]) -> bool | None:
    validations = [event.get("status") for event in trace if event.get("stage") == "validator"]
    return validations[-1] == "valid" if validations else None


def evaluate(tag: str = "baseline", split: str = "dev") -> dict[str, Any]:
    settings = get_settings()
    cases = cases_for_split(split)
    errors = validate_cases(cases)
    if errors:
        raise RuntimeError("golden_set.yaml lỗi — sửa trước khi eval:\n  " + "\n  ".join(errors))
    # Đo trên holdout thì bắt buộc holdout đã khóa & nguyên vẹn (chống leakage).
    lock_status = assert_holdout_unchanged() if split in ("holdout", "all") else "dev split (holdout không dùng)"

    llm_on = bool(settings.llm_api_key)
    router = RuleRouter()
    layer = get_semantic_layer()
    pipeline = AgentPipeline(SQLGenerator(OpenAIJSONClient(settings))) if llm_on else None

    id_by_code = {
        r[0]: r[1]
        for r in get_engine().connect().execute(
            text("SELECT test_case_code, test_case_id FROM eval.query_test_case")
        )
    }

    results: list[CaseResult] = []
    for c in cases:
        code, q = c["code"], c["question_vi"]
        cr = CaseResult(
            code=code,
            difficulty=c["difficulty"],
            category=c["category"],
            kind="",
            expected_status=c.get("expected_status", "ok"),
        )
        expected_features = set(c.get("expected_features") or [])
        gold_sql = c.get("gold_sql")
        _, initial_route = router.route(q)
        cr.actual_status = _INTENT_STATUS.get(initial_route.intent, "ok")

        if gold_sql:  # ---------- answerable ----------
            cr.kind = "answerable"
            retrieval_started = time.perf_counter()
            ranked = _retrieval_for(router, layer, q, top_k=len(layer))
            cr.retrieval_latency_ms = int((time.perf_counter() - retrieval_started) * 1000)
            cr.retrieval_top_5 = ranked[:5]
            cr.retrieval_recall_at_5 = _recall_at_5(expected_features, ranked)
            cr.expected_feature_ranks = {
                feature: (ranked.index(feature) + 1 if feature in ranked else None)
                for feature in sorted(expected_features)
            }
            cr.retrieval_correct = expected_features.issubset(set(ranked[:5]))
            try:
                gold_rows = _run_gold(gold_sql)
                cr.gold_executes = True
                cr.expected_result_available = True
            except Exception as exc:
                cr.gold_executes = False
                cr.expected_result_available = False
                cr.failure = f"gold_sql lỗi: {exc}"
                gold_rows = None
            if llm_on and gold_rows is not None:
                started = time.perf_counter()
                try:
                    resp = pipeline.ask(q, session_id=f"eval-{code}")
                    cr.latency_ms = int((time.perf_counter() - started) * 1000)
                    cr.actual_sql = resp.sql
                    cr.actual_status = resp.status
                    cr.generated_sql_present = bool(resp.sql and resp.sql.strip())
                    cr.generated_sql_parses = _sql_parses(resp.sql)
                    cr.schema_valid = _trace_schema_valid(resp.pipeline_trace)
                    if cr.schema_valid is None and not cr.generated_sql_present:
                        cr.schema_valid = False
                    cr.generated_sql_executes = resp.status == "ok" and resp.result is not None
                    cr.llm_latency_ms = _trace_duration(resp.pipeline_trace, "generator", "repair")
                    cr.sql_latency_ms = _trace_duration(resp.pipeline_trace, "executor")
                    cr.actual_features = [f.name for f in resp.retrieved]
                    cr.repairs = resp.repairs
                    sel = {r.name for r in resp.retrieved} if resp.retrieved else set()
                    cr.feature_selection_correct = expected_features.issubset(sel)
                    if resp.status == "ok" and resp.result is not None:
                        tol = (c.get("tolerance") or {}).get("float_abs", 0.01)
                        cr.result_correct = result_sets_equal(gold_rows, resp.result.rows, float_abs=tol)
                    else:
                        cr.result_correct = False
                        cr.failure = resp.error or f"status={resp.status}"
                except Exception as exc:
                    cr.actual_status = "error"
                    cr.result_correct = False
                    cr.failure = f"pipeline lỗi: {exc}"
        else:  # ---------- guardrail ----------
            if c.get("needs_llm") and not llm_on:
                cr.kind = "skipped"
            else:
                cr.kind = "guardrail"
                _, decision = router.route(q)
                status = _INTENT_STATUS.get(decision.intent, "ok")
                cr.actual_status = status
                rc = decision.refusal_code.value if decision.refusal_code else None
                exp_status = c.get("expected_status")
                exp_refusal = c.get("expected_refusal")
                cr.refusal_correct = status == exp_status and (exp_refusal is None or rc == exp_refusal)
                if not cr.refusal_correct:
                    cr.failure = f"got status={status} refusal={rc}, want {exp_status}/{exp_refusal}"

        results.append(cr)
        _persist(id_by_code.get(code), cr, tag, settings.llm_model if llm_on else "none")

    return {"tag": tag, "split": split, "lock_status": lock_status, "llm_on": llm_on,
            "model": settings.llm_model if llm_on else "none", "results": results}


def _persist(test_case_id: int | None, cr: CaseResult, tag: str, model: str) -> None:
    if test_case_id is None:
        return
    try:
        with get_engine().begin() as conn:
            conn.execute(text("""
                INSERT INTO eval.query_test_run
                  (test_case_id, retriever_version, prompt_version, model_name,
                   actual_features, actual_sql, retrieval_correct,
                   feature_selection_correct, result_correct, failure_reason)
                VALUES (:id, :tag, :pv, :model, CAST(:feats AS jsonb), :sql,
                        :retr, :fsel, :res, :fail)
            """), {
                "id": test_case_id, "tag": tag, "pv": PROMPT_VERSION, "model": model,
                "feats": json.dumps(cr.actual_features), "sql": cr.actual_sql,
                "retr": cr.retrieval_correct, "fsel": cr.feature_selection_correct,
                "res": cr.result_correct if cr.kind == "answerable" else cr.refusal_correct,
                "fail": cr.failure,
            })
    except Exception:
        pass  # eval không được làm hỏng run vì lỗi ghi log


def _rate(vals: list[bool | None]) -> str:
    hit = [v for v in vals if v is not None]
    if not hit:
        return "  n/a"
    return f"{sum(hit)}/{len(hit)} ({100*sum(hit)//len(hit)}%)"


def _recall_rate(vals: list[float | None]) -> str:
    measured = [v for v in vals if v is not None]
    if not measured:
        return "  n/a"
    return f"{100 * sum(measured) / len(measured):.0f}%"


def _percent(vals: list[bool | None]) -> str:
    measured = [v for v in vals if v is not None]
    if not measured:
        return "n/a"
    return f"{100 * sum(measured) / len(measured):.0f}%"


def _funnel_rate(cases: list[CaseResult], field: str) -> str:
    if not cases:
        return "n/a"
    success = sum(bool(getattr(case, field)) for case in cases)
    return f"{success}/{len(cases)} ({100 * success / len(cases):.0f}%)"


def _percentile_ms(vals: list[int | None], quantile: float) -> str:
    measured = sorted(v for v in vals if v is not None)
    if not measured:
        return "n/a"
    return f"{measured[min(len(measured) - 1, int(quantile * len(measured)))]}ms"


def _precision_recall(
    results: list[CaseResult], expected_status: str, actual_status: str
) -> tuple[str, str]:
    eligible = [r for r in results if r.kind != "skipped" and r.actual_status is not None]
    predicted = [r for r in eligible if r.actual_status == actual_status]
    positives = [r for r in eligible if _expected_status(r) == expected_status]
    true_positive = sum(
        _expected_status(r) == expected_status and r.actual_status == actual_status
        for r in eligible
    )
    precision = "n/a" if not predicted else f"{100 * true_positive / len(predicted):.0f}%"
    recall = "n/a" if not positives else f"{100 * true_positive / len(positives):.0f}%"
    return precision, recall


def _expected_status(result: CaseResult) -> str:
    return result.expected_status


def format_report(report: dict[str, Any]) -> str:
    results: list[CaseResult] = report["results"]
    lines = [
        f"=== EVAL REPORT  tag={report['tag']}  split={report.get('split', 'dev')}  "
        f"model={report['model']}  LLM={'on' if report['llm_on'] else 'OFF (offline metrics only)'} ===",
        f"  holdout: {report.get('lock_status', '')}",
    ]

    def block(title: str, groups: dict[str, list[CaseResult]]):
        lines.append(f"\n[{title}]")
        lines.append(f"  {'nhóm':<20} {'retrieval':>12} {'refusal':>12} {'exec_acc':>12} {'gold_ok':>10}")
        for g in sorted(groups):
            rs = groups[g]
            lines.append(
                f"  {g:<20} {_rate([r.retrieval_correct for r in rs]):>12} "
                f"{_rate([r.refusal_correct for r in rs]):>12} "
                f"{_rate([r.result_correct for r in rs]):>12} "
                f"{_rate([r.gold_executes for r in rs]):>10}"
            )

    by_diff: dict[str, list[CaseResult]] = defaultdict(list)
    by_cat: dict[str, list[CaseResult]] = defaultdict(list)
    for r in results:
        by_diff[r.difficulty].append(r)
        by_cat[r.category].append(r)
    block("Theo độ khó", by_diff)
    block("Theo category (mục đích)", by_cat)

    lines.append("\n[Recall@5]")
    for title, groups in (("difficulty", by_diff), ("category", by_cat)):
        rates = ", ".join(
            f"{group}={_recall_rate([r.retrieval_recall_at_5 for r in rows])}"
            for group, rows in sorted(groups.items())
        )
        lines.append(f"  {title}: {rates}")

    answerable = [r for r in results if r.kind == "answerable"]
    guardrail = [r for r in results if r.kind == "guardrail"]
    skipped = [r for r in results if r.kind == "skipped"]
    lat = sorted(r.latency_ms for r in answerable if r.latency_ms)
    p = lambda q: lat[min(len(lat) - 1, int(q * len(lat)))] if lat else 0
    lines.append("\n[Overall]")
    lines.append(f"  retrieval_hit@5 : {_rate([r.retrieval_correct for r in answerable])}")
    lines.append(f"  retrieval_recall@5: {_recall_rate([r.retrieval_recall_at_5 for r in answerable])}")
    lines.append(f"  refusal_accuracy: {_rate([r.refusal_correct for r in guardrail])}")
    lines.append(f"  execution_acc   : {_rate([r.result_correct for r in answerable])}")
    lines.append(f"  gold_sql_ok     : {_rate([r.gold_executes for r in answerable])}")
    lines.append(f"  latency p50/p95 : {p(0.5)}ms / {p(0.95)}ms" if lat else "  latency         : n/a (no LLM)")
    lines.append(f"  skipped (needs LLM): {len(skipped)}")

    def hit_at(k: int) -> list[bool | None]:
        return [
            bool(r.expected_feature_ranks) and all(
                rank is not None and rank <= k
                for rank in r.expected_feature_ranks.values()
            )
            for r in answerable
        ]

    first_ranks = [
        min((rank for rank in r.expected_feature_ranks.values() if rank is not None), default=None)
        for r in answerable
    ]
    mrr = "n/a" if not first_ranks else f"{sum(1 / rank for rank in first_ranks if rank) / len(first_ranks):.3f}"
    task_outcomes = [r.result_correct for r in answerable] + [r.refusal_correct for r in guardrail]
    clarification_precision, clarification_recall = _precision_recall(results, "clarify", "clarify")
    refusal_precision, refusal_recall = _precision_recall(results, "out_of_scope", "out_of_scope")
    expected_ok = [r for r in results if r.kind != "skipped" and r.expected_status == "ok"]
    over_refusal = _percent([r.actual_status == "out_of_scope" for r in expected_ok])

    lines.append("\n[Dataset health]")
    lines.append(f"  gold_sql_execution_rate       : {_percent([r.gold_executes for r in answerable])}")
    lines.append(f"  expected_result_available_rate: {_percent([r.expected_result_available for r in answerable])}")
    lines.append("\n[Retrieval]")
    lines.append(f"  retrieval_hit@1               : {_percent(hit_at(1))}")
    lines.append(f"  retrieval_hit@3               : {_percent(hit_at(3))}")
    lines.append(f"  retrieval_hit@5               : {_percent(hit_at(5))}")
    lines.append(f"  MRR                           : {mrr}")
    lines.append(f"  selected_context_accuracy     : {_percent([r.feature_selection_correct for r in answerable])}")
    sql_present = [r for r in answerable if r.generated_sql_present is not None]
    parsed = [r for r in sql_present if r.generated_sql_present]
    parsed_sql = [r for r in parsed if r.generated_sql_parses]
    valid_sql = [r for r in parsed_sql if r.schema_valid]
    executed_sql = [r for r in valid_sql if r.generated_sql_executes]
    lines.append("\n[SQL generation]")
    lines.append(f"  SQL present                    : {_funnel_rate(sql_present, 'generated_sql_present')}")
    lines.append(f"  Parse success | SQL present    : {_funnel_rate(parsed, 'generated_sql_parses')}")
    lines.append(f"  Schema valid | parsed          : {_funnel_rate(parsed_sql, 'schema_valid')}")
    lines.append(f"  Execution success | valid      : {_funnel_rate(valid_sql, 'generated_sql_executes')}")
    lines.append(f"  Result match | executed        : {_funnel_rate(executed_sql, 'result_correct')}")
    lines.append("\n[End-to-end]")
    lines.append(f"  result_match_accuracy         : {_percent([r.result_correct for r in answerable])}")
    lines.append(f"  task_success_rate             : {_percent(task_outcomes)}")
    lines.append("\n[Clarification / refusal]")
    lines.append(f"  clarification_precision       : {clarification_precision}")
    lines.append(f"  clarification_recall          : {clarification_recall}")
    lines.append(f"  refusal_precision             : {refusal_precision}")
    lines.append(f"  refusal_recall                : {refusal_recall}")
    lines.append(f"  over_refusal_rate             : {over_refusal}")
    lines.append("\n[Performance]")
    lines.append(f"  latency_p50                   : {_percentile_ms([r.latency_ms or None for r in answerable], .5)}")
    lines.append(f"  latency_p95                   : {_percentile_ms([r.latency_ms or None for r in answerable], .95)}")
    lines.append(f"  retrieval_latency_p95         : {_percentile_ms([r.retrieval_latency_ms for r in answerable], .95)}")
    lines.append(f"  llm_latency_p95               : {_percentile_ms([r.llm_latency_ms for r in answerable], .95)}")
    lines.append(f"  sql_latency_p95               : {_percentile_ms([r.sql_latency_ms for r in answerable], .95)}")
    return "\n".join(lines)
