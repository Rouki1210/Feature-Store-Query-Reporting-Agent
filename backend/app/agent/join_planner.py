"""Join Planner — quyết định đọc bảng nào, ghép thế nào (Task 2.4).

Thứ tự ưu tiên (docs/join_policy.md §2):

  1. `feature.customer_cross_bu_feature` — bảng tính sẵn. Nếu retrieval chạm tới nó
     thì dùng MỘT MÌNH nó, không join. Đây là đường mặc định cho câu hỏi xuyên BU
     (ADR 0001: join sai khóa = nhân dòng = số sai mà nhìn vẫn hợp lý).
  2. Join theo `metadata.join_catalog` — chỉ khi cần cột không có ở bảng tính sẵn.
  3. Không thuộc 1 và 2 ⇒ từ chối, KHÔNG tự chế join key.

Planner chỉ *lập kế hoạch*. Chốt chặn thật nằm ở `app/sql/guards.py` (Task 2.8) —
nó soi AST của SQL do LLM sinh. Planner sai thì guard vẫn chặn được.
"""
from __future__ import annotations

from dataclasses import dataclass, field

CROSS_BU_TABLE = "feature.customer_cross_bu_feature"


@dataclass(frozen=True)
class JoinRule:
    """Một dòng trong `metadata.join_catalog`."""
    left_table: str
    right_table: str
    join_keys: tuple[str, ...]
    join_type: str = "inner"
    cardinality: str = "1:1"
    requires_snapshot_key: bool = True
    allowed_intents: tuple[str, ...] = ()
    explanation_vi: str = ""
    is_active: bool = True

    @property
    def pair(self) -> frozenset[str]:
        return frozenset({self.left_table, self.right_table})


@dataclass(frozen=True)
class JoinPlan:
    tables: tuple[str, ...]
    join_keys: tuple[str, ...] = ()
    join_type: str | None = None
    explanation_vi: str = ""
    source: str = "catalog"

    @property
    def needs_join(self) -> bool:
        return len(self.tables) > 1

    def as_dict(self) -> dict:
        """Dạng ghi vào `agent.query_log.join_plan`."""
        return {
            "tables": list(self.tables),
            "join_keys": list(self.join_keys),
            "join_type": self.join_type,
            "explanation_vi": self.explanation_vi,
            "source": self.source,
        }


@dataclass(frozen=True)
class JoinDecision:
    plan: JoinPlan | None
    reason_vi: str = ""
    rejected_tables: tuple[str, ...] = field(default=())

    @property
    def ok(self) -> bool:
        return self.plan is not None


# Chỉ một dòng lúc khởi động. Thêm dòng khi có nhu cầu THẬT, kèm test dương và âm.
DEFAULT_RULES: tuple[JoinRule, ...] = (
    JoinRule(
        left_table="feature.gsm_transaction",
        right_table="feature.vinfast_transaction",
        join_keys=("customer_id", "snapshot_date"),
        join_type="inner",
        cardinality="1:1",
        allowed_intents=("cross_bu",),
        explanation_vi=(
            "Ghép GSM với VinFast theo cùng khách và cùng ngày snapshot "
            "(1 khách × 1 snapshot = 1 dòng ở mỗi bảng)."
        ),
    ),
)


class JoinPlanner:
    def __init__(self, rules: tuple[JoinRule, ...] = DEFAULT_RULES, max_joins: int = 2):
        self._rules = tuple(r for r in rules if r.is_active)
        self._max_joins = max_joins

    @classmethod
    def load_from_db(cls, max_joins: int = 2) -> "JoinPlanner":
        from sqlalchemy import text

        from app.db import get_engine

        sql = text("""
            SELECT left_table, right_table, join_keys, join_type, cardinality,
                   requires_snapshot_key, allowed_intents, explanation_vi, is_active
            FROM metadata.join_catalog
            WHERE is_active
        """)
        with get_engine().connect() as conn:
            rows = conn.execute(sql).mappings().all()
        return cls(tuple(
            JoinRule(
                left_table=r["left_table"], right_table=r["right_table"],
                join_keys=tuple(r["join_keys"]), join_type=r["join_type"],
                cardinality=r["cardinality"],
                requires_snapshot_key=r["requires_snapshot_key"],
                allowed_intents=tuple(r["allowed_intents"] or ()),
                explanation_vi=r["explanation_vi"] or "", is_active=r["is_active"],
            )
            for r in rows
        ), max_joins=max_joins)

    def rule_for(self, left: str, right: str) -> JoinRule | None:
        pair = frozenset({left, right})
        return next((r for r in self._rules if r.pair == pair), None)

    @property
    def rules(self) -> tuple[JoinRule, ...]:
        """Active catalog rules reused by the execution guard."""
        return self._rules

    def plan(self, intent: str, tables: set[str] | list[str]) -> JoinDecision:
        """Từ tập bảng mà retrieval chạm tới → kế hoạch đọc dữ liệu."""
        wanted = sorted(set(tables))
        if not wanted:
            return JoinDecision(None, "Chưa xác định được bảng dữ liệu cho câu hỏi này.")

        if CROSS_BU_TABLE in wanted:
            # Ưu tiên bảng tính sẵn kể cả khi retrieval kéo thêm bảng khác vào:
            # một bảng thì không có gì để join sai.
            dropped = tuple(t for t in wanted if t != CROSS_BU_TABLE)
            note = (
                " Không cần ghép bảng vì số liệu xuyên đơn vị đã được tính sẵn."
                if dropped else ""
            )
            return JoinDecision(
                JoinPlan(
                    tables=(CROSS_BU_TABLE,),
                    explanation_vi="Dùng bảng tổng hợp xuyên đơn vị đã tính sẵn." + note,
                    source="precomputed",
                ),
                rejected_tables=dropped,
            )

        if len(wanted) == 1:
            return JoinDecision(
                JoinPlan(tables=(wanted[0],), explanation_vi="Chỉ đọc một bảng, không ghép.")
            )

        if len(wanted) - 1 > self._max_joins:
            return JoinDecision(
                None,
                f"Câu hỏi cần ghép {len(wanted)} bảng, vượt giới hạn "
                f"{self._max_joins} phép ghép.",
                rejected_tables=tuple(wanted),
            )

        rule = self.rule_for(wanted[0], wanted[1])
        if rule is None:
            return JoinDecision(
                None,
                f"Chưa có đường ghép được duyệt giữa {wanted[0]} và {wanted[1]}.",
                rejected_tables=tuple(wanted),
            )
        if intent not in rule.allowed_intents:
            return JoinDecision(
                None,
                f"Intent '{intent}' không được phép dùng đường ghép này.",
                rejected_tables=tuple(wanted),
            )
        if rule.requires_snapshot_key and "snapshot_date" not in rule.join_keys:
            # Chốt chặn phòng thủ: CHECK ở DB đã cấm, nhưng catalog có thể tới từ
            # nguồn khác (test, seed tay) nên vẫn kiểm lại ở đây.
            return JoinDecision(
                None,
                f"Đường ghép {wanted[0]} × {wanted[1]} thiếu khóa snapshot_date.",
                rejected_tables=tuple(wanted),
            )
        return JoinDecision(JoinPlan(
            tables=(rule.left_table, rule.right_table),
            join_keys=rule.join_keys,
            join_type=rule.join_type,
            explanation_vi=rule.explanation_vi,
        ))

    def plan_for_features(self, intent: str, retrieved: list) -> JoinDecision:
        """Tiện dụng: nhận list feature (có `.table`) từ retriever."""
        return self.plan(intent, {getattr(f, "table", None) or f["table"] for f in retrieved})
