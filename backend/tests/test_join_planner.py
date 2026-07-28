"""Task 2.4 — allow-listed, intent-aware join planning."""
from app.agent.join_planner import CROSS_BU_TABLE, JoinPlanner, JoinRule


GSM = "feature.gsm_transaction"
VF = "feature.vinfast_transaction"


def test_cross_bu_rule_requires_the_allowed_intent():
    planner = JoinPlanner()
    assert planner.plan("cross_bu", {GSM, VF}).ok
    denied = planner.plan("single_bu", {GSM, VF})
    assert not denied.ok and "Intent" in denied.reason_vi


def test_precomputed_cross_bu_table_wins_over_runtime_join():
    decision = JoinPlanner().plan("cross_bu", {CROSS_BU_TABLE, GSM, VF})
    assert decision.ok
    assert decision.plan.tables == (CROSS_BU_TABLE,)
    assert decision.plan.source == "precomputed"
    assert not decision.plan.needs_join


def test_missing_snapshot_key_is_rejected_even_for_manual_rule():
    bad = JoinRule(
        GSM, VF, ("customer_id",), allowed_intents=("cross_bu",), requires_snapshot_key=True,
    )
    decision = JoinPlanner((bad,)).plan("cross_bu", {GSM, VF})
    assert not decision.ok and "snapshot_date" in decision.reason_vi


def test_inactive_rule_is_not_a_join_path():
    disabled = JoinRule(
        GSM, VF, ("customer_id", "snapshot_date"), allowed_intents=("cross_bu",), is_active=False,
    )
    assert not JoinPlanner((disabled,)).plan("cross_bu", {GSM, VF}).ok
