"""AST-based SQL guards, independent from the LLM prompt."""
from __future__ import annotations

from typing import Any

from sqlglot import exp, parse
from sqlglot.errors import ParseError


class GuardError(ValueError):
    """SQL vi phạm chính sách an toàn — bị từ chối ở tầng thực thi."""


_FORBIDDEN_FUNCTIONS = {
    "pg_read_file", "pg_read_binary_file", "pg_ls_dir", "pg_stat_file",
    "pg_sleep", "pg_sleep_for", "pg_sleep_until", "dblink", "dblink_exec",
    "lo_import", "lo_export", "lo_unlink", "pg_notify",
}

ALLOWED_SCHEMAS = frozenset({"feature", "metadata"})
_FEATURE_TABLES = frozenset({"feature.gsm_transaction", "feature.vinfast_transaction"})


def _resolve_settings(settings: Any) -> tuple[list[str], int, int]:
    """Lấy (sensitive_columns, max_rows) từ settings; nạp mặc định nếu None."""
    if settings is None:
        from app.config import get_settings  # import trễ để tránh phụ thuộc pydantic khi test guard
        settings = get_settings()
    return settings.sensitive_columns, settings.sql_default_rows, settings.sql_max_rows


def _parse(sql: str) -> exp.Expression:
    try:
        statements = parse(sql, read="postgres")
    except ParseError as exc:
        raise GuardError(f"SQL không hợp lệ: {exc}") from exc
    if len(statements) != 1:
        raise GuardError("Chỉ cho phép một câu lệnh SQL.")
    statement = statements[0]
    if not isinstance(statement, (exp.Select, exp.SetOperation)):
        raise GuardError("Chỉ cho phép SELECT/WITH.")
    if any(statement.find(kind) for kind in (exp.Delete, exp.Insert, exp.Update, exp.Create, exp.Drop, exp.Alter, exp.Merge)):
        raise GuardError("Chỉ cho phép truy vấn đọc.")
    return statement


def _function_names(statement: exp.Expression) -> set[str]:
    names: set[str] = set()
    for node in statement.find_all(exp.Func):
        names.update(str(name).lower() for name in (node.sql_name(), node.name) if name)
    return names


def _check_forbidden(statement: exp.Expression) -> None:
    forbidden = _FORBIDDEN_FUNCTIONS & _function_names(statement)
    if forbidden:
        raise GuardError(f"Function bị cấm: {sorted(forbidden)[0]}.")


def _is_select_star(projection: exp.Expression) -> bool:
    return isinstance(projection, exp.Star) or (
        isinstance(projection, exp.Column) and isinstance(projection.this, exp.Star)
    )


def _check_star(statement: exp.Expression) -> None:
    if any(_is_select_star(p) for select in statement.find_all(exp.Select) for p in select.expressions):
        raise GuardError("Không cho phép 'SELECT *'. Hãy liệt kê cột cụ thể.")


def _check_sensitive_columns(statement: exp.Expression, sensitive: list[str]) -> None:
    blocked = {column.name.lower() for column in statement.find_all(exp.Column)} & set(sensitive)
    if blocked:
        raise GuardError(f"Cột nhạy cảm bị chặn: '{sorted(blocked)[0]}'.")


def _table_names(statement: exp.Expression) -> list[str]:
    return [
        f"{table.db}.{table.name}".lower() if table.db else table.name.lower()
        for table in statement.find_all(exp.Table)
    ]


def referenced_tables(sql: str) -> list[str]:
    try:
        return _table_names(_parse(sql))
    except GuardError:
        return []


def has_select_star(sql: str) -> bool:
    try:
        statement = _parse(sql)
    except GuardError:
        return False
    return any(_is_select_star(p) for select in statement.find_all(exp.Select) for p in select.expressions)


def _check_table_allowlist(statement: exp.Expression) -> None:
    ctes = {cte.alias_or_name.lower() for cte in statement.find_all(exp.CTE)}
    tables = _table_names(statement)
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
    if len(_FEATURE_TABLES & set(tables)) > 1:
        raise GuardError("Không cho phép join GSM và VinFast trong Sprint 1.")


def _enforce_row_limit(statement: exp.Expression, default_rows: int, max_rows: int) -> str:
    limit = statement.args.get("limit")
    current = limit.expression.to_py() if limit and isinstance(limit.expression, exp.Literal) else None
    rows = min(int(current), max_rows) if isinstance(current, int) else min(default_rows, max_rows)
    return statement.limit(rows, copy=True).sql(dialect="postgres")


def validate_sql(sql: str, settings: Any = None) -> str:
    """Kiểm tra & làm sạch SQL. Trả về SQL an toàn hoặc raise GuardError.

    Thứ tự: strip comment → 1 câu lệnh → SELECT/WITH → chặn từ khóa cấm →
    chặn '*' → chặn cột nhạy cảm → áp row-limit.
    """
    sensitive, default_rows, max_rows = _resolve_settings(settings)
    if not sql or not sql.strip():
        raise GuardError("SQL rỗng.")

    statement = _parse(sql)
    _check_forbidden(statement)
    _check_star(statement)
    _check_sensitive_columns(statement, sensitive)
    _check_table_allowlist(statement)
    return _enforce_row_limit(statement, default_rows, max_rows)


def is_safe(sql: str, settings: Any = None) -> bool:
    """Tiện ích boolean cho test/UX — không raise."""
    try:
        validate_sql(sql, settings)
        return True
    except GuardError:
        return False
