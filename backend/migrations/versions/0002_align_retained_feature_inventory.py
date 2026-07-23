"""Align feature tables with the retained Sprint 1 inventory.

The workbook inventory uses table-prefixed feature names
(`gsm_transaction_<feature>` / `vinfast_transaction_<feature>`), while the
physical PostgreSQL columns remain unprefixed.  This migration adds the
missing retained columns and deliberately keeps legacy columns in place so
existing snapshots are not destroyed.  Legacy columns must be excluded from
the metadata/query allowlist until they are explicitly retired.
"""
from __future__ import annotations

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


_WINDOWS = {
    "daily",
    "l1w",
    "l2w",
    "l4w",
    "l1m",
    "l2m",
    "l3m",
    "l6m",
    "l12m",
    "l1m_vs_l3m",
    "l1m_vs_l6m",
    "l1m_vs_l12m",
    "l3m_vs_l12m",
}


def _expand(stems: dict[str, tuple[str, ...]]) -> tuple[str, ...]:
    return tuple(f"{stem}_{window}" for stem, windows in stems.items() for window in windows)


_GSM_FEATURES = _expand(
    {
        "canceled_original_price_max": ("daily", "l1w", "l2w", "l1m", "l3m", "l6m", "l12m"),
        "canceled_original_price_sum": ("daily", "l1w", "l2w", "l1m", "l3m", "l6m", "l12m"),
        "canceled_txn_active_day_count": ("daily", "l1w", "l2w", "l1m", "l3m", "l6m", "l12m"),
        "canceled_txn_count": ("daily", "l1w", "l2w", "l1m", "l3m", "l6m", "l12m"),
        "canceled_weekday_original_price_sum": ("l1w", "l2w", "l1m", "l3m", "l6m", "l12m"),
        "canceled_weekday_txn_count": ("l1w", "l2w", "l1m", "l3m", "l6m", "l12m"),
        "completed_discount_amount_sum": ("daily", "l1w", "l2w", "l1m", "l3m", "l6m", "l12m"),
        "completed_original_price_max": ("daily", "l1w", "l2w", "l1m", "l3m", "l6m", "l12m"),
        "completed_original_price_sum": (
            "daily", "l1w", "l2w", "l1m", "l3m", "l6m", "l12m",
            "l1m_vs_l3m", "l1m_vs_l6m", "l3m_vs_l12m",
        ),
        "completed_trip_distance_km_sum": (
            "daily", "l1w", "l2w", "l1m", "l3m", "l6m", "l12m",
            "l1m_vs_l3m", "l1m_vs_l6m", "l3m_vs_l12m",
        ),
        "completed_txn_active_day_count": ("daily", "l1w", "l2w", "l1m", "l3m", "l6m", "l12m"),
        "completed_txn_count": ("daily", "l1w", "l2w", "l1m", "l3m", "l6m", "l12m"),
        "completed_weekday_original_price_sum": ("l1w", "l2w", "l1m", "l3m", "l6m", "l12m"),
        "completed_weekday_txn_count": ("l1w", "l2w", "l1m", "l3m", "l6m", "l12m"),
        "days_since_first_txn": ("l12m",),
        "days_since_last_txn": ("l12m",),
        "finished_original_price_max": ("daily", "l1w", "l2w", "l1m", "l3m", "l6m", "l12m"),
        "finished_original_price_sum": ("daily", "l1w", "l2w", "l1m", "l3m", "l6m", "l12m"),
        "finished_time_daytime_original_price_sum": (
            "daily", "l1w", "l2w", "l1m", "l3m", "l6m", "l12m"
        ),
        "finished_time_daytime_txn_count": (
            "daily", "l1w", "l2w", "l1m", "l3m", "l6m", "l12m"
        ),
        "finished_txn_active_day_count": ("daily", "l1w", "l2w", "l1m", "l3m", "l6m", "l12m"),
        "finished_txn_count": (
            "daily", "l1w", "l2w", "l1m", "l3m", "l6m", "l12m",
            "l1m_vs_l3m", "l1m_vs_l6m", "l3m_vs_l12m",
        ),
        "finished_type_bike_txn_count": ("l1w", "l2w"),
        "finished_type_express_txn_count": ("l1w", "l2w"),
        "finished_type_food_txn_count": ("l1w", "l2w"),
        "finished_type_taxi_txn_count": ("l1w", "l2w"),
        "finished_weekday_original_price_sum": ("l1w", "l2w", "l1m", "l3m", "l6m", "l12m"),
        "finished_weekday_txn_count": ("l1w", "l2w", "l1m", "l3m", "l6m", "l12m"),
    }
)

