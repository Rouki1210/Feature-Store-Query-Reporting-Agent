from __future__ import annotations

from app.agent.contracts import GenerationRequest, RouteDecision
from app.semantic.retriever import ScoredFeature


def _with_state_flags(features: list[ScoredFeature]) -> list[ScoredFeature]:
    """Bổ sung cờ trạng thái cùng bảng vào context, dù retrieval không xếp hạng chúng.

    Câu "chi tiêu VinFast trung bình của khách HOẠT ĐỘNG GSM" cần hai loại cột khác
    nhau: một CHỈ SỐ để tính và một CỜ để lọc. Retrieval xếp hạng theo độ giống câu
    hỏi nên cột chỉ số luôn thắng, cờ rớt khỏi top-k — LLM không còn gì để lọc và
    quay ra tính trung bình trên toàn bộ khách (sai mẫu số, SQL vẫn đúng cú pháp).

    Cờ rẻ: cả catalog chỉ có 19 cột boolean, thêm vài dòng vào context không đáng kể.
    """
    tables = {f.table for f in features}
    have = {f.name for f in features}
    extra = [
        f for f in _flag_pool()
        if f.table in tables and f.name not in have
    ]
    return features + extra


def _flag_pool() -> list[ScoredFeature]:
    from app.semantic.retriever import get_semantic_layer

    layer = get_semantic_layer()
    return [
        ScoredFeature(
            name=f["name"], table=f["table"], group=f.get("group", ""),
            description_vi=f.get("description_vi", ""), description_en=f.get("description_en", ""),
            keywords=[], score=0.0, dtype=f.get("dtype"), unit=f.get("unit"),
            null_meaning=f.get("null_meaning"), business_unit=f.get("business_unit"),
        )
        for f in layer.features
        if f.get("dtype") == "boolean"
    ]


def context_features(
    route: RouteDecision, features: list[ScoredFeature], join_plan: dict | None = None,
) -> list[ScoredFeature]:
    # Lọc theo BU của route, TRỪ khi join plan đã chốt bảng: plan cross-BU gồm hai bảng
    # gắn nhãn GSM/VINFAST trong khi route.business_unit là CROSS_BU, lọc tiếp sẽ xoá
    # sạch context và generator không còn cột nào để dùng.
    plan_tables = {str(t).lower() for t in (join_plan or {}).get("tables", [])}
    allowed = [
        f for f in features
        if route.business_unit is None
        or (f.table or "").lower() in plan_tables
        or (f.business_unit or "").upper() == route.business_unit.upper()
    ]
    return _with_state_flags(allowed)


def build_feature_context(
    route: RouteDecision, features: list[ScoredFeature], join_plan: dict | None = None,
    max_chars: int = 12000,
) -> str:
    allowed = context_features(route, features, join_plan)
    lines = [
        "Sprint 2 scope: one row per customer_id + snapshot_date.",
        "Query only the retrieved, allowlisted feature columns below.",
        "Only feature.* and metadata.* are queryable. Never query raw.* or PII.",
        "Use one SELECT/WITH statement, schema-qualified tables, and never SELECT *.",
        "A completed/finished VinFast transaction is transaction status only; it is not vehicle ownership.",
        "NVSO and work_order/WO are needs_review business terms; do not expand or infer their meaning.",
        # Đừng phát biểu tổng quát về NULL: mỗi feature mang `null=` riêng ở dòng của nó
        # (no_event_in_window | zero_denominator | never_event | always_present |
        # no_history_in_unit | no_spend_to_compare). Câu tổng quát sẽ mâu thuẫn với
        # chính dữ liệu bên dưới — đúng thứ Task 2.3 sinh ra để phân biệt.
        "Read the null= field on each feature line; NULL does not mean the same thing for every feature.",
        "In particular no_history_in_unit means the customer never had data in that unit, "
        "while 0 means they had data but nothing in the window. Averages must state which "
        "denominator they use.",
        "Keep the SQL at customer_id + snapshot_date grain and do not join raw tables.",
    ]
    if join_plan:
        lines.append(
            "Join plan (authoritative): reason=" + join_plan.get("explanation_vi", "")
            + "; allowed_tables=" + ", ".join(join_plan.get("tables", []))
            + "; join_type=" + str(join_plan.get("join_type") or "none")
            + "; join_keys=" + ", ".join(join_plan.get("join_keys", [])) + "."
        )
    for f in allowed:
        lines.append(
            f"- {f.name} | table={f.table} | group={f.group} | "
            f"dtype={f.dtype or 'unknown'} | unit={f.unit or '-'} | "
            f"status={f.support_status} | null={f.null_meaning or '-'} | "
            f"score={f.score} | VI={f.description_vi} | EN={f.description_en}"
        )
    text = "\n".join(lines)
    return text[:max_chars]


def generation_request(
    question: str, route: RouteDecision, features: list[ScoredFeature], join_plan: dict | None = None,
) -> GenerationRequest:
    return GenerationRequest(
        question=question, route=route,
        feature_context=build_feature_context(route, features, join_plan), join_plan=join_plan,
    )
