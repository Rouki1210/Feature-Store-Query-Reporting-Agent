"""SQL guards — enforce DƯỚI prompt (CLAUDE.md mục 5, KHÔNG thương lượng).

Chỉ `SELECT`/`WITH` được qua. Mọi truy vấn bị áp row-limit cứng. `SELECT *` và
cột nhạy cảm bị chặn ở tầng THỰC THI — loại trừ ở prompt là cần nhưng chưa đủ.

Đây là tầng phòng thủ độc lập với LLM: kể cả prompt bị lái sai, guard vẫn chặn.
Vì vậy guard được test kỹ (tests/test_guards.py) và đứng trước mọi lời gọi LLM.

Ghi chú kỹ thuật: module này chỉ phụ thuộc stdlib. `sqlparse` là TÙY CHỌN — nếu có
thì dùng để strip comment chuẩn hơn; nếu không có, fallback regex vẫn an toàn.
"""
from __future__ import annotations

import re
from typing import Any

try:  # sqlparse tùy chọn — có thì strip comment chuẩn hơn.
    import sqlparse  # type: ignore
except Exception:  # pragma: no cover
    sqlparse = None  # type: ignore


class GuardError(ValueError):
    """SQL vi phạm chính sách an toàn — bị từ chối ở tầng thực thi."""


# Từ khóa cấm (DML/DDL/lệnh nguy hiểm) — bất kỳ đâu trong câu lệnh.
_FORBIDDEN = {
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "TRUNCATE",
    "REPLACE", "MERGE", "GRANT", "REVOKE", "ATTACH", "DETACH", "PRAGMA",
    "VACUUM", "EXEC", "EXECUTE", "CALL", "COPY", "INTO", "REINDEX", "ANALYZE",
    "COMMIT", "ROLLBACK", "SAVEPOINT", "SET", "LOAD",
}
_FORBIDDEN_FUNCTIONS = {
    "pg_read_file", "pg_read_binary_file", "pg_ls_dir", "pg_stat_file",
    "pg_sleep", "pg_sleep_for", "pg_sleep_until", "dblink", "dblink_exec",
    "lo_import", "lo_export", "lo_unlink", "pg_notify",
}

_SELECT_STAR = re.compile(r"select\s+(distinct\s+)?\*", re.IGNORECASE)
_QUALIFIED_STAR = re.compile(r"[\w`\"\]]\s*\.\s*\*", re.IGNORECASE)  # t.*  "t".*
_LIMIT_RE = re.compile(r"\blimit\s+(\d+)\b", re.IGNORECASE)
_LINE_COMMENT = re.compile(r"--[^\n]*")
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_TABLE_REF = re.compile(
    r'\b(?:from|join)\s+((?:"?[A-Za-z_]\w*"?\.)?"?[A-Za-z_]\w*"?)',
    re.IGNORECASE,
)
_CTE_NAME = re.compile(r'(?:\bwith|,)\s*"?([A-Za-z_]\w*)"?\s+as\s*\(', re.IGNORECASE)
ALLOWED_SCHEMAS = frozenset({"feature", "metadata"})


def _resolve_settings(settings: Any) -> tuple[list[str], int]:
    """Lấy (sensitive_columns, max_rows) từ settings; nạp mặc định nếu None."""
    if settings is None:
        from app.config import get_settings  # import trễ để tránh phụ thuộc pydantic khi test guard
        settings = get_settings()
    return settings.sensitive_columns, settings.sql_max_rows


def _strip_comments(sql: str) -> str:
    """Bỏ comment để phân tích trên phần thực thi thật (tránh né guard)."""
    if sqlparse is not None:
        return sqlparse.format(sql, strip_comments=True).strip()
    # Fallback regex: bỏ block comment rồi line comment.
    out = _BLOCK_COMMENT.sub(" ", sql)
    out = _LINE_COMMENT.sub("", out)
    return out.strip()


def _single_statement(sql: str) -> str:
    """Bảo đảm đúng MỘT câu lệnh; chặn stacking bằng dấu `;`."""
    body = sql.rstrip().rstrip(";").strip()
    if not body:
        raise GuardError("SQL rỗng.")
    if ";" in body:
        raise GuardError("Không cho phép nhiều câu lệnh (phát hiện dấu ';').")
    return body


