"""Metadata-driven breakdown planning and deterministic SQL compilation."""
from __future__ import annotations

import itertools
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Iterable

from app.agent.contracts import BreakdownPlan, GenerationResponse, IntentType, RouteDecision

CROSS_TABLE = "feature.customer_cross_bu_feature"
GSM_TABLE = "feature.gsm_transaction"
VF_TABLE = "feature.vinfast_transaction"

# Bảng được phép xuất hiện trong SQL biên dịch. Catalog nằm trong DB nên `table` của
# member là DỮ LIỆU, không phải hằng số trong code — phải đối chiếu allowlist trước
# khi nối vào câu lệnh.
_COMPILABLE_TABLES = frozenset({CROSS_TABLE, GSM_TABLE, VF_TABLE})
# Identifier hợp lệ: chữ thường, số, gạch dưới. Mọi thứ khác bị từ chối thay vì escape —
# tên cột/nhãn chiều không có lý do chính đáng để chứa dấu cách, nháy hay dấu chấm.
_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]*$")


def _safe_identifier(value: str, kind: str) -> str:
    """Định danh đi vào SQL phải khớp allowlist — catalog là dữ liệu, không phải code."""
    text = str(value)
    if not _IDENTIFIER.fullmatch(text):
        raise ValueError(f"Breakdown {kind} không hợp lệ để sinh SQL: {text!r}")
    return text


def _safe_table(value: str) -> str:
    """Chỉ ba bảng feature được phép; chặn cả mẹo nối 'bảng WHERE ... --'."""
    text = str(value)
    if text not in _COMPILABLE_TABLES:
        raise ValueError(f"Breakdown table ngoài allowlist: {text!r}")
    return text


def _safe_literal(value: str) -> str:
    """Nhãn hiển thị là chuỗi tự do, nhưng phải là literal — không được thoát ra khỏi nháy."""
    return "'" + str(value).replace("'", "''") + "'"


def _max_groups() -> int:
    from app.config import get_settings

    return get_settings().breakdown_max_groups




@dataclass(frozen=True)
class BreakdownSpec:
    key: str
    label_vi: str
    aliases: tuple[str, ...]
    strategy: str
    source_tables: tuple[str, ...]
    members: tuple[dict[str, Any], ...] = ()
    compatible_dimensions: tuple[str, ...] = ()
    overlap_possible: bool = False
    is_active: bool = True

    def as_catalog_dict(self) -> dict[str, Any]:
        return {
            "dimension_key": self.key,
            "label_vi": self.label_vi,
            "aliases": list(self.aliases),
            "strategy": self.strategy,
            "source_tables": list(self.source_tables),
            "members": list(self.members),
            "compatible_dimensions": list(self.compatible_dimensions),
            "overlap_possible": self.overlap_possible,
            "is_active": self.is_active,
        }


