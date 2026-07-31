from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from app.agent.contracts import NarrationInput
from app.agent.llm_client import JSONLLM

_NUMBER = (int, float, Decimal)


def _fmt(value) -> str:
    """Số kiểu Việt Nam; số lớn rút gọn để câu tóm tắt còn đọc được."""
    if isinstance(value, bool) or not isinstance(value, _NUMBER):
        return str(value)
    number = float(value)
    for limit, suffix, scale in ((1e9, " tỷ", 1e9), (1e6, " triệu", 1e6), (1e3, " nghìn", 1e3)):
        if abs(number) >= limit:
            return f"{number / scale:,.1f}".replace(",", "_").replace(".", ",").replace("_", ".") + suffix
    if number == int(number):
        return f"{int(number):,}".replace(",", ".")
    return f"{number:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


def _is_identifier(name: str) -> bool:
    """`customer_id` là số nhưng KHÔNG phải chỉ số — tóm tắt nó ra câu vô nghĩa."""
    lowered = name.lower()
    return lowered.endswith("_id") or lowered in {"id", "customer_id", "order_id", "vehicle_id"}


def _numeric_columns(result) -> list[tuple[int, str]]:
    return [
        (index, name)
        for index, name in enumerate(result.columns)
        if not _is_identifier(name)
        and any(
            isinstance(row[index], _NUMBER) and not isinstance(row[index], bool)
            for row in result.rows
        )
    ]


def _label_column(result) -> int | None:
    """Cột định danh để nêu tên nhóm/khách trong câu tóm tắt."""
    for index, name in enumerate(result.columns):
        if name.lower() in {"customer_id", "business_unit", "service_type", "window",
                            "customer_state", "snapshot_date", "dominant_business_unit_l1m"}:
            return index
    for index, _ in enumerate(result.columns):
        if all(isinstance(row[index], (str, date, datetime)) for row in result.rows):
            return index
    return None


def _describe_scalar(result) -> str:
    value = result.rows[0][0]
    return f"{result.columns[0]} = {_fmt(value)}."


def _describe_ranking(result, numeric: list[tuple[int, str]], label: int) -> str:
    index, name = numeric[0]
    values = [row[index] for row in result.rows if isinstance(row[index], _NUMBER)]
    if not values:
        return ""
    # Dòng đầu chỉ là "dẫn đầu" khi SQL đã sắp theo chính chỉ số đó; nếu không thì
    # nêu dòng cao nhất thật, tránh khẳng định thứ hạng sai.
    top = max(result.rows, key=lambda row: float(row[index]) if isinstance(row[index], _NUMBER) else float("-inf"))
    lead = "Cao nhất" if top is not result.rows[0] else "Dẫn đầu"
    parts = [f"{lead} là {top[label]} với {name} = {_fmt(top[index])}"]
    if len(values) > 1:
        total = sum(float(v) for v in values)
        parts.append(f"trung bình {_fmt(total / len(values))}")
        # Tỉ trọng chỉ có nghĩa khi có đủ nhóm để so; 2 nhóm thì đọc thẳng hai số.
        share = float(top[index]) / total if total else 0
        if len(values) >= 3 and share >= 0.2:
            parts.append(f"riêng nhóm đầu chiếm {share:.0%}")
    return "; ".join(parts) + "."


def _describe_spread(result, numeric: list[tuple[int, str]]) -> str:
    """Nhiều cột số mà không có thứ hạng rõ ⇒ nêu khoảng giá trị từng cột."""
    pieces = []
    for index, name in numeric[:3]:
        values = [float(row[index]) for row in result.rows if isinstance(row[index], _NUMBER)]
        if not values:
            continue
        if len(values) == 1:
            pieces.append(f"{name} = {_fmt(values[0])}")
        else:
            pieces.append(
                f"{name} từ {_fmt(min(values))} đến {_fmt(max(values))}"
                f" (trung bình {_fmt(sum(values) / len(values))})"
            )
    return "; ".join(pieces) + "." if pieces else ""


def deterministic_answer(inp: NarrationInput) -> str:
    """Tóm tắt NGẮN, tính thẳng từ result set — không gọi LLM nên không thể bịa số.

    Cùng nguyên tắc với reporter (CLAUDE.md §4): thống kê quyết định nội dung, phần
    ngôn ngữ chỉ diễn đạt lại. Ở đây thậm chí không có LLM nào tham gia.
    """
    result = inp.result
    if result.row_count == 0:
        return "Không có dữ liệu phù hợp với điều kiện truy vấn."

    numeric = _numeric_columns(result)
    label = _label_column(result)
    if result.row_count == 1 and len(result.columns) == 1:
        summary = _describe_scalar(result)
    elif numeric and label is not None and result.row_count > 1:
        summary = _describe_ranking(result, numeric, label) or _describe_spread(result, numeric)
    elif numeric:
        summary = _describe_spread(result, numeric)
    else:
        summary = f"{result.row_count} dòng, các cột: {', '.join(result.columns)}."

    notes: list[str] = []
    if result.row_count > 1 and f"{result.row_count} dòng" not in summary:
        notes.append(f"{result.row_count} dòng")
    if result.truncated:
        notes.append("đã chạm giới hạn dòng nên chưa phải toàn bộ")
    # Cảnh báo độ phủ do pipeline._coverage() phát MỘT LẦN (ngưỡng `coverage_low_ratio`).
    # Nhắc lại ở đây là chỗ thứ ba nói cùng một chuyện — user sẽ ngừng đọc cảnh báo.
    return summary + (f" ({'; '.join(notes)})" if notes else "")


class OptionalLLMNarrator:
    """Narrates only validated result data; callers must retain deterministic fallback."""

    def __init__(self, client: JSONLLM):
        self.client = client

    def __call__(self, inp: NarrationInput) -> str:
        payload = self.client.complete_json(
            "You narrate validated analytics results in concise Vietnamese. "
            "Return JSON only: {\"answer_vi\": \"...\"}. Never invent values or claim ownership.",
            inp.model_dump_json(ensure_ascii=False),
        )
        answer = payload.get("answer_vi")
        if not isinstance(answer, str) or not answer.strip():
            raise ValueError("Narrator không trả answer_vi hợp lệ.")
        return answer.strip()