def _first_keyword(sql: str) -> str:
    # `sql` đã được strip comment trước khi gọi. Bỏ '(' dẫn đầu (subquery bọc ngoài).
    s = sql.lstrip().lstrip("(").lstrip()
    match = re.match(r"([A-Za-z_]+)", s)
    return match.group(1).upper() if match else ""


def _check_forbidden(sql: str) -> None:
    upper = sql.upper()
    for kw in _FORBIDDEN:
        if re.search(rf"\b{kw}\b", upper):
            raise GuardError(f"Từ khóa bị cấm: {kw}. Chỉ cho phép truy vấn đọc.")
    for fn in _FORBIDDEN_FUNCTIONS:
        if re.search(rf"\b{re.escape(fn)}\s*\(", sql, re.IGNORECASE):
            raise GuardError(f"Function bị cấm: {fn}.")


def _check_star(sql: str) -> None:
    # Cho phép aggregate như COUNT(*), nhưng chặn SELECT * / t.* (select-all).
    if _SELECT_STAR.search(sql) or _QUALIFIED_STAR.search(sql):
        raise GuardError("Không cho phép 'SELECT *'. Hãy liệt kê cột cụ thể.")


def _check_sensitive_columns(sql: str, sensitive: list[str]) -> None:
    low = sql.lower()
    for col in sensitive:
        if re.search(rf"\b{re.escape(col)}\b", low):
            raise GuardError(
                f"Cột nhạy cảm bị chặn: '{col}'. Không được truy vấn cột này."
            )


def referenced_tables(sql: str) -> list[str]:
    return [m.group(1).replace('"', "").lower() for m in _TABLE_REF.finditer(sql)]


def has_select_star(sql: str) -> bool:
    """SELECT * / t.* thật (không tính COUNT(*)). Dùng cho audit log."""
    return bool(_SELECT_STAR.search(sql) or _QUALIFIED_STAR.search(sql))


def _check_table_allowlist(sql: str) -> None:
    ctes = {m.group(1).lower() for m in _CTE_NAME.finditer(sql)}
    tables = referenced_tables(sql)
    if not tables:
        raise GuardError("Truy vấn phải tham chiếu ít nhất một bảng feature hoặc metadata.")
    for table in tables:
        if "." not in table:
            if table in ctes:
                continue
            raise GuardError(
                f"Bảng '{table}' phải có schema và chỉ được thuộc feature hoặc metadata."
            )
        schema = table.split(".", 1)[0]
        if schema not in ALLOWED_SCHEMAS:
            raise GuardError(
                f"Schema '{schema}' không được phép. Chỉ cho phép feature và metadata."
            )


def _enforce_row_limit(sql: str, max_rows: int) -> str:
    """Áp row-limit cứng: thêm LIMIT nếu thiếu, kẹp nếu vượt."""
    match = _LIMIT_RE.search(sql)
    if match is None:
        return f"{sql} LIMIT {max_rows}"
    current = int(match.group(1))
    if current > max_rows:
        start, end = match.span(1)
        return sql[:start] + str(max_rows) + sql[end:]
    return sql


def validate_sql(sql: str, settings: Any = None) -> str:
    """Kiểm tra & làm sạch SQL. Trả về SQL an toàn hoặc raise GuardError.

    Thứ tự: strip comment → 1 câu lệnh → SELECT/WITH → chặn từ khóa cấm →
    chặn '*' → chặn cột nhạy cảm → áp row-limit.
    """
    sensitive, max_rows = _resolve_settings(settings)
    if not sql or not sql.strip():
        raise GuardError("SQL rỗng.")

    body = _strip_comments(sql)
    body = _single_statement(body)

    first = _first_keyword(body)
    if first not in ("SELECT", "WITH"):
        raise GuardError(f"Chỉ cho phép SELECT/WITH, nhận được: {first or '(rỗng)'}.")

    _check_forbidden(body)
    _check_star(body)
    _check_sensitive_columns(body, sensitive)
    _check_table_allowlist(body)

    return _enforce_row_limit(body, max_rows)


def is_safe(sql: str, settings: Any = None) -> bool:
    """Tiện ích boolean cho test/UX — không raise."""
    try:
        validate_sql(sql, settings)
        return True
    except GuardError:
        return False
