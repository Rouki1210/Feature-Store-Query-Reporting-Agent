"""Test SQL guards — chạy TRƯỚC khi bất cứ thứ gì gọi LLM (CLAUDE.md mục 6 bước 3).

    cd backend && python -m pytest tests/test_guards.py -v
"""
from __future__ import annotations

import pytest

from app.config import Settings
from app.agent.join_planner import JoinPlanner
from app.sql.guards import GuardError, is_safe, validate_sql

# Settings cố định cho test (không phụ thuộc .env).
SETTINGS = Settings(
    SQL_MAX_ROWS=100,
    SQL_SENSITIVE_COLUMNS="phone,email,national_id,customer_name",
)
JOIN_PLAN = JoinPlanner().plan("cross_bu", {
    "feature.gsm_transaction", "feature.vinfast_transaction",
}).plan.as_dict()
JOIN_RULES = JoinPlanner().rules


# ---------------- Truy vấn hợp lệ ----------------

def test_select_passes_and_gets_limit():
    safe = validate_sql("SELECT customer_id FROM feature.gsm_transaction", SETTINGS)
    assert safe.upper().startswith("SELECT")
    assert "LIMIT 100" in safe.upper()


def test_with_cte_passes():
    sql = "WITH t AS (SELECT customer_id FROM feature.gsm_transaction) SELECT customer_id FROM t"
    assert is_safe(sql, SETTINGS)


def test_ast_rejects_write_hidden_in_cte():
    with pytest.raises(GuardError):
        validate_sql(
            "WITH changed AS (DELETE FROM feature.gsm_transaction RETURNING customer_id) "
            "SELECT customer_id FROM changed",
            SETTINGS,
        )


def test_count_star_is_allowed():
    # COUNT(*) hợp lệ; chỉ 'SELECT *' mới bị chặn.
    safe = validate_sql("SELECT COUNT(*) AS n FROM feature.gsm_transaction", SETTINGS)
    assert "COUNT(*)" in safe.upper()


def test_existing_limit_within_cap_is_kept():
    safe = validate_sql("SELECT customer_id FROM feature.gsm_transaction LIMIT 10", SETTINGS)
    assert "LIMIT 10" in safe.upper()


def test_existing_limit_over_cap_is_clamped():
    safe = validate_sql("SELECT customer_id FROM feature.gsm_transaction LIMIT 999999", SETTINGS)
    assert "LIMIT 100" in safe.upper()
    assert "999999" not in safe


def test_missing_limit_uses_default_not_safety_cap():
    settings = Settings(SQL_DEFAULT_ROWS=100, SQL_MAX_ROWS=1000)
    safe = validate_sql("SELECT customer_id FROM feature.gsm_transaction", settings)
    assert "LIMIT 100" in safe.upper()


# ---------------- Chặn ghi / DDL ----------------

@pytest.mark.parametrize("sql", [
    "UPDATE features SET x=1",
    "DELETE FROM features",
    "INSERT INTO features VALUES (1)",
    "DROP TABLE features",
    "ALTER TABLE features ADD COLUMN x int",
    "CREATE TABLE t (id int)",
    "TRUNCATE features",
    "GRANT SELECT ON features TO bob",
    "SELECT customer_id INTO backup FROM features",
    "PRAGMA table_info(features)",
])
def test_write_and_ddl_rejected(sql):
    assert not is_safe(sql, SETTINGS)
    with pytest.raises(GuardError):
        validate_sql(sql, SETTINGS)


# ---------------- Chặn nhiều câu lệnh / injection ----------------

def test_stacked_statements_rejected():
    with pytest.raises(GuardError):
        validate_sql("SELECT customer_id FROM features; DROP TABLE features", SETTINGS)


def test_comment_hidden_ddl_stripped_then_safe():
    # Comment bị strip -> phần thực thi vẫn chỉ là SELECT.
    safe = validate_sql("SELECT customer_id FROM feature.gsm_transaction /* DROP TABLE x */", SETTINGS)
    assert safe.upper().startswith("SELECT")


def test_comment_cannot_smuggle_execution():
    # '-- ; DELETE' là comment, không thực thi; nhưng nếu DELETE nằm NGOÀI comment thì chặn.
    with pytest.raises(GuardError):
        validate_sql("SELECT 1 FROM feature.gsm_transaction\nUNION SELECT 1 FROM feature.gsm_transaction; DELETE FROM feature.gsm_transaction", SETTINGS)


# ---------------- Chặn SELECT * và cột nhạy cảm ----------------

def test_select_star_rejected():
    with pytest.raises(GuardError):
        validate_sql("SELECT * FROM feature.gsm_transaction", SETTINGS)


