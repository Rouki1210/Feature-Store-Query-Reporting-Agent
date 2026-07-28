"""AST-based SQL guards, independent from the LLM prompt."""
from __future__ import annotations

from typing import Any, Iterable

from sqlglot import exp, parse
from sqlglot.errors import ParseError


class GuardError(ValueError):
    """SQL violates the read-only policy."""


_FORBIDDEN_FUNCTIONS = {
    "pg_read_file", "pg_read_binary_file", "pg_ls_dir", "pg_stat_file",
    "pg_sleep", "pg_sleep_for", "pg_sleep_until", "dblink", "dblink_exec",
    "lo_import", "lo_export", "lo_unlink", "pg_notify",
}

ALLOWED_SCHEMAS = frozenset({"feature", "metadata"})
_FEATURE_TABLES = frozenset({
    "feature.gsm_transaction", "feature.vinfast_transaction", "feature.customer_cross_bu_feature",
})


def _resolve_settings(settings: Any) -> tuple[list[str], int, int, int, int]:
    if settings is None:
        from app.config import get_settings
        settings = get_settings()
    return (
        settings.sensitive_columns, settings.sql_default_rows, settings.sql_max_rows,
        settings.sql_max_joins, settings.sql_max_ctes,
    )


def _parse(sql: str) -> exp.Expression:
    try:
        statements = parse(sql, read="postgres")
    except ParseError as exc:
        raise GuardError(f"Invalid SQL: {exc}") from exc
    if len(statements) != 1:
        raise GuardError("Only one SQL statement is allowed.")
    statement = statements[0]
    if not isinstance(statement, (exp.Select, exp.SetOperation)):
        raise GuardError("Only SELECT/WITH is allowed.")
    if any(statement.find(kind) for kind in (exp.Delete, exp.Insert, exp.Update, exp.Create, exp.Drop, exp.Alter, exp.Merge)):
        raise GuardError("Only read queries are allowed.")
    return statement


def _function_names(statement: exp.Expression) -> set[str]:
    names: set[str] = set()
    for node in statement.find_all(exp.Func):
        names.update(str(name).lower() for name in (node.sql_name(), node.name) if name)
    return names


def _check_forbidden(statement: exp.Expression) -> None:
    forbidden = _FORBIDDEN_FUNCTIONS & _function_names(statement)
    if forbidden:
        raise GuardError(f"Forbidden function: {sorted(forbidden)[0]}.")


def _is_select_star(projection: exp.Expression) -> bool:
    return isinstance(projection, exp.Star) or (
        isinstance(projection, exp.Column) and isinstance(projection.this, exp.Star)
    )


def _check_star(statement: exp.Expression) -> None:
    if any(_is_select_star(p) for select in statement.find_all(exp.Select) for p in select.expressions):
        raise GuardError("SELECT * is not allowed.")


def _check_sensitive_columns(statement: exp.Expression, sensitive: list[str]) -> None:
    blocked = {column.name.lower() for column in statement.find_all(exp.Column)} & set(sensitive)
    if blocked:
        raise GuardError(f"Sensitive column blocked: '{sorted(blocked)[0]}'.")


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
        raise GuardError("Query must reference a feature or metadata table.")
    for table in tables:
        if "." not in table:
            if table in ctes:
                continue
            raise GuardError(f"Table '{table}' must be schema-qualified.")
        if table.split(".", 1)[0] not in ALLOWED_SCHEMAS:
            raise GuardError(f"Schema '{table.split('.', 1)[0]}' is not allowed.")


def _physical_table(node: exp.Expression) -> tuple[str, str] | None:
    if not isinstance(node, exp.Table) or not node.db:
        return None
    return f"{node.db}.{node.name}".lower(), node.alias_or_name.lower()


def _and_terms(node: exp.Expression) -> list[exp.Expression]:
    if isinstance(node, exp.And):
        return _and_terms(node.left) + _and_terms(node.right)
    return [node]


