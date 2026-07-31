from __future__ import annotations

import time
import json
from typing import Any, Callable

from sqlalchemy import text

from app.agent.breakdown import BreakdownPlanner, compile_breakdown, selected_features
from app.agent.conversation import ORDER_STATUS_OPTIONS
from app.agent.context import context_features, generation_request
from app.agent.contracts import IntentType, NarrationInput, PipelineContext, RepairRequest
from app.agent.generator import SQLGenerator
from app.agent.join_planner import JoinPlan, JoinPlanner
from app.agent.narrator import deterministic_answer
from app.agent.result_shape import classify_result_shape
from app.agent.router import RuleRouter
from app.agent.validator import PipelineValidator
from app.config import Settings, get_settings
from app.db import get_engine
from app.models.schemas import AskResponse, Confidence, CoverageInfo, RetrievedFeature
from app.semantic.retriever import ScoredFeature, get_semantic_layer
from app.sql.executor import run_query


# Chip cho slot mà router/retrieval hỏi lại — trước đây chỉ nhánh breakdown trả
# options, nên frontend phải đoán bằng danh sách hard-code và mời sai slot.
# Giá trị phải PARSE ĐƯỢC bởi `conversation._answer_slots`.
_SLOT_OPTIONS: dict[str, tuple[dict[str, str], ...]] = {
    "business_unit": (
        {"value": "GSM", "label": "GSM"},
        {"value": "VinFast", "label": "VinFast"},
        {"value": "Cả hai", "label": "Cả hai"},
    ),
    "window": tuple(
        {"value": label, "label": label}
        for label in ("1 tuần", "1 tháng", "3 tháng", "6 tháng", "12 tháng", "Tổng cộng")
    ),
    "top_n": ({"value": "Top 10", "label": "Top 10"}, {"value": "Top 20", "label": "Top 20"}),
    "order_status": ORDER_STATUS_OPTIONS,
}


def _options_for_slots(missing: list[str]) -> list[dict[str, str]]:
    return [option for slot in missing for option in _SLOT_OPTIONS.get(slot, ())]


# NULL ở các cột này là GIÁ TRỊ CÓ NGHĨA, không phải dữ liệu thiếu — xem
# `feature_spec._build()` và ADR 0003.
_SEMANTIC_NULL = frozenset({"no_history_in_unit", "never_event", "no_spend_to_compare"})