DEFAULT_BREAKDOWNS: tuple[BreakdownSpec, ...] = (
    BreakdownSpec(
        key="business_unit",
        label_vi="Business unit",
        aliases=(
            "theo từng business unit", "từng business unit", "mỗi business unit",
            "theo business unit", "by business unit", "each business unit",
            "business unit", "bu breakdown", "theo bu",
        ),
        strategy="pivot_feature",
        source_tables=(CROSS_TABLE,),
        compatible_dimensions=("window",),
        members=(
            {"key": "GSM", "label": "GSM", "spend": "gsm_spend_{window}",
             "population_flag": "is_active_gsm_{window}"},
            {"key": "VINFAST", "label": "VINFAST", "spend": "vinfast_spend_{window}",
             "population_flag": "is_active_vinfast_{window}"},
        ),
    ),
    BreakdownSpec(
        key="service_type",
        label_vi="Loại dịch vụ/sản phẩm",
        aliases=(
            "theo dịch vụ", "từng dịch vụ", "mỗi dịch vụ", "loại dịch vụ",
            "service breakdown", "by service", "theo sản phẩm", "loại sản phẩm",
        ),
        strategy="pivot_feature",
        source_tables=(GSM_TABLE, VF_TABLE),
        compatible_dimensions=("window",),
        members=(
            {"key": "taxi", "label": "Taxi", "business_unit": "GSM",
             "table": GSM_TABLE, "count": "finished_type_taxi_txn_count_{window}"},
            {"key": "bike", "label": "Bike", "business_unit": "GSM",
             "table": GSM_TABLE, "count": "finished_type_bike_txn_count_{window}"},
            {"key": "express", "label": "Express", "business_unit": "GSM",
             "table": GSM_TABLE, "count": "finished_type_express_txn_count_{window}"},
            {"key": "food", "label": "Food", "business_unit": "GSM",
             "table": GSM_TABLE, "count": "finished_type_food_txn_count_{window}"},
            {"key": "accessories", "label": "Accessories", "business_unit": "VINFAST",
             "table": VF_TABLE, "count": "txn_accessories_completed_count_{window}"},
        ),
    ),
    BreakdownSpec(
        key="customer_state",
        label_vi="Trạng thái khách hàng",
        aliases=(
            "theo trạng thái", "từng trạng thái", "trạng thái khách hàng",
            "customer state", "customer status", "by status",
        ),
        strategy="boolean_segment",
        source_tables=(CROSS_TABLE, VF_TABLE),
        compatible_dimensions=("window",),
        overlap_possible=True,
        members=(
            {"key": "active_gsm", "label": "Active GSM", "business_unit": "CROSS_BU",
             "table": CROSS_TABLE, "flag": "is_active_gsm_{window}"},
            {"key": "active_vinfast", "label": "Active VinFast", "business_unit": "CROSS_BU",
             "table": CROSS_TABLE, "flag": "is_active_vinfast_{window}"},
            {"key": "buyer", "label": "Buyer", "business_unit": "VINFAST",
             "table": VF_TABLE, "flag": "is_vehicle_buyer"},
            {"key": "owner", "label": "Owner", "business_unit": "VINFAST",
             "table": VF_TABLE, "flag": "is_vehicle_owner"},
            {"key": "handover_scheduled", "label": "Handover scheduled",
             "business_unit": "VINFAST", "table": VF_TABLE,
             "flag": "is_vehicle_handover_scheduled"},
        ),
    ),
    BreakdownSpec(
        key="window",
        label_vi="Cửa sổ thời gian",
        aliases=(
            "theo cửa sổ", "theo khoảng thời gian", "từng khoảng thời gian",
            "theo window", "by window", "time window",
        ),
        strategy="pivot_feature",
        source_tables=(CROSS_TABLE, GSM_TABLE, VF_TABLE),
        compatible_dimensions=("business_unit", "service_type", "customer_state"),
    ),
    BreakdownSpec(
        key="snapshot_date",
        label_vi="Ngày snapshot",
        aliases=(
            "theo snapshot", "theo ngày snapshot", "lịch sử snapshot",
            "by snapshot", "snapshot date",
        ),
        strategy="physical_column",
        source_tables=(CROSS_TABLE, GSM_TABLE, VF_TABLE),
    ),
)

_WINDOWS = ("daily", "l1w", "l2w", "l1m", "l3m", "l6m", "l12m", "all")
_WINDOW_ALIASES = {
    "daily": ("hôm nay", "trong ngày", "daily"),
    "l1w": ("1 tuần", "một tuần", "1 week", "l1w"),
    "l2w": ("2 tuần", "hai tuần", "2 weeks", "l2w"),
    "l1m": ("1 tháng", "một tháng", "1 month", "l1m"),
    "l3m": ("3 tháng", "ba tháng", "quý", "3 months", "l3m"),
    "l6m": ("6 tháng", "sáu tháng", "nửa năm", "6 months", "l6m"),
    "l12m": ("12 tháng", "một năm", "1 năm", "12 months", "1 year", "l12m"),
    "all": ("tổng cộng", "toàn thời gian", "từ trước đến nay", "lũy kế", "all"),
}
_GENERIC_BREAKDOWN = (
    "chia theo", "phân nhóm", "phân bổ theo", "breakdown", "group by", "theo từng", "mỗi nhóm",
)
_PER_CUSTOMER_LIST = ("theo từng khách", "mỗi khách", "per customer", "each customer")
_NO_BREAKDOWN = ("không chia nhóm", "tổng chung", "overall", "no breakdown")
_INDEPENDENT = ("nhóm độc lập", "độc lập", "independent")
_EXCLUSIVE = ("nhóm loại trừ", "loại trừ", "exclusive")


