"""Task 2.7 — prompt và feature context là INTERFACE với LLM, không phải tài liệu.

LLM chỉ thấy hai thứ: `SYSTEM_PROMPT` và chuỗi `feature_context`. Sai ở đây thì mọi
tầng dưới (validator, guard) chỉ chặn được hậu quả chứ không sửa được nguyên nhân —
agent sẽ lặp lại cùng một lỗi qua từng vòng repair.
"""
from __future__ import annotations

from app.agent.context import build_feature_context
from app.agent.contracts import IntentType, RouteDecision
from app.agent.generator import PROMPT_VERSION, SYSTEM_PROMPT
from app.agent.validator import CANONICAL_FEATURES, LEGACY_FEATURE_COLUMNS
from app.semantic.retriever import ScoredFeature

GSM, VF = "feature.gsm_transaction", "feature.vinfast_transaction"


def _feature(name: str, table: str, unit: str, null_meaning: str = "no_event_in_window"):
    return ScoredFeature(
        name=name, table=table, group="g", description_vi="vi", description_en="en",
        keywords=[], score=5.0, business_unit=unit, null_meaning=null_meaning,
    )


def test_prompt_never_teaches_a_legacy_column():
    """Prompt nhắc cột legacy = dạy LLM cái mà validator chắc chắn reject."""
    import re

    leaked = [c for c in LEGACY_FEATURE_COLUMNS if re.search(rf"\b{re.escape(c)}\b", SYSTEM_PROMPT)]
    assert not leaked, f"prompt nhắc cột không query được: {leaked}"


def test_prompt_separates_buyer_scheduled_owner():
    for column in ("is_vehicle_buyer", "is_vehicle_owner", "is_vehicle_handover_scheduled"):
        assert column in SYSTEM_PROMPT, column
        assert column in CANONICAL_FEATURES


def test_prompt_version_is_recorded_in_changelog():
    """Bump version mà không ghi lý do thì before/after không so được."""
    import pathlib

    changelog = (pathlib.Path(__file__).resolve().parents[2] / "prompts" / "CHANGELOG.md")
    assert changelog.exists(), "thiếu prompts/CHANGELOG.md"
    assert PROMPT_VERSION in changelog.read_text(encoding="utf-8")


def test_context_defers_null_meaning_to_each_feature():
    """Không được phát biểu tổng quát về NULL: 6 loại null cùng tồn tại trong catalog."""
    route = RouteDecision(intent=IntentType.single_bu, business_unit="VINFAST", confidence=0.8)
    context = build_feature_context(route, [
        _feature("vinfast_spend_l1m", VF, "VINFAST", "no_history_in_unit"),
    ])
    assert "null=no_history_in_unit" in context
    assert "NULL means no event in the requested window" not in context


def test_join_plan_tables_survive_the_business_unit_filter():
    """Plan cross-BU gồm hai bảng gắn nhãn GSM/VINFAST, còn route là CROSS_BU.

    Lọc theo BU mà không trừ bảng trong plan sẽ để lại context RỖNG — generator
    không còn cột nào để dùng, và lỗi chỉ lộ ra ở ca dùng join runtime đầu tiên.
    """
    route = RouteDecision(intent=IntentType.cross_bu, business_unit="CROSS_BU", confidence=0.85)
    features = [
        _feature("completed_txn_count_l1m", GSM, "GSM"),
        _feature("txn_completed_count_l1m", VF, "VINFAST"),
    ]
    plan = {
        "tables": [GSM, VF], "join_keys": ["customer_id", "snapshot_date"],
        "join_type": "inner", "explanation_vi": "ghép theo khách và snapshot",
    }
    context = build_feature_context(route, features, plan)
    assert sum(1 for line in context.splitlines() if line.startswith("- ")) == 2
    assert "join_keys=customer_id, snapshot_date" in context


def test_cross_bu_route_still_filters_out_single_bu_features_without_plan():
    """Không có plan thì lọc BU vẫn phải chặt — đừng nới thành cửa hậu."""
    route = RouteDecision(intent=IntentType.cross_bu, business_unit="CROSS_BU", confidence=0.85)
    context = build_feature_context(route, [_feature("completed_txn_count_l1m", GSM, "GSM")])
    assert not [line for line in context.splitlines() if line.startswith("- ")]
