"""Deterministic bilingual semantic retriever for the canonical inventory."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache

_TABLE_HINTS = {
    "gsm_transaction": (
        "gsm", "xanh sm", "taxi", "gọi xe", "giao hàng", "chuyến", "ride",
        "ride hailing", "trip", "delivery",
    ),
    "vinfast_transaction": (
        "vinfast", "vf", "ô tô", "oto", "xe điện", "phụ kiện", "đơn xe",
        "ev", "electric vehicle", "car", "scooter", "accessories", "order",
    ),
}

_WINDOW_ALIASES = {
    "daily": ("daily", "hôm nay", "hom nay", "trong ngày", "today"),
    "l1w": ("l1w", "1 tuần", "1 tuan", "tuần gần nhất", "last 1 week", "last week"),
    "l2w": ("l2w", "2 tuần", "2 tuan", "last 2 weeks"),
    "l4w": ("l4w", "4 tuần", "4 tuan", "last 4 weeks"),
    "l1m": ("l1m", "1 tháng", "1 thang", "tháng gần nhất", "last 1 month", "last month"),
    "l2m": ("l2m", "2 tháng", "2 thang", "last 2 months"),
    "l3m": ("l3m", "3 tháng", "3 thang", "last 3 months"),
    "l6m": ("l6m", "6 tháng", "6 thang", "last 6 months"),
    "l8w": ("l8w", "8 tuần", "8 tuan", "last 8 weeks"),
    "l12m": ("l12m", "12 tháng", "12 thang", "last 12 months"),
}

_RISK_TERMS = {
    "nvso", "work order", "work_order", "wo", "owner", "ownership",
    "chủ sở hữu", "sở hữu", "buyer", "người mua", "completed order",
    "đơn hoàn thành",
}


def _strip_accents(text: str) -> str:
    text = text.replace("đ", "d").replace("Đ", "D")
    return "".join(
        c for c in unicodedata.normalize("NFD", text)
        if unicodedata.category(c) != "Mn"
    ).lower()


def _tokens(text: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9_]+", _strip_accents(text)) if len(t) >= 2}


def _has_term(text: str, terms: tuple[str, ...]) -> bool:
    return any(
        re.search(
            rf"(?<![a-z0-9_]){re.escape(_strip_accents(term))}(?![a-z0-9_])",
            text,
        )
        for term in terms
    )


@dataclass
class ScoredFeature:
    name: str
    table: str
    group: str
    description_vi: str
    description_en: str
    keywords: list[str]
    score: float
    support_status: str = "queryable"
    dtype: str | None = None
    unit: str | None = None
    null_meaning: str | None = None


class SemanticLayer:
    def __init__(self, features: list[dict]):
        self.features = [
            f for f in features
            if f.get("is_active", True) and f.get("is_queryable", True)
        ]
        self._norm: list[tuple[dict, str, set[str]]] = []
        for f in self.features:
            searchable = " ".join(
                [
                    f.get("name", ""),
                    f.get("group", ""),
                    f.get("description_vi", ""),
                    f.get("description_en", ""),
                    " ".join(f.get("keywords", [])),
                ]
            )
            self._norm.append((f, _strip_accents(searchable), _tokens(searchable)))

    @classmethod
    def load(cls, path: str) -> "SemanticLayer":
        import yaml

        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        return cls(data.get("features", []))

    @classmethod
    def load_from_db(cls) -> "SemanticLayer":
        """Đọc catalog (seed từ YAML authoritative) — nguồn runtime của agent."""
        from sqlalchemy import text

        from app.db import get_engine

        sql = text("""
            SELECT fc.feature_name, fc.table_schema, fc.table_name, fc.feature_group,
                   fc.description_vi, fc.description_en, fc.data_type, fc.aggregation_type,
                   fc.time_window, fc.unit, fc.null_meaning,
                   COALESCE(array_agg(fs.synonym_text)
                            FILTER (WHERE fs.synonym_text IS NOT NULL), '{}') AS keywords
            FROM metadata.feature_catalog fc
            LEFT JOIN metadata.feature_synonyms fs
              ON fs.feature_id = fc.feature_id AND fs.is_active
            WHERE fc.table_schema = 'feature' AND fc.is_active AND fc.is_queryable
            GROUP BY fc.feature_id
        """)
        with get_engine().connect() as conn:
            rows = conn.execute(sql).mappings().all()
        features = [{
            "name": r["feature_name"],
            "table": f'{r["table_schema"]}.{r["table_name"]}',
            "group": r["feature_group"],
            "description_vi": r["description_vi"] or "",
            "description_en": r["description_en"] or "",
            "dtype": r["data_type"],
            "aggregation": r["aggregation_type"],
            "window": r["time_window"],
            "unit": r["unit"],
            "null_meaning": r["null_meaning"],
            "keywords": list(r["keywords"]),
            "support_status": "queryable",  # WHERE is_queryable đã loại NVSO/WO
        } for r in rows]
        return cls(features)

    def __len__(self) -> int:
        return len(self.features)

    def is_cross_pnl(self, question: str) -> bool:
        q = _strip_accents(question)
        return any(
            term in q
            for term in (
                "cross pnl", "cross-pnl", "lien pnl", "cheo nganh", "earn",
                "burn", "tich diem", "tieu diem", "redeem", "loyalty",
            )
        )

    @staticmethod
    def _table_scores(q_norm: str) -> dict[str, float]:
        return {
            table: sum(1.0 for hint in hints if _strip_accents(hint) in q_norm)
            for table, hints in _TABLE_HINTS.items()
        }

    @staticmethod
    def _window_hint(q_norm: str) -> str | None:
        matches = SemanticLayer._window_hints(q_norm)
        return matches[0] if matches else None

    @staticmethod
    def _window_hints(q_norm: str) -> list[str]:
        matches: list[tuple[int, str]] = []
        for window, aliases in _WINDOW_ALIASES.items():
            positions = [
                q_norm.find(_strip_accents(alias))
                for alias in aliases
                if _strip_accents(alias) in q_norm
            ]
            if positions:
                matches.append((min(positions), window))
        matches.sort()
        return [window for _, window in matches]

    @staticmethod
    def _metric_hint(q_norm: str) -> str | None:
        if _has_term(q_norm, ("ty le", "ratio", "rate", "trend", "xu huong", "so sanh", "compare")):
            return "ratio"
        if _has_term(q_norm, ("tong tien", "chi tieu", "doanh thu", "amount", "spend", "value", "price", "gia")):
            return "value"
        if _has_term(
            q_norm,
            (
                "so chuyen", "so don", "bao nhieu", "count", "frequency",
                "number of", "trip", "trips", "order", "orders",
            ),
        ):
            return "count"
        return None

    @staticmethod
    def _is_compare(q_norm: str) -> bool:
        return _has_term(
            q_norm, ("so sanh", "compare", "versus", "vs", "tang giam", "trend")
        )

    def retrieve(
        self,
        question: str,
        top_k: int | None = None,
        *,
        business_unit: str | None = None,
        group: str | None = None,
    ) -> list[ScoredFeature]:
        if top_k is None:
            from app.config import get_settings

            top_k = get_settings().retrieval_top_k
        q_norm = _strip_accents(question)
        q_tokens = _tokens(question)
        table_scores = self._table_scores(q_norm)
        window_hints = self._window_hints(q_norm)
        window_hint = window_hints[0] if window_hints else None
        metric_hint = self._metric_hint(q_norm)
        compare = self._is_compare(q_norm)
        value_requested = _has_term(
            q_norm,
            (
                "tong tien", "chi tieu", "doanh thu", "amount", "spend",
                "value", "price", "gia",
            ),
        )
        discount_requested = _has_term(q_norm, ("discount", "chiet khau", "giam gia"))
        count_requested = not value_requested and _has_term(
            q_norm,
            (
                "so chuyen", "so don", "bao nhieu", "count", "frequency",
                "number of", "trip", "trips", "order", "orders",
            ),
        )
        ratio_window = (
            f"{window_hints[0]}_vs_{window_hints[1]}"
            if compare and len(window_hints) >= 2
            else None
        )
        unit = business_unit.lower() if business_unit else None

        scored: list[ScoredFeature] = []
        for f, searchable, feature_tokens in self._norm:
            table = f.get("table", "").split(".", 1)[-1]
            if unit and not table.startswith(unit):
                continue
            if group and f.get("group") != group:
                continue
            feature_window = f.get("window")
            if window_hint and not compare and feature_window not in (window_hint, None):
                continue
            if ratio_window and feature_window != ratio_window:
                continue
            has_count = bool(re.search(r"(?:^|_)count(?:_|$)", f.get("name", "")))
            if metric_hint == "count" and not has_count and "active_day" not in f.get("name", ""):
                continue
            if metric_hint == "value" and not any(
                x in f.get("name", "") for x in ("amount", "price", "discount", "battery")
            ):
                continue
            if metric_hint == "ratio" and f.get("aggregation") != "ratio":
                continue
            name = f.get("name", "")
            if compare and count_requested and not has_count:
                continue
            if compare and value_requested and not any(
                x in name for x in ("amount", "price", "discount", "battery")
            ):
                continue
            if _has_term(q_norm, ("cancel", "canceled", "cancelled", "huy")) and "canceled" not in name:
                continue
            if _has_term(q_norm, ("completed", "finished", "hoan thanh")) and not any(
                x in name for x in ("completed", "finished")
            ):
                continue
            if discount_requested and "discount" not in name:
                continue
            if value_requested and not discount_requested:
                if "discount" in name:
                    continue
            if _has_term(q_norm, ("distance", "quang duong", "km")) and "distance" not in name:
                continue
            if _has_term(q_norm, ("active day", "ngay hoat dong")) and "active_day" not in name:
                continue
            if _has_term(q_norm, ("processing time", "thoi gian xu ly")) and "processing_time" not in name:
                continue
            if _has_term(q_norm, ("amount",)):
                if table == "gsm_transaction":
                    if "original_price" not in name or "discount" in name:
                        continue
                elif "amount" not in name:
                    continue
            if _has_term(q_norm, ("price",)) and "price" not in name:
                continue
            if value_requested and not _has_term(q_norm, ("max", "maximum", "highest", "lon nhat")):
                if name.endswith("_max_" + str(feature_window)) or "_max_" in name:
                    continue
            if value_requested and not _has_term(q_norm, ("min", "minimum", "lowest", "nho nhat")):
                if name.endswith("_min_" + str(feature_window)) or "_min_" in name:
                    continue
            if metric_hint == "count" and not _has_term(q_norm, ("active day", "ngay hoat dong")):
                if "active_day" in name:
                    continue
            if not _has_term(q_norm, ("weekday", "ngay trong tuan")) and "weekday" in name:
                continue
            if not _has_term(q_norm, ("daytime", "ban ngay")) and "daytime" in name:
                continue

            score = 0.0
            name_norm = _strip_accents(name)
            if name_norm in q_norm:
                score += 8.0
            for kw in f.get("keywords", []):
                kw_norm = _strip_accents(kw)
                if kw_norm and kw_norm in q_norm:
                    score += 1.5 + min(len(kw_norm.split()), 4) * 0.25
            score += 0.25 * len(q_tokens & feature_tokens)
            score += 1.25 * table_scores.get(table, 0)
            if window_hint and feature_window == window_hint:
                score += 2.0
            if compare and f.get("aggregation") == "ratio":
                score += 2.5
            if "nvso" in q_norm and "nvso" in name_norm:
                score += 3.0
            if any(term in q_norm for term in ("work order", "work_order", "wo")) and "_wo_" in name_norm:
                score += 3.0
            if score <= 0:
                continue
            scored.append(
                ScoredFeature(
                    name=f["name"],
                    table=f["table"],
                    group=f.get("group", ""),
                    description_vi=f.get("description_vi", ""),
                    description_en=f.get("description_en", ""),
                    keywords=f.get("keywords", []),
                    score=round(score, 3),
                    support_status=f.get("support_status", "queryable"),
                    dtype=f.get("dtype"),
                    unit=f.get("unit"),
                    null_meaning=f.get("null_meaning"),
                )
            )
        scored.sort(key=lambda item: (-item.score, item.name))
        if not scored:
            return []
        return scored[: max(1, top_k)]


@lru_cache
def get_semantic_layer() -> SemanticLayer:
    # Agent đọc DB catalog (đã seed từ YAML authoritative). Tests dùng trực tiếp
    # SemanticLayer.load(yaml_path) khi cần chạy offline không có DB.
    return SemanticLayer.load_from_db()