def _norm(value: str) -> str:
    value = value.replace("đ", "d").replace("Đ", "D")
    return "".join(
        ch for ch in unicodedata.normalize("NFD", value)
        if unicodedata.category(ch) != "Mn"
    ).lower()


def _contains(text: str, values: Iterable[str]) -> bool:
    normalized = _norm(text)
    return any(_norm(value) in normalized for value in values)


def _feature_names(features: Iterable[Any]) -> set[str]:
    return {
        str(getattr(feature, "name", None) or feature.get("name"))
        for feature in features
    }


def _requested_windows(question: str) -> list[str]:
    """Cùng bộ nhận cửa sổ với retriever/router (xem `router._has_window`)."""
    from app.semantic.retriever import SemanticLayer

    found = set(SemanticLayer._window_hints(_norm(question)))
    found.update(
        window for window, aliases in _WINDOW_ALIASES.items()
        if any(_norm(alias) in _norm(question) for alias in aliases)
    )
    return [window for window in _WINDOWS if window in found]


_METRIC_TERMS: dict[str, tuple[str, ...]] = {
    # "so khach" phủ cả "số khách", "số khách hàng", "số lượng khách hàng" — thiếu nó
    # thì câu hỏi đếm khách hoàn toàn bình thường bị hỏi lại "muốn tính chỉ số nào?".
    "customer_count": ("so luong khach hang", "so luong khach", "so khach hang", "so khach",
                       "bao nhieu khach", "customer count", "number of customers"),
    "transaction_count": ("so chuyen", "so don", "so giao dich", "transaction count",
                          "trip count", "order count"),
    "total_revenue": ("doanh thu", "chi tieu", "tong tien", "revenue", "spend"),
}


def _norm_positions(text: str) -> tuple[str, list[int]]:
    """Chuỗi đã bỏ dấu + vị trí ký tự gốc tương ứng (normalize theo từng ký tự)."""
    out, index = [], []
    for position, char in enumerate(text):
        piece = _norm(char)
        out.append(piece)
        index.extend([position] * len(piece))
    return "".join(out), index


def strip_phrases(question: str, terms: Iterable[str]) -> str:
    """Gỡ các cụm đã được clarify trả lời khỏi câu gốc.

    Ghép câu trả lời mà GIỮ cụm cũ thì bộ nhận dạng vẫn đọc ra cụm cũ, cùng một
    clarify lại bắn, và vòng hỏi-lại không bao giờ thoát. Cắt theo vị trí ký tự GỐC nên
    dấu tiếng Việt và phần còn lại của câu giữ nguyên.
    """
    normalized, index = _norm_positions(question)
    cuts: list[tuple[int, int]] = []
    for term in terms:
        needle = _norm(term)
        start = normalized.find(needle)
        while start != -1:
            cuts.append((index[start], index[start + len(needle) - 1] + 1))
            start = normalized.find(needle, start + len(needle))
    kept = "".join(
        char for position, char in enumerate(question)
        if not any(low <= position < high for low, high in cuts)
    )
    return " ".join(kept.split())


def strip_metric_phrases(question: str) -> str:
    return strip_phrases(
        question, (term for terms in _METRIC_TERMS.values() for term in terms)
    )


_THRESHOLD_TERMS = (
    "lon hon", "nho hon", "it nhat", "toi thieu", "toi da", "tro len", "vuot qua",
    "tren ", "duoi ", ">", "<",
)


def _has_threshold_filter(question: str) -> bool:
    """Câu có điều kiện ngưỡng kèm con số ⇒ breakdown không diễn đạt được."""
    normalized = _norm(question)
    return any(term in normalized for term in _THRESHOLD_TERMS) and any(
        char.isdigit() for char in normalized
    )


