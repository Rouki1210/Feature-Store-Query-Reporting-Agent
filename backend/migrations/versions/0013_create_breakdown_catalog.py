"""Semantic breakdown registry and query audit payload."""
from __future__ import annotations

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise RuntimeError("Breakdown catalog requires PostgreSQL.")
    op.execute("""
        CREATE TABLE IF NOT EXISTS metadata.breakdown_catalog (
            dimension_key          TEXT PRIMARY KEY,
            label_vi               TEXT NOT NULL,
            aliases                TEXT[] NOT NULL DEFAULT '{}',
            strategy                TEXT NOT NULL,
            source_tables           TEXT[] NOT NULL DEFAULT '{}',
            members                JSONB NOT NULL DEFAULT '[]'::jsonb,
            compatible_dimensions  TEXT[] NOT NULL DEFAULT '{}',
            overlap_possible       BOOLEAN NOT NULL DEFAULT FALSE,
            is_active               BOOLEAN NOT NULL DEFAULT TRUE,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT chk_breakdown_strategy
              CHECK (strategy IN ('pivot_feature', 'boolean_segment', 'physical_column'))
        )
    """)
    op.execute("GRANT SELECT ON metadata.breakdown_catalog TO feature_agent_reader")
    op.execute("""
        ALTER TABLE agent.query_log
        ADD COLUMN IF NOT EXISTS breakdown_plan JSONB
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE agent.query_log DROP COLUMN IF EXISTS breakdown_plan")
    op.execute("DROP TABLE IF EXISTS metadata.breakdown_catalog")
