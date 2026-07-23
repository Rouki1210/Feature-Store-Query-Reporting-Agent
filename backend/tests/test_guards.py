"""Test SQL guards — chạy TRƯỚC khi bất cứ thứ gì gọi LLM (CLAUDE.md mục 6 bước 3).

    cd backend && python -m pytest tests/test_guards.py -v
"""
from __future__ import annotations

import pytest

from app.config import Settings
from app.sql.guards import GuardError, is_safe, validate_sql

# Settings cố định cho test (không phụ thuộc .env).
SETTINGS = Settings(
    SQL_MAX_ROWS=100,
    SQL_SENSITIVE_COLUMNS="phone,email,national_id,customer_name",
)


# ---------------- Truy vấn hợp lệ ----------------

def test_select_passes_and_gets_limit():
    safe = validate_sql("SELECT customer_id FROM features", SETTINGS)
    assert safe.upper().startswith("SELECT")
    assert "LIMIT 100" in safe.upper()


def test_with_cte_passes():
    sql = "WITH t AS (SELECT customer_id FROM features) SELECT customer_id FROM t"
    assert is_safe(sql, SETTINGS)


def test_count_star_is_allowed():
    # COUNT(*) hợp lệ; chỉ 'SELECT *' mới bị chặn.
    safe = validate_sql("SELECT COUNT(*) AS n FROM features", SETTINGS)
    assert "COUNT(*)" in safe.upper()


def test_existing_limit_within_cap_is_kept():
    safe = validate_sql("SELECT customer_id FROM features LIMIT 10", SETTINGS)
    assert "LIMIT 10" in safe.upper()


def test_existing_limit_over_cap_is_clamped():
    safe = validate_sql("SELECT customer_id FROM features LIMIT 999999", SETTINGS)
    assert "LIMIT 100" in safe.upper()
    assert "999999" not in safe


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
    safe = validate_sql("SELECT customer_id FROM features /* DROP TABLE x */", SETTINGS)
    assert safe.upper().startswith("SELECT")


def test_comment_cannot_smuggle_execution():
    # '-- ; DELETE' là comment, không thực thi; nhưng nếu DELETE nằm NGOÀI comment thì chặn.
    with pytest.raises(GuardError):
        validate_sql("SELECT 1 FROM features\nUNION SELECT 1 FROM features; DELETE FROM features", SETTINGS)


# ---------------- Chặn SELECT * và cột nhạy cảm ----------------

def test_select_star_rejected():
    with pytest.raises(GuardError):
        validate_sql("SELECT * FROM features", SETTINGS)


def test_qualified_star_rejected():
    with pytest.raises(GuardError):
        validate_sql("SELECT f.* FROM features f", SETTINGS)


@pytest.mark.parametrize("col", ["phone", "email", "national_id", "customer_name"])
def test_sensitive_columns_rejected(col):
    with pytest.raises(GuardError):
        validate_sql(f"SELECT {col} FROM customers", SETTINGS)


def test_empty_sql_rejected():
    with pytest.raises(GuardError):
        validate_sql("   ", SETTINGS)
