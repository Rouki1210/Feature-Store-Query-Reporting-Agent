"""Allow the Sprint 2 v2 benchmark taxonomy in eval.query_test_case."""
from __future__ import annotations

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

_CONSTRAINT = "chk_query_test_case_category"
_CATEGORIES = (
    "single_feature", "time_comparison", "service_breakdown", "ambiguous_question",
    "out_of_scope", "restricted_data", "sql_safety", "buyer_vs_owner", "cross_bu",
    "point_in_time", "join_safety", "insufficient_data", "semantic_clarification",
    "short_term_state", "visualization",
)
_PREVIOUS = _CATEGORIES[:11]


def _values(categories: tuple[str, ...]) -> str:
    return ", ".join(f"'{category}'" for category in categories)


def upgrade() -> None:
    op.execute(f"ALTER TABLE eval.query_test_case DROP CONSTRAINT IF EXISTS {_CONSTRAINT}")
    op.execute(f"""
        ALTER TABLE eval.query_test_case
        ADD CONSTRAINT {_CONSTRAINT}
        CHECK (test_category IN ({_values(_CATEGORIES)}))
    """)


def downgrade() -> None:
    op.execute(f"ALTER TABLE eval.query_test_case DROP CONSTRAINT IF EXISTS {_CONSTRAINT}")
    op.execute(f"""
        ALTER TABLE eval.query_test_case
        ADD CONSTRAINT {_CONSTRAINT}
        CHECK (test_category IN ({_values(_PREVIOUS)}))
    """)
