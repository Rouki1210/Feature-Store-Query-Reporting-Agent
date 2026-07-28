"""Allow Sprint 2 buyer/owner cases in the evaluation golden set."""
from __future__ import annotations

from alembic import op


revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE eval.query_test_case DROP CONSTRAINT IF EXISTS chk_query_test_case_category")
    op.execute("""
        ALTER TABLE eval.query_test_case ADD CONSTRAINT chk_query_test_case_category
        CHECK (test_category IN (
            'single_feature', 'time_comparison', 'service_breakdown', 'ambiguous_question',
            'out_of_scope', 'restricted_data', 'sql_safety', 'buyer_vs_owner'
        ))
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE eval.query_test_case DROP CONSTRAINT IF EXISTS chk_query_test_case_category")
    op.execute("""
        ALTER TABLE eval.query_test_case ADD CONSTRAINT chk_query_test_case_category
        CHECK (test_category IN (
            'single_feature', 'time_comparison', 'service_breakdown', 'ambiguous_question',
            'out_of_scope', 'restricted_data', 'sql_safety'
        ))
    """)