class AgentPipeline:
    def __init__(
        self,
        generator: SQLGenerator,
        *,
        router: RuleRouter | None = None,
        validator: PipelineValidator | None = None,
        settings: Settings | None = None,
        semantic_layer=None,
        narrator: Callable[[NarrationInput], str] | None = None,
        join_planner: JoinPlanner | None = None,
        breakdown_planner: BreakdownPlanner | None = None,
    ):
        self.settings = settings or get_settings()
        self.generator = generator
        self.router = router or RuleRouter()
        self.validator = validator or PipelineValidator()
        self.semantic_layer = semantic_layer or get_semantic_layer()
        self.narrator = narrator
        self.join_planner = join_planner
        self.breakdown_planner = breakdown_planner or BreakdownPlanner()

    def ask(
        self, question: str, session_id: str | None = None, *,
        join_plan: JoinPlan | None = None, state_transition: dict | None = None,
    ) -> AskResponse:
        started = time.perf_counter()
        trace: list[dict[str, Any]] = []

        def mark(
            stage: str,
            component: str,
            status: str,
            input_data: Any = None,
            output_data: Any = None,
            duration_ms: int | None = None,
        ):
            event = {
                "stage": stage,
                "component": component,
                "status": status,
                "input": input_data,
                "output": output_data,
            }
            if duration_ms is not None:
                event["duration_ms"] = duration_ms
            trace.append(event)

        try:
            dimensions = self.breakdown_planner.detect_dimensions(question)
            if dimensions:
                original, route = self.router.route(
                    question, self.settings.agent_max_question_chars,
                    breakdown_dimension=dimensions[0],
                )
            else:
                original, route = self.router.route(
                    question, self.settings.agent_max_question_chars,
                )
        except ValueError as exc:
            mark("normalize", "app.agent.router.normalize_question", "error", question, str(exc))
            return AskResponse(status="clarify", clarifying_question=str(exc), error=str(exc), pipeline_trace=trace)
        mark("router", "app.agent.router.RuleRouter", "completed", original, route.model_dump(mode="json"))
        normalized = " ".join(original.lower().split())
        context = PipelineContext(
            original_question=original, normalized_question=normalized, route=route
        )
        if route.intent in (IntentType.out_of_scope, IntentType.clarify):
            self._audit_terminal(
                original, route, session_id, int((time.perf_counter() - started) * 1000),
                state_transition=state_transition,
            )
            return AskResponse(
                status="out_of_scope" if route.intent == IntentType.out_of_scope else "clarify",
                answer_vi=route.reason, clarifying_question=route.clarifying_question,
                confidence=Confidence.high if route.confidence >= 0.9 else Confidence.medium,
                refusal_code=route.refusal_code.value if route.refusal_code else None,
                pipeline_trace=trace, known_slots=route.known_slots, missing_slots=route.missing_slots,
                clarification_options=_options_for_slots(route.missing_slots),
            )
        if self.breakdown_planner.needs_dimension_choice(question, dimensions):
            options = self.breakdown_planner.options_for(route.business_unit)
            route.intent = IntentType.clarify
            route.missing_slots = ["breakdown_dimension"]
            route.clarifying_question = (
                "Bạn muốn chia kết quả theo business unit, dịch vụ, trạng thái, "
                "cửa sổ thời gian hay xem tổng chung?"
            )
            self._audit_terminal(
                original, route, session_id, int((time.perf_counter() - started) * 1000),
                state_transition=state_transition,
            )
            return AskResponse(
                status="clarify", clarifying_question=route.clarifying_question,
                pipeline_trace=trace, known_slots=route.known_slots,
                missing_slots=route.missing_slots, clarification_options=options,
            )
        retrieval_started = time.perf_counter()
        scored = self.semantic_layer.retrieve(
            original, business_unit=route.business_unit
        )
        retrieval_ms = int((time.perf_counter() - retrieval_started) * 1000)
        # Câu mơ hồ khớp yếu nhiều feature (điểm top thấp) ⇒ hỏi lại thay vì sinh
        # SQL "gọi tất cả" (mục 5: ambiguous → ask back, đừng đoán).
        if not scored or scored[0].score < self.settings.retrieval_min_score:
            reason = "empty" if not scored else "low_confidence"
            mark("retriever", "app.semantic.retriever.SemanticLayer", reason, original,
                 [{"name": f.name, "score": f.score} for f in scored[:3]], retrieval_ms)
            route.intent = IntentType.clarify
            # Đừng hỏi lại slot đã biết: router gán được BU rồi thì chỉ còn thiếu chỉ số
            # và cửa sổ. Hỏi lại thứ user vừa nói là cách nhanh nhất để họ bỏ cuộc.
            route.missing_slots = [
                s for s in ("business_unit", "window") if s not in route.known_slots
            ] or ["window"]
            route.clarifying_question = "Câu hỏi chưa đủ rõ để chọn đúng chỉ số. Bạn muốn xem chỉ số nào (số chuyến, chi tiêu, tỷ lệ hủy...), của GSM hay VinFast, trong khoảng thời gian nào?"
            self._audit_terminal(
                original, route, session_id, int((time.perf_counter() - started) * 1000),
                state_transition=state_transition,
            )
            return AskResponse(
                status="clarify", clarifying_question=route.clarifying_question, pipeline_trace=trace,
                known_slots=route.known_slots, missing_slots=route.missing_slots,
                clarification_options=_options_for_slots(route.missing_slots),
            )
        mark("retriever", "app.semantic.retriever.SemanticLayer", "completed", original,
             [{"name": f.name, "table": f.table, "score": f.score} for f in scored], retrieval_ms)
        breakdown_decision = self.breakdown_planner.plan(
            original, route, getattr(self.semantic_layer, "features", ()), dimensions,
        )
        if breakdown_decision.clarifying_question:
            route.intent = IntentType.clarify
            route.missing_slots = (
                [breakdown_decision.missing_slot] if breakdown_decision.missing_slot else []
            )
            route.clarifying_question = breakdown_decision.clarifying_question
            self._audit_terminal(
                original, route, session_id, int((time.perf_counter() - started) * 1000),
                state_transition=state_transition,
            )
            return AskResponse(
                status="clarify", clarifying_question=route.clarifying_question,
                pipeline_trace=trace, known_slots=route.known_slots,
                missing_slots=route.missing_slots,
                clarification_options=list(breakdown_decision.options),
            )
        breakdown_plan = breakdown_decision.plan
        if breakdown_plan:
            context.breakdown_plan = breakdown_plan
            required = set(selected_features(breakdown_plan))
            have = {feature.name for feature in scored}
            for feature in getattr(self.semantic_layer, "features", ()):
                if feature["name"] not in required - have:
                    continue
                scored.append(ScoredFeature(
                    name=feature["name"], table=feature["table"],
                    group=feature.get("group", ""),
                    description_vi=feature.get("description_vi", ""),
                    description_en=feature.get("description_en", ""),
                    keywords=feature.get("keywords", []), score=10.0,
                    support_status=feature.get("support_status", "queryable"),
                    dtype=feature.get("dtype"), unit=feature.get("unit"),
                    null_meaning=feature.get("null_meaning"),
                    business_unit=feature.get("business_unit"),
                ))
                have.add(feature["name"])
            mark(
                "breakdown_planner", "app.agent.breakdown.BreakdownPlanner", "completed",
                {"dimensions": dimensions},
                breakdown_plan.model_dump(mode="json"),
            )
        context.retrieved = [f.__dict__ for f in scored]
        plan_dict: dict | None = None
        join_rules = ()
        if route.intent == IntentType.cross_bu:
            try:
                if self.join_planner is None:
                    self.join_planner = JoinPlanner.load_from_db(self.settings.sql_max_joins)
                decision = self.join_planner.plan_for_features(route.intent.value, scored)
            except Exception as exc:
                reason = "Không đọc được join catalog để lập kế hoạch cross-BU."
                self._audit_terminal(
                    original, route, session_id, int((time.perf_counter() - started) * 1000), reason,
                    state_transition=state_transition,
                )
                return AskResponse(status="error", error=reason, pipeline_trace=trace)
            plan = join_plan or decision.plan
            if plan is None:
                self._audit_terminal(
                    original, route, session_id, int((time.perf_counter() - started) * 1000), decision.reason_vi,
                    state_transition=state_transition,
                )
                return AskResponse(status="out_of_scope", answer_vi=decision.reason_vi, pipeline_trace=trace)
            if join_plan and not set(join_plan.tables) <= {f.table for f in scored}:
                return AskResponse(status="error", error="Join plan không khớp feature đã retrieve.", pipeline_trace=trace)
            plan_dict = plan.as_dict()
            join_rules = self.join_planner.rules
            mark("join_planner", "app.agent.join_planner.JoinPlanner", "completed",
                 {"intent": route.intent.value}, plan_dict)
        req = generation_request(original, route, scored, plan_dict, breakdown_plan)
        allowed = {f.name for f in context_features(route, scored, plan_dict)}
        generation_started = time.perf_counter()
        try:
            generation = (
                compile_breakdown(breakdown_plan, route.intent)
                if breakdown_plan and breakdown_plan.strategy != "physical_column"
                else self.generator.generate(req)
            )
        except Exception as exc:
            mark("generator", "app.agent.generator.SQLGenerator", "error",
                 {"question": original, "feature_count": len(scored)}, str(exc),
                 int((time.perf_counter() - generation_started) * 1000))
            self._audit_terminal(original, route, session_id, int((time.perf_counter() - started) * 1000), str(exc))
            return AskResponse(status="error", error=f"SQL generation failed: {exc}", pipeline_trace=trace)
        mark("generator", "app.agent.generator.SQLGenerator", "completed",
             {"question": original, "feature_count": len(scored)},
             generation.model_dump(mode="json"),
             int((time.perf_counter() - generation_started) * 1000))
        repairs = 0
        while True:
            validation = self.validator.validate(
                generation, allowed, self.settings, join_plan=plan_dict, join_rules=join_rules,
                breakdown_plan=breakdown_plan,
            )
            mark("validator", "app.agent.validator.PipelineValidator",
                 "valid" if validation.valid else "rejected",
                 {"sql": generation.sql, "selected_features": generation.selected_features},
                 validation.model_dump(mode="json"))
            context.generation, context.validation, context.repairs = generation, validation, repairs
            if validation.valid:
                break
            repairable = bool(validation.errors) and not any(
                x in " ".join(validation.errors).lower()
                for x in ("raw", "pii", "function bị cấm", "select *", "schema", "feature ngoài")
            ) and not (
                breakdown_plan and breakdown_plan.strategy != "physical_column"
            )
            if not repairable or repairs >= self.settings.sql_max_repairs:
                self._audit_terminal(
                    original, route, session_id, int((time.perf_counter() - started) * 1000),
                    "; ".join(validation.errors), generation.sql, validation.errors,
                )
                return AskResponse(status="error", sql=generation.sql, error="; ".join(validation.errors),
                                   repairs=repairs, pipeline_trace=trace)
            repairs += 1
            mark("repair", "app.agent.generator.SQLGenerator.repair", "requested",
                 {"error": validation.errors, "attempt": repairs}, None)
            repair_started = time.perf_counter()
            generation = self.generator.repair(
                request=RepairRequest(
                    question=original, previous_sql=generation.sql,
                    error="; ".join(validation.errors), feature_context=req.feature_context,
                    join_plan=plan_dict, breakdown_plan=breakdown_plan,
                ),
                intent=route.intent,
            )
            mark("repair", "app.agent.generator.SQLGenerator.repair", "completed", None, None,
                 int((time.perf_counter() - repair_started) * 1000))
        execution_started = time.perf_counter()
        try:
            safe_sql, result = run_query(
                validation.sql or generation.sql, self.settings,
                query_text=original, session_id=session_id,
                join_plan=plan_dict, join_rules=join_rules, state_transition=state_transition,
                breakdown_plan=(
                    breakdown_plan.model_dump(mode="json") if breakdown_plan else None
                ),
            )
            mark("executor", "app.sql.executor.run_query", "completed",
                 {"sql": safe_sql}, {"columns": result.columns, "row_count": result.row_count,
                                      "truncated": result.truncated},
                 int((time.perf_counter() - execution_started) * 1000))
        except Exception as exc:
            mark("executor", "app.sql.executor.run_query", "error", {"sql": generation.sql}, str(exc),
                 int((time.perf_counter() - execution_started) * 1000))
            if repairs < self.settings.sql_max_repairs and not (
                breakdown_plan and breakdown_plan.strategy != "physical_column"
            ):
                repairs += 1
                mark("repair", "app.agent.generator.SQLGenerator.repair", "requested",
                     {"error": str(exc), "attempt": repairs}, None)
                repair_started = time.perf_counter()
                generation = self.generator.repair(
                    RepairRequest(
                        question=original, previous_sql=generation.sql,
                        error=str(exc), feature_context=req.feature_context, join_plan=plan_dict,
                        breakdown_plan=breakdown_plan,
                    ), route.intent,
                )
                mark("repair", "app.agent.generator.SQLGenerator.repair", "completed", None, None,
                     int((time.perf_counter() - repair_started) * 1000))
                validation = self.validator.validate(
                    generation, allowed, self.settings, join_plan=plan_dict, join_rules=join_rules,
                    breakdown_plan=breakdown_plan,
                )
                mark("validator", "app.agent.validator.PipelineValidator",
                     "valid" if validation.valid else "rejected",
                     {"sql": generation.sql}, validation.model_dump(mode="json"))
                if validation.valid:
                    execution_started = time.perf_counter()
                    try:
                        safe_sql, result = run_query(
                            validation.sql or generation.sql, self.settings,
                            query_text=original, session_id=session_id,
                            join_plan=plan_dict, join_rules=join_rules, state_transition=state_transition,
                            breakdown_plan=(
                                breakdown_plan.model_dump(mode="json") if breakdown_plan else None
                            ),
                        )
                    except Exception as final_exc:
                        self._audit_terminal(
                            original, route, session_id, int((time.perf_counter() - started) * 1000),
                            str(final_exc), generation.sql, [],
                        )
                        return AskResponse(status="error", sql=generation.sql, error=str(final_exc),
                                           repairs=repairs, pipeline_trace=trace)
                    mark("executor", "app.sql.executor.run_query", "completed",
                         {"sql": safe_sql}, {"columns": result.columns, "row_count": result.row_count,
                                              "truncated": result.truncated},
                         int((time.perf_counter() - execution_started) * 1000))
                else:
                    self._audit_terminal(
                        original, route, session_id, int((time.perf_counter() - started) * 1000),
                        "; ".join(validation.errors), generation.sql, validation.errors,
                    )
                    return AskResponse(status="error", sql=generation.sql,
                                       error="; ".join(validation.errors), repairs=repairs,
                                       pipeline_trace=trace)
            else:
                self._audit_terminal(
                    original, route, session_id, int((time.perf_counter() - started) * 1000),
                    str(exc), generation.sql, [],
                )
                return AskResponse(status="error", sql=generation.sql, error=str(exc),
                                   repairs=repairs, pipeline_trace=trace)
        retrieved = [RetrievedFeature(**f.__dict__) for f in scored]
        coverage = self._coverage(result, breakdown_plan)
        narration_input = NarrationInput(
            question=original, sql=safe_sql, result=result,
            confidence=generation.confidence, coverage_note=coverage.note,
        )
        try:
            answer = self.narrator(narration_input) if self.narrator else deterministic_answer(narration_input)
            mark("narrator", "app.agent.narrator" if self.narrator else "app.agent.narrator.deterministic_answer",
                 "completed", {"row_count": result.row_count}, answer)
        except Exception:
            answer = deterministic_answer(narration_input)
            mark("narrator", "app.agent.narrator.deterministic_answer", "fallback",
                 {"row_count": result.row_count}, answer)
        return AskResponse(
            status="ok", answer_vi=answer, sql=safe_sql, result=result, retrieved=retrieved,
            confidence=Confidence.high if generation.confidence >= .8 else Confidence.medium,
            coverage=coverage, repairs=repairs, pipeline_trace=trace,
            join_explanation=plan_dict and plan_dict.get("explanation_vi"),
            result_shape=classify_result_shape(
                result,
                group_semantics=breakdown_plan.group_semantics if breakdown_plan else None,
            ),
            assumptions=generation.assumptions,
        )

    def _coverage(self, result, breakdown_plan) -> CoverageInfo:
        """Độ phủ chỉ tính trên cột mà NULL nghĩa là THIẾU dữ liệu.

        Bảng cross-BU cố ý để NULL: khách chỉ đi GSM thì `vinfast_spend_*` = NULL với
        `null_meaning = no_history_in_unit` ("chưa từng có dữ liệu ở đơn vị đó"). Đếm
        cả những ô đó thì mọi câu cross-BU — đúng năng lực khác biệt của dự án — đều bị
        gắn cờ "độ phủ thấp" sai nghĩa.
        """
        note = "Kết quả được tính trên feature snapshot Sprint 2."
        if breakdown_plan and breakdown_plan.group_semantics == "independent":
            note += " Các nhóm độc lập có thể chồng lấn; tổng nhóm có thể lớn hơn số khách duy nhất."
        if not result.rows:
            return CoverageInfo(note=note)
        semantic = {
            feature["name"]
            for feature in getattr(self.semantic_layer, "features", ())
            if feature.get("null_meaning") in _SEMANTIC_NULL
        }
        counted = [
            index for index, column in enumerate(result.columns)
            if column.lower() not in semantic
        ]
        if not counted:
            return CoverageInfo(
                note=note + " Các cột được hỏi dùng NULL làm giá trị có nghĩa "
                             "(chưa từng phát sinh ở đơn vị đó), nên không tính độ phủ.",
            )
        cells = len(result.rows) * len(counted)
        ratio = sum(
            row[index] is not None for row in result.rows for index in counted
        ) / cells
        is_low = ratio < self.settings.coverage_low_ratio
        if is_low:
            note += (
                f" Chỉ {ratio:.0%} ô có dữ liệu — hãy đọc số trung bình một cách thận trọng."
            )
        return CoverageInfo(non_null_ratio=ratio, note=note, is_low=is_low)

    @staticmethod
    def _audit_terminal(
        question, route, session_id, elapsed_ms, error=None, generated_sql=None, validation_errors=None,
        state_transition=None, join_plan=None, breakdown_plan=None,
    ):
        try:
            with get_engine().begin() as conn:
                query_id = conn.execute(text("""
                    INSERT INTO agent.query_log
                      (session_id, query_text, detected_intent, generated_sql, execution_status,
                       execution_time_ms, error_message, join_plan, breakdown_plan, state_transition)
                    VALUES (:session, :question, :intent, :sql, :status, :ms, :error,
                            CAST(:plan AS jsonb), CAST(:breakdown AS jsonb),
                            CAST(:transition AS jsonb))
                    RETURNING query_id
                """), {
                    "session": session_id, "question": question,
                    "intent": route.intent.value,
                    "status": "rejected" if route.intent == IntentType.out_of_scope else "clarification_required",
                    "sql": generated_sql, "ms": elapsed_ms, "error": error or route.reason,
                    "plan": json.dumps(join_plan) if join_plan else None,
                    "breakdown": json.dumps(breakdown_plan) if breakdown_plan else None,
                    "transition": json.dumps(state_transition) if state_transition else None,
                }).scalar_one()
                if generated_sql is not None:
                    conn.execute(text("""
                        INSERT INTO agent.sql_validation_log
                          (query_id, validator_version, sql_text, is_select_only,
                           has_select_star, accesses_raw_schema, has_disallowed_statement,
                           referenced_tables, validation_errors, is_valid)
                        VALUES (:id, 'sprint1-v1', :sql, FALSE, :star, :raw, TRUE,
                                '[]'::jsonb, CAST(:errors AS jsonb), FALSE)
                    """), {
                        "id": query_id, "sql": generated_sql,
                        "star": "*" in generated_sql, "raw": "raw." in generated_sql.lower(),
                        "errors": json.dumps(validation_errors or [error or "pipeline error"]),
                    })
        except Exception:
            pass
