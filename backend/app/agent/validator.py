from __future__ import annotations

import re
from typing import Any, Iterable

from app.agent.contracts import BreakdownPlan, GenerationResponse, ValidationResult
from app.semantic.feature_spec import feature_names
from app.sql.guards import GuardError, referenced_tables, validate_sql
from sqlglot import exp, parse_one


CANONICAL_FEATURES = frozenset(feature_names())

# Migration 0002 keeps these physical columns for backward compatibility.
# They are not part of the retained Sprint 1 query inventory.
LEGACY_FEATURE_COLUMNS = frozenset({
    "completed_txn_amount_l1m", "completed_txn_amount_l3m", "completed_txn_amount_l12m",
    "completed_distance_l1m", "completed_duration_l1m", "avg_ticket_l1m",
    "avg_distance_l1m", "completed_rate_l1m", "taxi_completed_count_l1m",
    "bike_completed_count_l1m", "express_completed_count_l1m", "food_completed_count_l1m",
    "txn_count_l1m_vs_l3m", "txn_amount_l1m_vs_l3m", "txn_count_l3m_vs_l12m",
    "first_trip_date", "last_trip_date", "active_days_l1m", "days_since_last_trip",
    "is_active_l1m", "order_created_count_daily", "order_created_count_l1m",
    "order_created_count_l3m", "order_created_count_l12m", "completed_order_count_l1m",
    "completed_order_count_l3m", "completed_order_count_l12m", "vehicle_order_count_l1m",
    "vehicle_completed_order_count_l1m", "accessories_order_count_l1m",
    "work_order_count_l1m", "nvso_order_count_l1m", "order_amount_l1m",
    "order_amount_l3m", "order_amount_l12m", "vehicle_amount_l1m",
    "accessories_amount_l1m", "discount_order_count_l1m", "discount_amount_l1m",
    "avg_order_value_l1m", "avg_vehicle_order_value_l1m", "battery_kwh_sum_l1m",
    "order_count_l1m_vs_l3m", "amount_l1m_vs_l3m", "order_count_l3m_vs_l12m",
    "first_order_date", "last_order_date", "first_vehicle_purchase_date",
    "days_since_last_order", "is_vinfast_buyer",
}) - CANONICAL_FEATURES

_PROJECTED_SNAPSHOT_DATE = re.compile(
    r"\bselect\s+(?:distinct\s+)?(?:[a-z_]\w*\.)?customer_id\s*,\s*"
    r"(?:[a-z_]\w*\.)?snapshot_date\b",
    re.IGNORECASE,
)
_PROJECTED_CUSTOMER_ID = re.compile(
    r"\bselect\s+(?:distinct\s+)?(?:[a-z_]\w*\.)?customer_id\b",
    re.IGNORECASE,
)


_ORDINAL = "breakdown_ordinal"


def _union_branches(statement: exp.Expression) -> list[exp.Select]:
    if isinstance(statement, exp.Union):
        return _union_branches(statement.this) + _union_branches(statement.expression)
    if isinstance(statement, exp.Select):
        # `compile_breakdown` bọc UNION trong subquery để `ORDER BY breakdown_ordinal`
        # cho thứ tự dòng xác định — các nhánh thật nằm bên trong.
        source = statement.args.get("from_") or statement.args.get("from")
        inner = source.this if source else None
        if isinstance(inner, exp.Subquery):
            return _union_branches(inner.this)
        return [statement]
    return list(statement.find_all(exp.Select))


def _branch_columns(branch: exp.Select) -> list[str]:
    """Bỏ cột ordinal ẩn — nó không thuộc kết quả người dùng thấy."""
    columns = [projection.alias_or_name for projection in branch.expressions]
    return columns[1:] if columns[:1] == [_ORDINAL] else columns


def _branch_projections(branch: exp.Select) -> list[exp.Expression]:
    projections = list(branch.expressions)
    has_ordinal = bool(projections) and projections[0].alias_or_name == _ORDINAL
    return projections[1:] if has_ordinal else projections