_VINFAST_FEATURES = _expand(
    {
        "days_since_first_completed_txn_days": ("daily", "l1w", "l2w", "l1m", "l3m", "l6m", "l12m"),
        "days_since_last_completed_txn_days": ("daily", "l1w", "l2w", "l1m", "l3m", "l6m", "l12m"),
        "txn_accessories_canceled_amount_sum": ("l1m_vs_l3m", "l1m_vs_l6m", "l1m_vs_l12m", "l3m_vs_l12m"),
        "txn_accessories_canceled_count": ("l1m_vs_l3m", "l1m_vs_l6m", "l1m_vs_l12m", "l3m_vs_l12m"),
        "txn_accessories_canceled_price_sum": ("l1m_vs_l3m", "l1m_vs_l6m", "l1m_vs_l12m", "l3m_vs_l12m"),
        "txn_accessories_completed_amount_sum": ("l1m_vs_l3m", "l1m_vs_l6m", "l1m_vs_l12m", "l3m_vs_l12m"),
        "txn_accessories_completed_count": ("l12m", "l1m_vs_l3m", "l1m_vs_l6m", "l1m_vs_l12m", "l3m_vs_l12m"),
        "txn_accessories_completed_price_sum": ("l12m", "l1m_vs_l3m", "l1m_vs_l6m", "l1m_vs_l12m", "l3m_vs_l12m"),
        "txn_canceled_active_day_count": ("daily", "l1w", "l2w", "l1m", "l3m", "l6m", "l12m"),
        "txn_canceled_amount_sum": ("daily", "l1w", "l2w", "l1m", "l3m", "l6m", "l12m"),
        "txn_canceled_count": ("daily", "l1w", "l2w", "l1m", "l3m", "l6m", "l12m"),
        "txn_canceled_price_sum": ("daily", "l1w", "l2w", "l1m", "l3m", "l6m", "l12m"),
        "txn_canceled_processing_time_max": ("daily", "l1w", "l2w", "l1m", "l3m", "l6m", "l12m"),
        "txn_canceled_processing_time_min": ("daily", "l1w", "l2w", "l1m", "l3m", "l6m", "l12m"),
        "txn_completed_active_day_count": ("daily", "l1w", "l2w", "l1m", "l3m", "l6m", "l12m"),
        "txn_completed_amount_sum": ("daily", "l1w", "l2w", "l1m", "l3m", "l6m", "l12m"),
        "txn_completed_battery_sum": ("l12m",),
        "txn_completed_count": ("daily", "l1w", "l2w", "l1m", "l3m", "l6m", "l12m"),
        "txn_completed_price_sum": ("daily", "l1w", "l2w", "l1m", "l3m", "l6m", "l12m"),
        "txn_completed_processing_time_max": ("daily", "l1w", "l2w", "l1m", "l3m", "l6m", "l12m"),
        "txn_completed_processing_time_min": ("daily", "l1w", "l2w", "l1m", "l3m", "l6m", "l12m"),
        "txn_discount_accessories_completed_count": ("l12m",),
        "txn_discount_canceled_count": ("daily", "l1w", "l2w", "l1m", "l3m", "l6m", "l12m"),
        "txn_discount_completed_count": ("daily", "l1w", "l2w", "l1m", "l3m", "l6m", "l12m"),
        "txn_discount_delivered_count": ("daily", "l1w", "l2w", "l1m", "l3m", "l6m", "l12m"),
        "txn_discount_nvso_completed_count": ("l12m",),
        "txn_first_completed_updated_date_min": ("daily", "l1w", "l2w", "l1m", "l3m", "l6m", "l12m"),
        "txn_last_completed_updated_date_max": ("daily", "l1w", "l2w", "l1m", "l3m", "l6m", "l12m"),
        "txn_wo_canceled_amount_sum": ("l1m_vs_l3m", "l1m_vs_l6m", "l1m_vs_l12m", "l3m_vs_l12m"),
        "txn_wo_canceled_count": ("l1m_vs_l3m", "l1m_vs_l6m", "l1m_vs_l12m", "l3m_vs_l12m"),
        "txn_wo_canceled_price_sum": ("l1m_vs_l3m", "l1m_vs_l6m", "l1m_vs_l12m", "l3m_vs_l12m"),
        "txn_wo_completed_amount_sum": ("l1m_vs_l3m", "l1m_vs_l6m", "l1m_vs_l12m", "l3m_vs_l12m"),
        "txn_wo_completed_count": ("l1m_vs_l3m", "l1m_vs_l6m", "l1m_vs_l12m", "l3m_vs_l12m"),
        "txn_wo_completed_price_sum": ("l1m_vs_l3m", "l1m_vs_l6m", "l1m_vs_l12m", "l3m_vs_l12m"),
    }
)


def _column_type(name: str) -> str:
    if "_date_" in name:
        return "DATE"
    if "_vs_" in name or "_rate_" in name:
        return "NUMERIC(18, 6)"
    if "days_since_" in name or "_active_day_count_" in name or "_count_" in name:
        return "INTEGER"
    return "NUMERIC(20, 4)"


def _add_columns(table: str, columns: tuple[str, ...]) -> None:
    for name in columns:
        # Names are generated from the fixed inventory above; quote them so
        # future additions cannot accidentally become SQL identifiers.
        op.execute(
            f'ALTER TABLE feature."{table}" '
            f'ADD COLUMN IF NOT EXISTS "{name}" {_column_type(name)}'
        )


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise RuntimeError("Feature inventory alignment requires PostgreSQL.")
    if len(_GSM_FEATURES) != 167 or len(_VINFAST_FEATURES) != 186:
        raise RuntimeError("Inventory pattern expansion count changed unexpectedly.")
    _add_columns("gsm_transaction", _GSM_FEATURES)
    _add_columns("vinfast_transaction", _VINFAST_FEATURES)


def downgrade() -> None:
    # Do not drop columns in downgrade: these columns may have been populated
    # after upgrade.  A future retirement migration must explicitly archive
    # data and remove legacy columns under a separate change-control decision.
    pass