def _metric_requests(question: str) -> list[dict[str, str]]:
    q = _norm(question)
    metrics: list[dict[str, str]] = []
    found = {
        key for key, terms in _METRIC_TERMS.items() if any(term in q for term in terms)
    }
    customer_count = "customer_count" in found
    transaction_count = "transaction_count" in found
    revenue = "total_revenue" in found
    average = any(term in q for term in ("trung binh", "average", "avg"))
    if customer_count:
        metrics.append({"key": "customer_count", "alias": "customer_count", "aggregate": "count_true"})
    if transaction_count:
        metrics.append({"key": "transaction_count", "alias": "transaction_count", "aggregate": "sum"})
    if revenue:
        metrics.append({
            "key": "total_revenue",
            "alias": "average_revenue" if average else "total_revenue",
            "aggregate": "avg" if average else "sum",
        })
    return metrics


@dataclass(frozen=True)
class BreakdownDecision:
    plan: BreakdownPlan | None = None
    clarifying_question: str | None = None
    options: tuple[dict[str, str], ...] = ()
    missing_slot: str | None = None


class BreakdownPlanner:
    def __init__(self, specs: tuple[BreakdownSpec, ...] = DEFAULT_BREAKDOWNS):
        self.specs = tuple(spec for spec in specs if spec.is_active)
        self._by_key = {spec.key: spec for spec in self.specs}

    @classmethod
    def load_from_db(cls) -> "BreakdownPlanner":
        from sqlalchemy import text

        from app.db import get_engine

        with get_engine().connect() as conn:
            rows = conn.execute(text("""
                SELECT dimension_key, label_vi, aliases, strategy, source_tables,
                       members, compatible_dimensions, overlap_possible, is_active
                FROM metadata.breakdown_catalog WHERE is_active
                ORDER BY dimension_key
            """)).mappings().all()
        return cls(tuple(
            BreakdownSpec(
                key=row["dimension_key"], label_vi=row["label_vi"],
                aliases=tuple(row["aliases"] or ()), strategy=row["strategy"],
                source_tables=tuple(row["source_tables"] or ()),
                members=tuple(row["members"] or ()),
                compatible_dimensions=tuple(row["compatible_dimensions"] or ()),
                overlap_possible=row["overlap_possible"], is_active=row["is_active"],
            )
            for row in rows
        ))

    def detect_dimensions(self, question: str) -> list[str]:
        return [
            spec.key for spec in self.specs
            if _contains(question, spec.aliases)
        ][:2]

    def dimension_from_answer(self, answer: str) -> str | None:
        if _contains(answer, _NO_BREAKDOWN):
            return "none"
        normalized = _norm(answer).strip()
        for spec in self.specs:
            if normalized in {_norm(spec.key), _norm(spec.label_vi), *map(_norm, spec.aliases)}:
                return spec.key
        return None

    def needs_dimension_choice(self, question: str, dimensions: list[str]) -> bool:
        return (
            not dimensions
            and _contains(question, _GENERIC_BREAKDOWN)
            and not _contains(question, _NO_BREAKDOWN)
            and not _contains(question, _PER_CUSTOMER_LIST)
        )

    def options_for(self, business_unit: str | None) -> tuple[dict[str, str], ...]:
        unit = (business_unit or "").upper()
        allowed = {"business_unit", "window", "snapshot_date"}
        if unit in {"GSM", "VINFAST"}:
            allowed.add("service_type")
        if unit in {"VINFAST", "CROSS_BU"}:
            allowed.add("customer_state")
        return (
            {"value": "none", "label": "Tổng chung"},
            *(
                {"value": spec.key, "label": spec.label_vi}
                for spec in self.specs if spec.key in allowed
            ),
        )

    def plan(
        self,
        question: str,
        route: RouteDecision,
        catalog_features: Iterable[Any],
        dimensions: list[str] | None = None,
    ) -> BreakdownDecision:
        dimensions = dimensions if dimensions is not None else self.detect_dimensions(question)
        if not dimensions or dimensions == ["none"]:
            return BreakdownDecision()
        if _has_threshold_filter(question):
            # Branch của breakdown chỉ biết đếm/cộng cả nhóm, không mang theo điều kiện
            # ngưỡng ("chi tiêu > 100 triệu"). Sinh plan ở đây là trả số ĐÚNG CÚ PHÁP
            # nhưng SAI CÂU HỎI mà không báo gì. Nhường lại đường LLM thông thường.
            return BreakdownDecision()
        if len(dimensions) > 2:
            return BreakdownDecision(
                clarifying_question="Mỗi truy vấn chỉ hỗ trợ tối đa 2 chiều phân nhóm.",
                options=self.options_for(route.business_unit),
                missing_slot="breakdown_dimension",
            )
        first = self._by_key.get(dimensions[0])
        if first is None:
            return BreakdownDecision(
                clarifying_question="Chiều phân nhóm chưa có trong semantic metadata.",
                options=self.options_for(route.business_unit),
                missing_slot="breakdown_dimension",
            )
        if len(dimensions) == 2 and dimensions[1] not in first.compatible_dimensions:
            return BreakdownDecision(
                clarifying_question="Hai chiều phân nhóm này chưa có mapping dữ liệu tương thích.",
                options=self.options_for(route.business_unit),
                missing_slot="breakdown_dimension",
            )

        metrics = _metric_requests(question)
        if not metrics:
            return BreakdownDecision(
                clarifying_question="Bạn muốn tính chỉ số nào cho từng nhóm?",
                options=(
                    {"value": "Số lượng khách hàng", "label": "Số lượng khách hàng"},
                    {"value": "Tổng doanh thu", "label": "Tổng doanh thu"},
                    {"value": "Số giao dịch", "label": "Số giao dịch"},
                ),
                missing_slot="metric",
            )
        names = _feature_names(catalog_features)
        if "business_unit" in dimensions:
            return self._business_unit_plan(question, dimensions, metrics, names)
        if "service_type" in dimensions:
            return self._service_plan(question, route, dimensions, metrics, names)
        if "customer_state" in dimensions:
            return self._state_plan(question, route, dimensions, metrics, names)
        if dimensions == ["window"]:
            return self._window_plan(question, route, metrics, names)
        if dimensions == ["snapshot_date"]:
            return self._physical_plan(route, metrics, catalog_features)
        return BreakdownDecision(
            clarifying_question="Tổ hợp breakdown này chưa có mapping feature hợp lệ.",
            options=self.options_for(route.business_unit),
            missing_slot="breakdown_dimension",
        )

    def _business_unit_plan(
        self, question: str, dimensions: list[str],
        metrics: list[dict[str, str]], names: set[str],
    ) -> BreakdownDecision:
        windows = _requested_windows(question)
        if "window" in dimensions:
            windows = windows or ["l1m", "l3m", "l6m", "l12m", "all"]
        else:
            windows = [windows[0] if windows else "all"]
        spec = self._by_key["business_unit"]
        branches: list[dict[str, Any]] = []
        selected: set[str] = set()
        for window in windows:
            for member in spec.members:
                branch_metrics: list[dict[str, str]] = []
                for metric in metrics:
                    if metric["key"] == "customer_count":
                        feature = member["population_flag"].format(window=window)
                    elif metric["key"] == "total_revenue":
                        feature = member["spend"].format(window=window)
                    else:
                        return self._unsupported_metric("business unit")
                    if feature not in names:
                        continue
                    selected.add(feature)
                    branch_metrics.append({**metric, "feature": feature})
                if len(branch_metrics) == len(metrics):
                    labels = {"business_unit": member["label"]}
                    if "window" in dimensions:
                        labels["window"] = window
                    branches.append({"labels": labels, "table": CROSS_TABLE, "metrics": branch_metrics})
        return self._finish(dimensions, metrics, windows, spec.strategy, "not_applicable", branches, selected)

    def _service_plan(
        self, question: str, route: RouteDecision, dimensions: list[str],
        metrics: list[dict[str, str]], names: set[str],
    ) -> BreakdownDecision:
        if any(metric["key"] != "transaction_count" for metric in metrics):
            return self._unsupported_metric("loại dịch vụ/sản phẩm")
        unit = (route.business_unit or "").upper()
        spec = self._by_key["service_type"]
        members = [member for member in spec.members if member["business_unit"] == unit]
        windows = _requested_windows(question)
        supported = ["l1w", "l2w"] if unit == "GSM" else ["l12m"]
        if "window" in dimensions:
            windows = windows or supported
        elif not windows:
            return BreakdownDecision(
                clarifying_question="Bạn muốn breakdown dịch vụ trong cửa sổ thời gian nào?",
                options=tuple(
                    {"value": window, "label": window} for window in supported
                ),
                missing_slot="window",
            )
        else:
            windows = [windows[0]]
        branches: list[dict[str, Any]] = []
        selected: set[str] = set()
        for window in windows:
            for member in members:
                feature = member["count"].format(window=window)
                if feature not in names:
                    continue
                selected.add(feature)
                labels = {"service_type": member["label"]}
                if "window" in dimensions:
                    labels["window"] = window
                branches.append({
                    "labels": labels, "table": member["table"],
                    "metrics": [{**metrics[0], "feature": feature}],
                })
        return self._finish(dimensions, metrics, windows, spec.strategy, "not_applicable", branches, selected)

    def _state_plan(
        self, question: str, route: RouteDecision, dimensions: list[str],
        metrics: list[dict[str, str]], names: set[str],
    ) -> BreakdownDecision:
        unit = (route.business_unit or "").upper()
        if unit not in {"VINFAST", "CROSS_BU"}:
            return BreakdownDecision(
                clarifying_question="Breakdown trạng thái hiện chỉ hỗ trợ VinFast hoặc dữ liệu cross-BU.",
                options=self.options_for(route.business_unit),
                missing_slot="business_unit",
            )
        semantics = (
            "independent" if _contains(question, _INDEPENDENT)
            else "exclusive" if _contains(question, _EXCLUSIVE)
            else None
        )
        if semantics is None:
            return BreakdownDecision(
                clarifying_question=(
                    "Các trạng thái có thể chồng lấn. Bạn muốn đếm nhóm độc lập "
                    "hay chia thành các nhóm loại trừ nhau?"
                ),
                options=(
                    {"value": "independent", "label": "Nhóm độc lập"},
                    {"value": "exclusive", "label": "Nhóm loại trừ"},
                ),
                missing_slot="group_semantics",
            )
        spec = self._by_key["customer_state"]
        members = [member for member in spec.members if member["business_unit"] == unit]
        windows = _requested_windows(question)
        if "window" in dimensions:
            windows = windows or (["l1m", "l3m", "l6m", "l12m", "all"] if unit == "CROSS_BU" else ["l1m", "l3m", "l6m", "l12m"])
        else:
            windows = [windows[0] if windows else ("all" if unit == "CROSS_BU" else "l12m")]
        branches: list[dict[str, Any]] = []
        selected: set[str] = set()
        for window in windows:
            resolved = [
                {
                    **member,
                    "resolved_flag": member["flag"].format(window=window),
                }
                for member in members
                if member["flag"].format(window=window) in names
            ]
            combinations = (
                [(member["label"], [(member["resolved_flag"], True)]) for member in resolved]
                if semantics == "independent"
                else [
                    (
                        " + ".join(
                            member["label"] for member, enabled in zip(resolved, bits) if enabled
                        ) or "Neither",
                        [(member["resolved_flag"], enabled) for member, enabled in zip(resolved, bits)],
                    )
                    for bits in itertools.product((False, True), repeat=len(resolved))
                ]
            )
            for label, conditions in combinations:
                branch_metrics: list[dict[str, str]] = []
                for metric in metrics:
                    if metric["key"] == "customer_count":
                        feature = conditions[0][0]
                    elif metric["key"] == "total_revenue":
                        feature = (
                            f"combined_spend_{window}" if unit == "CROSS_BU"
                            else f"txn_completed_amount_sum_{window}"
                        )
                    else:
                        return self._unsupported_metric("trạng thái khách hàng")
                    if feature not in names:
                        continue
                    selected.add(feature)
                    branch_metrics.append({**metric, "feature": feature})
                selected.update(flag for flag, _ in conditions)
                if len(branch_metrics) == len(metrics):
                    labels = {"customer_state": label}
                    if "window" in dimensions:
                        labels["window"] = window
                    branches.append({
                        "labels": labels,
                        "table": CROSS_TABLE if unit == "CROSS_BU" else VF_TABLE,
                        "metrics": branch_metrics,
                        "conditions": [
                            {"feature": feature, "equals": enabled}
                            for feature, enabled in conditions
                        ],
                    })
        return self._finish(dimensions, metrics, windows, spec.strategy, semantics, branches, selected)

    def _window_plan(
        self, question: str, route: RouteDecision,
        metrics: list[dict[str, str]], names: set[str],
    ) -> BreakdownDecision:
        unit = (route.business_unit or "").upper()
        table = {"GSM": GSM_TABLE, "VINFAST": VF_TABLE, "CROSS_BU": CROSS_TABLE}.get(unit)
        if not table:
            return BreakdownDecision(
                clarifying_question="Bạn muốn xem cửa sổ thời gian của GSM, VinFast hay cả hai?",
                options=(
                    {"value": "GSM", "label": "GSM"},
                    {"value": "VinFast", "label": "VinFast"},
                    {"value": "Cả hai", "label": "Cả hai"},
                ),
                missing_slot="business_unit",
            )
        windows = _requested_windows(question)
        windows = windows or list(_WINDOWS)
        branches: list[dict[str, Any]] = []
        selected: set[str] = set()
        for window in windows:
            branch_metrics: list[dict[str, str]] = []
            for metric in metrics:
                feature = self._window_feature(unit, metric["key"], window)
                if not feature or feature not in names:
                    continue
                selected.add(feature)
                branch_metrics.append({**metric, "feature": feature})
            if len(branch_metrics) == len(metrics):
                branches.append({
                    "labels": {"window": window}, "table": table, "metrics": branch_metrics,
                })
        return self._finish(["window"], metrics, windows, "pivot_feature", "not_applicable", branches, selected)

    @staticmethod
    def _window_feature(unit: str, metric: str, window: str) -> str | None:
        if metric == "total_revenue":
            return {
                "GSM": f"completed_original_price_sum_{window}",
                "VINFAST": f"txn_completed_amount_sum_{window}",
                "CROSS_BU": f"combined_spend_{window}",
            }.get(unit)
        if metric == "transaction_count":
            return {
                "GSM": f"finished_txn_count_{window}",
                "VINFAST": f"txn_completed_count_{window}",
            }.get(unit)
        if metric == "customer_count" and unit == "CROSS_BU":
            return f"is_cross_bu_active_{window}"
        return None

    def _physical_plan(
        self, route: RouteDecision, metrics: list[dict[str, str]], features: Iterable[Any],
    ) -> BreakdownDecision:
        unit = (route.business_unit or "").upper()
        table = {"GSM": GSM_TABLE, "VINFAST": VF_TABLE, "CROSS_BU": CROSS_TABLE}.get(unit)
        candidates = [
            feature for feature in features
            if str(getattr(feature, "table", None) or feature.get("table")) == table
        ]
        if not table or not candidates:
            return self._unsupported_metric("snapshot_date")
        metric = metrics[0]
        tokens = {
            "total_revenue": ("spend", "amount_sum", "original_price_sum"),
            "transaction_count": ("txn_count",),
        }.get(metric["key"], ())
        feature = next((
            str(getattr(item, "name", None) or item.get("name"))
            for item in candidates
            if any(token in str(getattr(item, "name", None) or item.get("name")) for token in tokens)
        ), None)
        if feature is None:
            return self._unsupported_metric("snapshot_date")
        plan = BreakdownPlan(
            dimensions=["snapshot_date"], members={"snapshot_date": []},
            metrics=[{**metric, "feature": feature}], strategy="physical_column",
            expected_columns=["snapshot_date", metric["alias"]], estimated_groups=_max_groups(),
        )
        return BreakdownDecision(plan=plan)

    @staticmethod
    def _unsupported_metric(dimension: str) -> BreakdownDecision:
        return BreakdownDecision(
            clarifying_question=f"Chỉ số được hỏi chưa có mapping hợp lệ theo {dimension}.",
            options=(
                {"value": "Số lượng khách hàng", "label": "Số lượng khách hàng"},
                {"value": "Tổng doanh thu", "label": "Tổng doanh thu"},
                {"value": "Số giao dịch", "label": "Số giao dịch"},
            ),
            missing_slot="metric",
        )

    @staticmethod
    def _finish(
        dimensions: list[str], metrics: list[dict[str, str]], windows: list[str],
        strategy: str, semantics: str, branches: list[dict[str, Any]], selected: set[str],
    ) -> BreakdownDecision:
        if not branches:
            return BreakdownPlanner._unsupported_metric("dimension đã chọn")
        limit = _max_groups()
        if len(branches) > limit:
            return BreakdownDecision(
                clarifying_question=(
                    f"Breakdown tạo {len(branches)} nhóm, vượt giới hạn {limit}. "
                    "Hãy chọn ít member/window hơn."
                ),
                missing_slot="breakdown_dimension",
            )
        members = {
            dimension: sorted({str(branch["labels"][dimension]) for branch in branches})
            for dimension in dimensions
        }
        plan = BreakdownPlan(
            dimensions=dimensions, members=members,
            metrics=[{**metric, "features": sorted(
                {
                    item["feature"] for branch in branches for item in branch["metrics"]
                    if item["alias"] == metric["alias"]
                }
            )} for metric in metrics],
            window=windows[0] if len(windows) == 1 else None,
            strategy=strategy, group_semantics=semantics,
            expected_columns=[*dimensions, *(metric["alias"] for metric in metrics)],
            estimated_groups=len(branches), branches=branches,
        )
        # selected is intentionally resolved before construction; retain it in metrics/branches only.
        _ = selected
        return BreakdownDecision(plan=plan)


