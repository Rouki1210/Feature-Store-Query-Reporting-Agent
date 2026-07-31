"""Backend quyết định kết quả nên hiển thị như thế nào.

Trước đây frontend tự đoán (`chartable`/`scalar` trong `lib/table.ts`). Hai nơi cùng
phán quyết là cách sinh ra bug im lặng — y như vụ `SLOT_CHOICES` mời sai slot. Backend
biết `group_semantics` của breakdown, frontend không.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from app.models.schemas import QueryResult

_NUMBER = (int, float, Decimal)
_SHAPES = ("scalar", "time_series", "category", "table")


def _is_number(value) -> bool:
    return isinstance(value, _NUMBER) and not isinstance(value, bool)


def _column_is(result: QueryResult, index: int, predicate) -> bool:
    """Cột thuần một kiểu, bỏ qua NULL — NULL là ngữ nghĩa hợp lệ ở feature store."""
    values = [row[index] for row in result.rows if row[index] is not None]
    return bool(values) and all(predicate(value) for value in values)


def classify_result_shape(
    result: QueryResult | None, *, group_semantics: str | None = None
) -> str:
    if result is None or not result.rows or not result.columns:
        return "table"
    columns = len(result.columns)
    if result.row_count == 1 and columns == 1 and _is_number(result.rows[0][0]):
        return "scalar"
    if columns < 2:
        return "table"
    numeric_tail = all(
        _column_is(result, index, _is_number) for index in range(1, columns)
    )
    if not numeric_tail:
        return "table"
    if _column_is(result, 0, lambda v: isinstance(v, (date, datetime))):
        return "time_series"
    # Nhóm chồng lấn (một khách có thể thuộc nhiều nhóm) ⇒ biểu đồ gợi ý sai
    # "phần của tổng thể". Bảng giữ đúng ngữ nghĩa. Quyết theo group_semantics chứ
    # không theo số cột: 1 chiều × 2 metric vẫn vẽ được grouped bar.
    if group_semantics == "independent":
        return "table"
    if _column_is(result, 0, lambda v: isinstance(v, str)):
        return "category"
    return "table"
