"""Sprint 2 — nốt 2 category benchmark còn thiếu: point_in_time, join_safety.

`0010` mở `buyer_vs_owner`, `0011` mở `cross_bu`. Golden set Sprint 2 (S01–S26) còn
dùng `point_in_time` (UC2-12…14) và `join_safety` (UC2-05, UC2-26) nên seed vẫn
CheckViolation nếu thiếu bước này.

Danh sách phải khớp `app/eval/golden.py::CATEGORY` —
`test_golden_set_integrity::test_category_enum_matches_db_constraint` canh hai bên.

`multi_turn` CỐ Ý không có: evaluator gọi pipeline stateless, đo hội thoại phải qua
`ask_with_context` nên nhóm đó nằm ở `tests/test_multi_turn.py`.

Revision ID: 0012
Revises: 0011
Create Date: 2026-07-28
"""
from __future__ import annotations

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

_CONSTRAINT = "chk_query_test_case_category"
_BEFORE = (
    "single_feature", "time_comparison", "service_breakdown", "ambiguous_question",
    "out_of_scope", "restricted_data", "sql_safety", "buyer_vs_owner", "cross_bu",
)
_ADDED = ("point_in_time", "join_safety")


def _values(names: tuple[str, ...]) -> str:
    return ", ".join(f"'{n}'" for n in names)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise RuntimeError("Eval category constraint change requires PostgreSQL.")
    op.execute(f"ALTER TABLE eval.query_test_case DROP CONSTRAINT IF EXISTS {_CONSTRAINT}")
    op.execute(f"""
        ALTER TABLE eval.query_test_case
        ADD CONSTRAINT {_CONSTRAINT}
        CHECK (test_category IN ({_values(_BEFORE + _ADDED)}))
    """)


def downgrade() -> None:
    # Fail nếu còn case point_in_time/join_safety — đúng: hạ constraint khi còn dữ liệu
    # vi phạm là mất dữ liệu.
    op.execute(f"ALTER TABLE eval.query_test_case DROP CONSTRAINT IF EXISTS {_CONSTRAINT}")
    op.execute(f"""
        ALTER TABLE eval.query_test_case
        ADD CONSTRAINT {_CONSTRAINT}
        CHECK (test_category IN ({_values(_BEFORE)}))
    """)