def selected_features(plan: BreakdownPlan) -> list[str]:
    return sorted({
        metric["feature"]
        for branch in plan.branches
        for metric in branch.get("metrics", [])
    } | {
        condition["feature"]
        for branch in plan.branches
        for condition in branch.get("conditions", [])
    } | {
        feature
        for metric in plan.metrics
        for feature in metric.get("features", [metric.get("feature")])
        if feature
    })


def compile_breakdown(plan: BreakdownPlan, intent: IntentType) -> GenerationResponse:
    if plan.strategy == "physical_column":
        raise ValueError("physical_column breakdown must be generated by the guarded LLM path.")
    selects: list[str] = []
    for ordinal, branch in enumerate(plan.branches):
        projections = [
            f"{ordinal} AS breakdown_ordinal",
            *(
                f"{_safe_literal(branch['labels'][dimension])} AS {_safe_identifier(dimension, 'dimension')}"
                for dimension in plan.dimensions
            ),
        ]
        conditions = branch.get("conditions", [])
        predicate = " AND ".join(
            f"{_safe_identifier(item['feature'], 'feature')} IS {'TRUE' if item['equals'] else 'FALSE'}"
            for item in conditions
        )
        for metric in branch["metrics"]:
            feature = _safe_identifier(metric["feature"], "feature")
            aggregate = metric["aggregate"]
            if aggregate == "count_true":
                condition = predicate or f"{feature} IS TRUE"
                expression = f"COUNT(*) FILTER (WHERE {condition})"
            elif aggregate in {"sum", "avg", "min", "max"}:
                expression = f"{aggregate.upper()}({feature})"
                if predicate:
                    expression += f" FILTER (WHERE {predicate})"
            else:
                raise ValueError(f"Unsupported breakdown aggregate: {aggregate}")
            projections.append(
                f"{expression} AS {_safe_identifier(metric['alias'], 'metric alias')}"
            )
        table = _safe_table(branch["table"])
        selects.append(
            "SELECT " + ", ".join(projections)
            + f" FROM {table}"
            + f" WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM {table})"
        )
    # `UNION ALL` KHÔNG bảo đảm thứ tự dòng: cùng một câu hỏi có thể ra thứ tự khác
    # giữa hai lần chạy, và l12m vẽ trước l1m. Thứ tự nhánh đã đúng nghĩa (theo
    # `_WINDOWS` rồi theo member), nên gắn ordinal ẩn rồi sort ngoài — không thêm cột
    # vào kết quả. Bọc thêm một subquery, không phải CTE, để không tốn quota
    # `sql_max_ctes`.
    columns = ", ".join(
        _safe_identifier(name, "column") for name in plan.expected_columns
    )
    union = " UNION ALL ".join(selects)
    return GenerationResponse(
        sql=f"SELECT {columns} FROM ({union}) AS breakdown ORDER BY breakdown_ordinal",
        selected_features=selected_features(plan),
        intent=intent,
        assumptions=[],
        confidence=0.95,
    )


def clarification_option(value: str, label: str) -> dict[str, str]:
    return {"value": value, "label": label}