def _validate_breakdown_sql(sql: str, plan: BreakdownPlan) -> list[str]:
    errors: list[str] = []
    try:
        statement = parse_one(sql, read="postgres")
    except Exception as exc:
        return [f"Breakdown SQL không parse được: {exc}"]
    branches = _union_branches(statement)
    if plan.strategy in {"pivot_feature", "boolean_segment"}:
        if len(branches) != len(plan.branches):
            errors.append(
                f"Breakdown cần {len(plan.branches)} nhánh nhưng SQL có {len(branches)}."
            )
        for branch in branches:
            columns = _branch_columns(branch)
            if columns != plan.expected_columns:
                errors.append(
                    "Breakdown output columns không khớp plan: "
                    f"{columns} != {plan.expected_columns}."
                )
        if len(branches) == len(plan.branches):
            expected_labels = [
                tuple(branch["labels"].get(dimension) for dimension in plan.dimensions)
                for branch in plan.branches
            ]
            actual_labels: list[tuple[str, ...]] = []
            for branch in branches:
                labels: list[str] = []
                for projection in _branch_projections(branch)[: len(plan.dimensions)]:
                    literal = projection.this if isinstance(projection, exp.Alias) else projection
                    labels.append(str(literal.this) if isinstance(literal, exp.Literal) else "")
                actual_labels.append(tuple(labels))
            if actual_labels != expected_labels:
                errors.append("Breakdown member labels hoặc thứ tự nhánh không khớp plan.")
    elif plan.strategy == "physical_column":
        if not branches:
            errors.append("Physical breakdown phải có SELECT.")
        for branch in branches:
            columns = _branch_columns(branch)
            if columns != plan.expected_columns:
                errors.append(
                    "Physical breakdown output columns không khớp plan: "
                    f"{columns} != {plan.expected_columns}."
                )
            grouped = {
                column.name.lower()
                for column in branch.args.get("group").find_all(exp.Column)
            } if branch.args.get("group") else set()
            if "snapshot_date" not in grouped:
                errors.append("Physical breakdown phải GROUP BY snapshot_date.")
    return errors


class PipelineValidator:
    def validate(
        self,
        generation: GenerationResponse,
        allowed_features: set[str],
        settings=None,
        *,
        join_plan: dict[str, Any] | None = None,
        join_rules: Iterable[Any] = (),
        breakdown_plan: BreakdownPlan | None = None,
    ) -> ValidationResult:
        errors: list[str] = []
        unknown = sorted(set(generation.selected_features) - allowed_features)
        if unknown:
            errors.append(f"Feature outside retrieved context: {', '.join(unknown)}")
        noncanonical = sorted(set(generation.selected_features) - CANONICAL_FEATURES)
        if noncanonical:
            errors.append(
                f"Feature outside canonical Sprint 1 inventory: {', '.join(noncanonical)}"
            )
        try:
            safe_sql = validate_sql(
                generation.sql, settings, join_plan=join_plan, join_rules=join_rules,
            )
        except GuardError as exc:
            errors.append(str(exc))
            return ValidationResult(
                valid=False,
                errors=errors,
                selected_features=generation.selected_features,
            )

        tables = referenced_tables(safe_sql)
        if _PROJECTED_SNAPSHOT_DATE.search(safe_sql) and not (
            breakdown_plan and "snapshot_date" in breakdown_plan.dimensions
        ):
            errors.append("snapshot_date is for filtering only; do not project it unless requested.")
        if _PROJECTED_CUSTOMER_ID.search(safe_sql) and not re.search(r"\border\s+by\b", safe_sql, re.IGNORECASE):
            errors.append("Per-customer lists must use ORDER BY customer_id unless ranked explicitly.")
        legacy_used = sorted(
            name
            for name in LEGACY_FEATURE_COLUMNS
            if re.search(rf"\b{re.escape(name)}\b", safe_sql, re.IGNORECASE)
        )
        if legacy_used:
            errors.append(
                "Legacy physical columns are not queryable: " + ", ".join(legacy_used)
            )
        referenced_features = {
            feature
            for feature in CANONICAL_FEATURES
            if re.search(rf"\b{re.escape(feature)}\b", safe_sql, re.IGNORECASE)
        }
        unselected = sorted(referenced_features - set(generation.selected_features))
        if unselected:
            errors.append("SQL uses unselected features: " + ", ".join(unselected))
        for feature in generation.selected_features:
            if not re.search(rf"\b{re.escape(feature)}\b", safe_sql, re.IGNORECASE):
                errors.append(f"SQL does not use selected feature: {feature}")
        if breakdown_plan:
            errors.extend(_validate_breakdown_sql(safe_sql, breakdown_plan))
        return ValidationResult(
            valid=not errors,
            sql=safe_sql if not errors else None,
            errors=errors,
            referenced_tables=tables,
            selected_features=generation.selected_features,
        )
