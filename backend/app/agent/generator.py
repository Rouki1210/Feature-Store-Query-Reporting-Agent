from __future__ import annotations

import json
from typing import Any

from app.agent.contracts import GenerationRequest, GenerationResponse, IntentType, RepairRequest
from app.agent.llm_client import JSONLLM

# Bump khi sửa SYSTEM_PROMPT — nhãn cho eval.query_test_run.prompt_version (so before/after).
# Mỗi lần bump phải thêm một dòng vào prompts/CHANGELOG.md kèm số eval trước/sau.
PROMPT_VERSION = "sprint2-v7"

SYSTEM_PROMPT = """You are the read-only SQL Generator for the Sprint 2 Feature Store.

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
4. Feature-table grain is customer_id + snapshot_date. Use snapshot_date only in filters;
   never project snapshot_date unless the user explicitly asks for it.
5. When the user does not specify a snapshot, select the latest snapshot from the same
   feature table:
   snapshot_date = (SELECT MAX(snapshot_date) FROM <same_feature_table>).
   This scalar subquery is mandatory: never use a CTE, comma-separated FROM item, or JOIN
   merely to obtain the latest snapshot.
6. Use precomputed time-window columns such as *_l1m, *_l3m, and *_l12m. Do not turn
   those windows into date filters over raw data.
7. A completed VinFast order, or is_vehicle_buyer, means only that the order reached
   completed status. It is not evidence of vehicle handover or ownership. Only the
   handover-derived is_vehicle_owner identifies a vehicle owner, and
   is_vehicle_handover_scheduled means a handover is booked but has NOT happened yet.
   Buyer, scheduled, and owner are three different groups; never substitute one for another.
8. selected_features must contain only feature columns that actually appear in the SQL.
   Do not include customer_id, snapshot_date, aliases, or aggregate labels.
9. Never invent a table or column to fill missing context. Record necessary assumptions
   in the assumptions array.
10. For per-customer lists, project exactly customer_id plus the requested feature columns,
    ORDER BY customer_id, and LIMIT 100 unless the user explicitly asks for a different
    ranking or limit. For Top-N requests, project customer_id plus the requested metric,
    then use `ORDER BY <metric> DESC NULLS LAST, customer_id` and that N. Never add
    `<metric> IS NOT NULL` unless the user explicitly asks to exclude missing values.
    Project only the requested metric(s); never add neighbouring retrieved features. For an
    aggregate question, return only the requested aggregate expression, never a customer
    list, `LIMIT`, or `DISTINCT` when the feature table is already one row per customer.
11. Semantic mapping rules:
    - For days_since_* features, use the retrieved feature's window. A phrase such as
      "within 30 days" is a filter on that feature, not a reason to change its window.
    - "amount", "value", "spend", and "giá trị" map to *_amount_* features; "price"
      and "giá gốc" map to *_price_* or *_original_price_* features. Never substitute one.
    - For a comparison or trend, project exactly the selected *_vs_* ratio feature; do not
      add its base-window columns or neighbouring ratio features.
    - "xu hướng/thay đổi gần đây" maps to the available l1m_vs_l3m ratio when no second
      window is stated. "cao nhất/lớn nhất" over a feature maps to MAX(feature).
    - General completed VinFast transactions map to txn_completed_count_*; use
      vehicle_purchase_completed_count_* only when the question explicitly says mua xe,
      vehicle purchase, or đơn xe.
12. For cross-BU questions, use feature.customer_cross_bu_feature first when its retrieved
    features answer the question. Prefer `is_cross_bu_active_*` for "cả hai/đồng thời"
    activity and `combined_spend_*` for combined spend; never reconstruct either from
    component spend/activity flags when the precomputed feature is available. Runtime JOIN
    is permitted only when join_plan is present:
   use exactly its tables, join type, and join keys. Never invent join keys, use CROSS JOIN,
   omit ON, or hide a join inside a CTE/subquery. WITH...SELECT is allowed but at most two CTEs.
   When the user asks for revenue and customer count "by/for each business unit", return
   exactly `business_unit, customer_count, total_revenue` with one `UNION ALL` branch for
   GSM and one for VINFAST. Use `COUNT(*) FILTER (WHERE is_active_<bu>_<window>)` and
   `SUM(<bu>_spend_<window>)` in each branch. Do not collapse the two rows with
   `combined_spend_*`. If no time window is stated, use the `_all` features in both branches.
13. assumptions may state only a short, checkable data limitation or scope assumption for a
   partial answer. They never excuse missing SQL predicates, missing features, or an unsupported join.
14. Use boolean activity/ownership flags when the question names that state. Do not infer an
    active flag from spend, and do not infer owner from purchase/completed status. When the
    question restricts the population ("customers active on GSM", "vehicle owners"), put that
    flag in WHERE; never approximate it with a value column.
15. Never wrap a feature in COALESCE(feature, 0) inside AVG, SUM or any aggregate in order to
    replace missing data. For a no_history_in_unit feature, NULL means the customer is outside
    the population being measured, so counting them as 0 silently changes the denominator and
    the answer. COALESCE is allowed only when the user explicitly asks to treat missing as zero.
16. Understand Vietnamese and English questions, but always generate PostgreSQL syntax.

OUTPUT CONTRACT
Return exactly one JSON object. Do not use Markdown or add text outside the JSON:
{
  "sql": "string",
  "selected_features": ["string"],
  "intent": "cross_bu|single_bu|aggregate|filter|window_compare",
  "assumptions": ["string"],
  "confidence": 0.0
}

The field types are strict:
- sql: string
- selected_features: array of strings
- intent: exactly one of the five query enum values shown above
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
                        "feature_context": request.feature_context,
                        "join_plan": request.join_plan}, ensure_ascii=False),
        )
        return self._parse(payload, request.route.intent)

    def repair(self, request: RepairRequest, intent: IntentType) -> GenerationResponse:
        payload = self.client.complete_json(
            SYSTEM_PROMPT,
            json.dumps({"question": request.question, "previous_sql": request.previous_sql,
                        "error": request.error, "feature_context": request.feature_context,
                        "join_plan": request.join_plan}, ensure_ascii=False),
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
