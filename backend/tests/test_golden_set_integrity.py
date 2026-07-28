"""Golden set integrity: enum hợp lệ, feature canonical, gold_sql qua guard, seed khớp."""
import pytest

from app.eval.golden import load_golden_cases, validate_cases

CASES = load_golden_cases()


def test_cases_pass_static_validation():
    errors = validate_cases(CASES)
    assert errors == [], "Golden set lỗi:\n" + "\n".join(errors)


def test_case_count_and_distribution():
    assert len(CASES) == 60
    by_diff = {}
    for c in CASES:
        by_diff[c["difficulty"]] = by_diff.get(c["difficulty"], 0) + 1
    # Phủ đủ 3 tầng độ khó; hard đủ nhiều để đo semantic gap.
    assert set(by_diff) == {"easy", "medium", "hard"}
    assert by_diff["hard"] >= 8


def test_answerable_have_gold_sql_guardrail_dont():
    for c in CASES:
        if c["expected_status"] == "ok":
            assert c.get("gold_sql"), f"{c['code']} answerable thiếu gold_sql"
        else:
            assert c.get("gold_sql") is None, f"{c['code']} guardrail có gold_sql thừa"


def test_guardrail_refusal_codes_present():
    for c in CASES:
        if c["category"] in ("out_of_scope", "restricted_data"):
            assert c.get("expected_refusal"), f"{c['code']} thiếu expected_refusal"


def test_seed_matches_yaml_count():
    from scripts.seed_golden_set import seed
    from app.db import get_engine
    from sqlalchemy import text

    n = seed()
    with get_engine().connect() as conn:
        # Đếm ACTIVE: case rời YAML bị deactivate (giữ lịch sử), không xóa.
        db = conn.execute(text("SELECT COUNT(*) FROM eval.query_test_case WHERE is_active")).scalar_one()
    assert n == len(CASES) == db


# --- Task 1.4: dev/holdout split + lock discipline ---
def test_dev_holdout_disjoint_and_complete():
    from app.eval.golden import split_cases

    dev, hold = split_cases()
    dev_codes = {c["code"] for c in dev}
    hold_codes = {c["code"] for c in hold}
    assert dev_codes.isdisjoint(hold_codes), "dev và holdout không được trùng"
    assert dev_codes | hold_codes == {c["code"] for c in CASES}
    assert len(hold) == 20 and len(dev) == 40


def test_both_splits_cover_difficulty_and_guardrail():
    from app.eval.golden import split_cases

    for part in split_cases():
        diffs = {c["difficulty"] for c in part}
        assert {"easy", "medium", "hard"} <= diffs, "mỗi split phải phủ đủ độ khó"
        assert any(c["expected_status"] != "ok" for c in part), "mỗi split phải có guardrail"
        assert any(c["expected_status"] == "ok" for c in part), "mỗi split phải có answerable"


def test_holdout_checksum_deterministic():
    from app.eval.golden import holdout_checksum

    assert holdout_checksum() == holdout_checksum() and len(holdout_checksum()) == 64


def test_holdout_gate_enforced(tmp_path, monkeypatch):
    """Đo holdout: chưa khóa → raise; drift → raise; khớp → ok."""
    import app.eval.golden as g

    cf = tmp_path / "HOLDOUT_CHECKSUM"
    monkeypatch.setattr(g, "checksum_file", lambda path=None: str(cf))

    with pytest.raises(RuntimeError, match="chưa khóa"):   # chưa lock
        g.assert_holdout_unchanged()

    cf.write_text(g.holdout_checksum(), encoding="utf-8")  # lock đúng
    assert "nguyên vẹn" in g.assert_holdout_unchanged()

    cf.write_text("deadbeef", encoding="utf-8")            # drift
    with pytest.raises(RuntimeError, match="leakage"):
        g.assert_holdout_unchanged()
