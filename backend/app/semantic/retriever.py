"""Bộ truy hồi feature — keyword matching song ngữ (VI + EN) trên keyword sinh sẵn.

Tiered retrieval (CLAUDE.md mục 4): thu hẹp theo tầng bảng → nhóm → feature cụ thể.
Bắt đầu bằng keyword matching (mục 6 bước 2); nâng cấp embeddings sau nếu đo lường
cho thấy đáng. Câu hỏi tiếng Việt được bỏ dấu để match; keyword EN match trực tiếp.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from functools import lru_cache

# Gợi ý bảng theo từ khóa VI + EN (tầng 1 của tiered retrieval).
_TABLE_HINTS = {
    "gsm_transaction": [
        "gsm", "xanh sm", "taxi", "gọi xe", "giao hàng", "chuyến", "di chuyển",
        "ride", "ride-hailing", "trip", "delivery",
    ],
    "vinfast_transaction": [
        "vinfast", "ô tô", "oto", "xe điện", "xe máy điện", "phụ kiện", "đơn xe",
        "ev", "electric vehicle", "car", "scooter", "accessories",
    ],
    "global_loyalty": [
        "điểm", "point", "points", "loyalty", "vinclub", "tích điểm", "tiêu điểm",
        "liên pnl", "cross pnl", "chéo ngành", "chuyển dịch",
        "earn", "burn", "redeem", "rewards", "membership", "cross-business",
    ],
}


def _strip_accents(text: str) -> str:
    """Bỏ dấu để match không phân biệt có dấu / không dấu.

    Lưu ý: 'đ/Đ' là chữ cái riêng (không phải dấu kết hợp) nên NFD không tách
    được — phải thay thủ công, nếu không 'điểm' → 'điem' và mọi signal chứa
    'diem' sẽ trượt.
    """
    text = text.replace("đ", "d").replace("Đ", "D")
    nfkd = unicodedata.normalize("NFD", text)
    return "".join(c for c in nfkd if unicodedata.category(c) != "Mn").lower()


@dataclass
class ScoredFeature:
    name: str
    table: str
    group: str
    description_vi: str
    description_en: str
    keywords: list[str]
    score: float


class SemanticLayer:
    """Nạp semantic_layer.yaml và cung cấp retrieve(question)."""

    def __init__(self, features: list[dict]):
        self.features = features
        # Chuẩn hóa sẵn keyword để match nhanh.
        self._norm: list[tuple[dict, list[str], str]] = []
        for f in features:
            kws = [_strip_accents(k) for k in f.get("keywords", [])]
            desc = _strip_accents(
                f.get("description_vi", "") + " " + f.get("description_en", "")
            )
            self._norm.append((f, kws, desc))

    @classmethod
    def load(cls, path: str) -> "SemanticLayer":
        import yaml  # import trễ — chỉ cần khi nạp từ file

        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        return cls(data.get("features", []))

    def __len__(self) -> int:
        return len(self.features)

    def is_cross_pnl(self, question: str) -> bool:
        q = _strip_accents(question)
        signals = ["lien pnl", "cross pnl", "cheo nganh", "chuyen dich", "earn", "burn",
                   "tich diem", "tieu diem", "chuyen tu", "sang vinfast", "tu gsm",
                   "cross-business", "cross unit", "redeem", "shift"]
        return any(s in q for s in signals)

    def _table_scores(self, q_norm: str) -> dict[str, float]:
        scores: dict[str, float] = {}
        for table, hints in _TABLE_HINTS.items():
            s = sum(1.0 for h in hints if _strip_accents(h) in q_norm)
            scores[table] = s
        return scores

    def retrieve(self, question: str, top_k: int | None = None) -> list[ScoredFeature]:
        if top_k is None:
            from app.config import get_settings  # import trễ

            top_k = get_settings().retrieval_top_k
        q_norm = _strip_accents(question)
        table_scores = self._table_scores(q_norm)
        cross_pnl = self.is_cross_pnl(question)

        scored: list[ScoredFeature] = []
        for f, kws, desc in self._norm:
            score = 0.0
            # Tầng feature: keyword overlap (cụm dài hơn = trọng số cao hơn).
            for kw in kws:
                if kw and kw in q_norm:
                    score += 1.0 + 0.15 * len(kw.split())
            # Match trong mô tả (nhẹ hơn).
            for tok in set(q_norm.split()):
                if len(tok) >= 3 and tok in desc:
                    score += 0.2
            # Tầng bảng: cộng điểm gợi ý bảng.
            score += 0.5 * table_scores.get(f["table"], 0.0)
            # Router cross-PnL: ưu tiên bảng loyalty (centre of gravity).
            if cross_pnl and f["table"] == "global_loyalty":
                score += 1.0
            if score > 0:
                scored.append(ScoredFeature(
                    name=f["name"], table=f["table"], group=f["group"],
                    description_vi=f["description_vi"],
                    description_en=f.get("description_en", ""),
                    keywords=f.get("keywords", []),
                    score=round(score, 3),
                ))

        scored.sort(key=lambda x: x.score, reverse=True)
        return scored[:top_k]


@lru_cache
def get_semantic_layer() -> SemanticLayer:
    from app.config import get_settings  # import trễ

    return SemanticLayer.load(get_settings().semantic_layer_path)
