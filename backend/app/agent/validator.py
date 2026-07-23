from __future__ import annotations

import re

from app.agent.contracts import GenerationResponse, ValidationResult
from app.semantic.feature_spec import feature_names
from app.sql.guards import GuardError, referenced_tables, validate_sql


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


class PipelineValidator:
    def validate(
        self,
        generation: GenerationResponse,
        allowed_features: set[str],
        settings=None,
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
            safe_sql = validate_sql(generation.sql, settings)
        except GuardError as exc:
            errors.append(str(exc))
            return ValidationResult(
                valid=False,
                errors=errors,
                selected_features=generation.selected_features,
            )

        tables = referenced_tables(safe_sql)
        legacy_used = sorted(
            name
            for name in LEGACY_FEATURE_COLUMNS
            if re.search(rf"\b{re.escape(name)}\b", safe_sql, re.IGNORECASE)
        )
        if legacy_used:
            errors.append(
                "Legacy physical columns are not queryable: " + ", ".join(legacy_used)
            )
        for feature in generation.selected_features:
            if not re.search(rf"\b{re.escape(feature)}\b", safe_sql, re.IGNORECASE):
                errors.append(f"SQL does not use selected feature: {feature}")
        return ValidationResult(
            valid=not errors,
            sql=safe_sql if not errors else None,
            errors=errors,
            referenced_tables=tables,
            selected_features=generation.selected_features,
        )
