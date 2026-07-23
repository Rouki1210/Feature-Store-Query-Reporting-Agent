from __future__ import annotations

import json
from typing import Any

from app.agent.contracts import GenerationRequest, GenerationResponse, IntentType, RepairRequest
from app.agent.llm_client import JSONLLM

SYSTEM_PROMPT = """You are the read-only SQL Generator for the Sprint 1 Feature Store.

TASK
- Convert the user's business question into exactly ONE PostgreSQL SELECT or WITH...SELECT statement.
- Use only the tables and feature columns explicitly listed in feature_context.
- Query precomputed features directly. Never reconstruct features from raw events.

MANDATORY RULES
1. Only the feature and metadata schemas are allowed. Every physical table name must
   be schema-qualified.
2. Never use raw.*, PII, DML, DDL, SELECT *, system functions, or multiple statements.
3. Always enumerate projected columns. COUNT(*) is allowed only when counting rows is
   genuinely required by the question.
4. Feature-table grain is customer_id + snapshot_date.
5. When the user does not specify a snapshot, select the latest snapshot from the same
   feature table:
   snapshot_date = (SELECT MAX(snapshot_date) FROM <same_feature_table>).
6. Use precomputed time-window columns such as *_l1m, *_l3m, and *_l12m. Do not turn
   those windows into date filters over raw data.
7. A completed VinFast order means only that the order status is completed. It is not
   evidence of vehicle handover or ownership.
8. selected_features must contain only feature columns that actually appear in the SQL.
   Do not include customer_id, snapshot_date, aliases, or aggregate labels.
9. Never invent a table or column to fill missing context. Record necessary assumptions
   in the assumptions array.
10. Understand Vietnamese and English questions, but always generate PostgreSQL syntax.

OUTPUT CONTRACT
Return exactly one JSON object. Do not use Markdown or add text outside the JSON:
{
  "sql": "string",
  "selected_features": ["string"],
  "intent": "single_bu|aggregate|filter|window_compare",
  "assumptions": ["string"],
  "confidence": 0.0
}

The field types are strict:
- sql: string
- selected_features: array of strings
- intent: exactly one of the four enum values shown above
- assumptions: array of strings, never a single string
- confidence: number between 0 and 1
"""


class SQLGenerator:
    def __init__(self, client: JSONLLM):
        self.client = client

    def generate(self, request: GenerationRequest) -> GenerationResponse:
        payload = self.client.complete_json(
            SYSTEM_PROMPT,
            json.dumps({"question": request.question, "intent": request.route.intent.value,
                        "business_unit": request.route.business_unit,
                        "feature_context": request.feature_context}, ensure_ascii=False),
        )
        return self._parse(payload, request.route.intent)

    def repair(self, request: RepairRequest, intent: IntentType) -> GenerationResponse:
        payload = self.client.complete_json(
            SYSTEM_PROMPT,
            json.dumps({"question": request.question, "previous_sql": request.previous_sql,
                        "error": request.error, "feature_context": request.feature_context}, ensure_ascii=False),
        )
        return self._parse(payload, intent)

    @staticmethod
    def _parse(payload: dict[str, Any], fallback_intent: IntentType) -> GenerationResponse:
        sql = payload.get("sql")
        if not isinstance(sql, str) or not sql.strip():
            raise ValueError("Generator không trả SQL hợp lệ.")
        sql = sql.strip()
        if sql.startswith("```"):
            sql = sql.removeprefix("```sql").removeprefix("```").removesuffix("```").strip()
        selected = payload.get("selected_features", [])
        if isinstance(selected, str):
            selected = [selected]
        if selected is None:
            selected = []
        if not isinstance(selected, list) or not all(isinstance(x, str) for x in selected):
            raise ValueError("selected_features phải là list[str].")
        assumptions = payload.get("assumptions", [])
        if isinstance(assumptions, str):
            assumptions = [assumptions]
        if assumptions is None:
            assumptions = []
        if not isinstance(assumptions, list):
            assumptions = [str(assumptions)]
        assumptions = [str(item) for item in assumptions if str(item).strip()]
        try:
            intent = IntentType(payload.get("intent", fallback_intent))
        except ValueError:
            intent = fallback_intent
        try:
            confidence = float(payload.get("confidence", 0.5))
        except (TypeError, ValueError):
            confidence = 0.5
        confidence = min(1.0, max(0.0, confidence))
        return GenerationResponse(
            sql=sql, selected_features=selected,
            intent=intent, assumptions=assumptions, confidence=confidence,
        )