def _check_join_policy(
    statement: exp.Expression,
    max_joins: int,
    max_ctes: int,
    join_plan: dict[str, Any] | None,
    join_rules: Iterable[Any],
) -> None:
    joins = list(statement.find_all(exp.Join))
    if len(joins) > max_joins:
        raise GuardError(f"Exceeded SQL_MAX_JOINS={max_joins}.")
    if sum(1 for _ in statement.find_all(exp.CTE)) > max_ctes:
        raise GuardError(f"Exceeded SQL_MAX_CTES={max_ctes}.")
    if not joins:
        return
    if not join_plan:
        raise GuardError("JOIN requires a catalog-backed join_plan.")

    plan_tables = frozenset(str(table).lower() for table in join_plan.get("tables", []))
    plan_keys = frozenset(str(key).lower() for key in join_plan.get("join_keys", []))
    plan_type = str(join_plan.get("join_type") or "").lower()
    rules = tuple(join_rules)
    for select in statement.find_all(exp.Select):
        source = select.args.get("from_")
        left = _physical_table(source.this) if source else None
        for join in select.args.get("joins") or []:
            right = _physical_table(join.this)
            if left is None or right is None:
                raise GuardError("Runtime JOIN must use two schema-qualified physical tables, not CTEs/subqueries.")
            if join.args.get("method") == "NATURAL" or join.args.get("kind") == "CROSS":
                raise GuardError("NATURAL JOIN and CROSS JOIN are not allowed.")
            on = join.args.get("on")
            if on is None:
                raise GuardError("JOIN requires an ON clause.")

            pair = frozenset({left[0], right[0]})
            rule = next((item for item in rules if item.pair == pair), None)
            if rule is None or pair != plan_tables:
                raise GuardError("JOIN pair is not approved by join_catalog and join_plan.")
            actual_type = str(join.args.get("side") or join.args.get("kind") or "inner").lower()
            if actual_type != rule.join_type.lower() or actual_type != plan_type:
                raise GuardError("JOIN type does not match join_catalog.")
            required_keys = frozenset(key.lower() for key in rule.join_keys)
            if required_keys != plan_keys:
                raise GuardError("join_plan keys do not match join_catalog.")

            aliases = {left[1]: left[0], right[1]: right[0]}
            seen_keys: set[str] = set()
            for term in _and_terms(on):
                if not isinstance(term, exp.EQ) or not isinstance(term.left, exp.Column) or not isinstance(term.right, exp.Column):
                    raise GuardError("JOIN ON may contain only equality checks for catalog keys.")
                first, second = term.left, term.right
                key = first.name.lower()
                if (
                    key != second.name.lower() or key not in required_keys
                    or aliases.get(first.table.lower()) == aliases.get(second.table.lower())
                    or {aliases.get(first.table.lower()), aliases.get(second.table.lower())} != pair
                ):
                    raise GuardError("JOIN uses a key not approved by join_catalog.")
                seen_keys.add(key)
            if seen_keys != required_keys:
                raise GuardError("JOIN is missing a required join_catalog key.")
            # The next join would need its own direct left table and catalog rule.
            left = None


def _enforce_row_limit(statement: exp.Expression, default_rows: int, max_rows: int) -> str:
    limit = statement.args.get("limit")
    current = limit.expression.to_py() if limit and isinstance(limit.expression, exp.Literal) else None
    rows = min(int(current), max_rows) if isinstance(current, int) else min(default_rows, max_rows)
    return statement.limit(rows, copy=True).sql(dialect="postgres")


def validate_sql(
    sql: str,
    settings: Any = None,
    *,
    join_plan: dict[str, Any] | None = None,
    join_rules: Iterable[Any] = (),
) -> str:
    """Return safe SQL or raise GuardError before the query reaches PostgreSQL."""
    sensitive, default_rows, max_rows, max_joins, max_ctes = _resolve_settings(settings)
    if not sql or not sql.strip():
        raise GuardError("SQL is empty.")
    statement = _parse(sql)
    _check_forbidden(statement)
    _check_star(statement)
    _check_sensitive_columns(statement, sensitive)
    _check_table_allowlist(statement)
    _check_join_policy(statement, max_joins, max_ctes, join_plan, join_rules)
    return _enforce_row_limit(statement, default_rows, max_rows)


def is_safe(sql: str, settings: Any = None, **kwargs: Any) -> bool:
    try:
        validate_sql(sql, settings, **kwargs)
        return True
    except GuardError:
        return False
