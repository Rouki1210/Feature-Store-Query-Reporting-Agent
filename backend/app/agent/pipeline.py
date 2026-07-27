from __future__ import annotations

import time
import json
from typing import Any, Callable

from sqlalchemy import text

from app.agent.context import generation_request
from app.agent.contracts import IntentType, NarrationInput, PipelineContext, RepairRequest
from app.agent.generator import SQLGenerator
from app.agent.narrator import deterministic_answer
from app.agent.router import RuleRouter
from app.agent.validator import PipelineValidator
from app.config import Settings, get_settings
from app.db import get_engine
from app.models.schemas import AskResponse, Confidence, CoverageInfo, RetrievedFeature
from app.semantic.retriever import ScoredFeature, get_semantic_layer
from app.sql.executor import run_query


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
    ):
        self.settings = settings or get_settings()
        self.generator = generator
        self.router = router or RuleRouter()
        self.validator = validator or PipelineValidator()
        self.semantic_layer = semantic_layer or get_semantic_layer()
        self.narrator = narrator

    def ask(self, question: str, session_id: str | None = None) -> AskResponse:
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
            original, route = self.router.route(question, self.settings.agent_max_question_chars)
        except ValueError as exc:
            mark("normalize", "app.agent.router.normalize_question", "error", question, str(exc))
            return AskResponse(status="clarify", clarifying_question=str(exc), error=str(exc), pipeline_trace=trace)
        mark("router", "app.agent.router.RuleRouter", "completed", original, route.model_dump(mode="json"))
        normalized = " ".join(original.lower().split())
        context = PipelineContext(
            original_question=original, normalized_question=normalized, route=route
        )
        if route.intent in (IntentType.out_of_scope, IntentType.clarify):
            self._audit_terminal(original, route, session_id, int((time.perf_counter() - started) * 1000))
            return AskResponse(
                status="out_of_scope" if route.intent == IntentType.out_of_scope else "clarify",
                answer_vi=route.reason, clarifying_question=route.clarifying_question,
                confidence=Confidence.high if route.confidence >= 0.9 else Confidence.medium,
                refusal_code=route.refusal_code.value if route.refusal_code else None,
                pipeline_trace=trace,
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
            route.clarifying_question = "Câu hỏi chưa đủ rõ để chọn đúng chỉ số. Bạn muốn xem chỉ số nào (số chuyến, chi tiêu, tỷ lệ hủy...), của GSM hay VinFast, trong khoảng thời gian nào?"
            self._audit_terminal(original, route, session_id, int((time.perf_counter() - started) * 1000))
            return AskResponse(status="clarify", clarifying_question=route.clarifying_question, pipeline_trace=trace)
        mark("retriever", "app.semantic.retriever.SemanticLayer", "completed", original,
             [{"name": f.name, "table": f.table, "score": f.score} for f in scored], retrieval_ms)
        context.retrieved = [f.__dict__ for f in scored]
        req = generation_request(original, route, scored)
        allowed = {f.name for f in scored}
        generation_started = time.perf_counter()
        try:
            generation = self.generator.generate(req)
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
            validation = self.validator.validate(generation, allowed, self.settings)
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
            )
            mark("executor", "app.sql.executor.run_query", "completed",
                 {"sql": safe_sql}, {"columns": result.columns, "row_count": result.row_count,
                                      "truncated": result.truncated},
                 int((time.perf_counter() - execution_started) * 1000))
        except Exception as exc:
            mark("executor", "app.sql.executor.run_query", "error", {"sql": generation.sql}, str(exc),
                 int((time.perf_counter() - execution_started) * 1000))
            if repairs < self.settings.sql_max_repairs:
                repairs += 1
                mark("repair", "app.agent.generator.SQLGenerator.repair", "requested",
                     {"error": str(exc), "attempt": repairs}, None)
                repair_started = time.perf_counter()
                generation = self.generator.repair(
                    RepairRequest(
                        question=original, previous_sql=generation.sql,
                        error=str(exc), feature_context=req.feature_context,
                    ), route.intent,
                )
                mark("repair", "app.agent.generator.SQLGenerator.repair", "completed", None, None,
                     int((time.perf_counter() - repair_started) * 1000))
                validation = self.validator.validate(generation, allowed, self.settings)
                mark("validator", "app.agent.validator.PipelineValidator",
                     "valid" if validation.valid else "rejected",
                     {"sql": generation.sql}, validation.model_dump(mode="json"))
                if validation.valid:
                    execution_started = time.perf_counter()
                    try:
                        safe_sql, result = run_query(validation.sql or generation.sql, self.settings,
                                                     query_text=original, session_id=session_id)
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
        non_null = None
        if result.rows:
            non_null = sum(v is not None for row in result.rows for v in row) / (len(result.rows) * len(result.columns))
        coverage = CoverageInfo(non_null_ratio=non_null, note="Kết quả được tính trên feature snapshot Sprint 1.")
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
        )

    @staticmethod
    def _audit_terminal(question, route, session_id, elapsed_ms, error=None, generated_sql=None, validation_errors=None):
        try:
            with get_engine().begin() as conn:
                query_id = conn.execute(text("""
                    INSERT INTO agent.query_log
                      (session_id, query_text, detected_intent, generated_sql, execution_status,
                       execution_time_ms, error_message)
                    VALUES (:session, :question, :intent, :sql, :status, :ms, :error)
                    RETURNING query_id
                """), {
                    "session": session_id, "question": question,
                    "intent": route.intent.value,
                    "status": "rejected" if route.intent == IntentType.out_of_scope else "clarification_required",
                    "sql": generated_sql, "ms": elapsed_ms, "error": error or route.reason,
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