def test_qualified_star_rejected():
    with pytest.raises(GuardError):
        validate_sql("SELECT f.* FROM feature.gsm_transaction f", SETTINGS)


@pytest.mark.parametrize("col", ["phone", "email", "national_id", "customer_name"])
def test_sensitive_columns_rejected(col):
    with pytest.raises(GuardError):
        validate_sql(f"SELECT {col} FROM feature.gsm_transaction", SETTINGS)


def test_empty_sql_rejected():
    with pytest.raises(GuardError):
        validate_sql("   ", SETTINGS)


def test_raw_schema_and_unqualified_table_rejected():
    with pytest.raises(GuardError):
        validate_sql("SELECT customer_id FROM raw.customers", SETTINGS)
    with pytest.raises(GuardError):
        validate_sql("SELECT customer_id FROM customers", SETTINGS)


def test_metadata_schema_allowed():
    assert is_safe("SELECT feature_name FROM metadata.feature_catalog", SETTINGS)


def test_catalog_join_with_all_keys_passes():
    safe = validate_sql(
        "SELECT g.customer_id, g.completed_txn_count_l1m "
        "FROM feature.gsm_transaction g INNER JOIN feature.vinfast_transaction v "
        "ON g.customer_id = v.customer_id AND g.snapshot_date = v.snapshot_date",
        SETTINGS, join_plan=JOIN_PLAN, join_rules=JOIN_RULES,
    )
    assert "INNER JOIN" in safe.upper()


@pytest.mark.parametrize("sql", [
    "SELECT g.customer_id FROM feature.gsm_transaction g "
    "JOIN feature.vinfast_transaction v ON g.customer_id = v.customer_id",
    "SELECT g.customer_id FROM feature.gsm_transaction g CROSS JOIN feature.vinfast_transaction v",
    "SELECT g.customer_id FROM feature.gsm_transaction g JOIN feature.vinfast_transaction v",
    "SELECT g.customer_id FROM feature.gsm_transaction g LEFT JOIN feature.vinfast_transaction v "
    "ON g.customer_id = v.customer_id AND g.snapshot_date = v.snapshot_date",
    "SELECT g.customer_id FROM feature.gsm_transaction g INNER JOIN feature.vinfast_transaction v "
    "ON g.customer_id = v.customer_id AND g.snapshot_date = v.snapshot_date AND g.completed_txn_count_l1m = v.txn_completed_count_l1m",
])
def test_runtime_join_policy_rejects_invalid_catalog_variants(sql):
    with pytest.raises(GuardError):
        validate_sql(sql, SETTINGS, join_plan=JOIN_PLAN, join_rules=JOIN_RULES)


def test_join_without_context_is_rejected():
    with pytest.raises(GuardError):
        validate_sql(
            "SELECT g.customer_id FROM feature.gsm_transaction g INNER JOIN feature.vinfast_transaction v "
            "ON g.customer_id = v.customer_id AND g.snapshot_date = v.snapshot_date", SETTINGS,
        )


@pytest.mark.parametrize("sql", [
    "SELECT g.customer_id FROM feature.gsm_transaction g INNER JOIN feature.vinfast_transaction v "
    "ON g.customer_id = v.customer_id AND g.snapshot_date = v.snapshot_date "
    "INNER JOIN feature.customer_cross_bu_feature c ON c.customer_id = g.customer_id",
    "SELECT customer_id FROM feature.gsm_transaction UNION SELECT customer_id FROM raw.customers",
    "SELECT customer_id FROM (SELECT customer_id FROM raw.customers) x",
    "WITH a AS (SELECT customer_id FROM feature.gsm_transaction), "
    "b AS (SELECT customer_id FROM feature.gsm_transaction), "
    "c AS (SELECT customer_id FROM feature.gsm_transaction) SELECT customer_id FROM a",
])
def test_join_adversarial_queries_are_rejected(sql):
    with pytest.raises(GuardError):
        validate_sql(sql, SETTINGS, join_plan=JOIN_PLAN, join_rules=JOIN_RULES)


@pytest.mark.parametrize("sql", [
    "SELECT version()",
    "SELECT pg_sleep(1) FROM metadata.feature_catalog",
    "SELECT pg_read_file('/etc/passwd') FROM metadata.feature_catalog",
])
def test_system_or_side_effect_functions_rejected(sql):
    with pytest.raises(GuardError):
        validate_sql(sql, SETTINGS)


def test_query_must_reference_approved_table():
    with pytest.raises(GuardError):
        validate_sql("SELECT 1", SETTINGS)
