from __future__ import annotations

from app.agent.contracts import GenerationRequest, RouteDecision
from app.semantic.retriever import ScoredFeature


def build_feature_context(route: RouteDecision, features: list[ScoredFeature], max_chars: int = 12000) -> str:
    allowed = [f for f in features if route.business_unit is None or f.table.split(".", 1)[-1].startswith(route.business_unit.lower())]
    lines = [
        "Sprint 1 scope: one row per customer_id + snapshot_date.",
        "Query only the retrieved, allowlisted feature columns below.",
        "Only feature.* and metadata.* are queryable. Never query raw.* or PII.",
        "Use one SELECT/WITH statement, schema-qualified tables, and never SELECT *.",
        "A completed/finished VinFast transaction is transaction status only; it is not vehicle ownership.",
        "NVSO and work_order/WO are needs_review business terms; do not expand or infer their meaning.",
        "NULL means no event in the requested window unless the feature says zero_denominator.",
        "Keep the SQL at customer_id + snapshot_date grain and do not join raw tables.",
    ]
    for f in allowed:
        lines.append(
            f"- {f.name} | table={f.table} | group={f.group} | "
            f"dtype={f.dtype or 'unknown'} | unit={f.unit or '-'} | "
            f"status={f.support_status} | null={f.null_meaning or '-'} | "
            f"score={f.score} | VI={f.description_vi} | EN={f.description_en}"
        )
    text = "\n".join(lines)
    return text[:max_chars]


def generation_request(question: str, route: RouteDecision, features: list[ScoredFeature]) -> GenerationRequest:
    return GenerationRequest(
        question=question, route=route, feature_context=build_feature_context(route, features)
    )
