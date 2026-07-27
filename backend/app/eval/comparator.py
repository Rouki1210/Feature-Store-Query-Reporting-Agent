"""So sánh 2 result set order- & column-name-insensitive (CLAUDE.md mục 8).

Execution accuracy: gold SQL và SQL agent sinh có thể đặt tên/thứ tự cột khác
nhau nhưng cùng dữ liệu ⇒ coi là bằng. Chỉ phụ thuộc stdlib.
"""
from __future__ import annotations

import decimal
from typing import Any

Row = list[Any]


def _num(v: Any) -> Any:
    if isinstance(v, decimal.Decimal):
        return float(v)
    return v


def _canonical(rows: list[Row], float_abs: float) -> tuple:
    """Bảng → dạng chuẩn bất biến theo thứ tự dòng VÀ tên/thứ tự cột.

    Cách làm: chuyển sang các CỘT, làm tròn float theo dung sai, sort các cột
    theo 'chữ ký' (tuple giá trị đã sort) để bỏ qua thứ tự/tên cột, rồi ghép lại
    thành các dòng và sort dòng.

    ponytail: align cột bằng value-signature là heuristic — 2 cột có cùng
    multiset giá trị có thể hoán đổi mà vẫn 'bằng'. Đủ cho eval; nâng lên
    permutation-match nếu đo sai.
    """
    if not rows:
        return ()
    width = len(rows[0])

    def norm(v: Any) -> Any:
        v = _num(v)
        if isinstance(v, float):
            # Quy về bội số của float_abs để so có dung sai mà vẫn hashable/sort được.
            return round(v / float_abs) if float_abs else v
        return v

    columns = [[norm(row[i]) for row in rows] for i in range(width)]
    # Sort mỗi cột để lấy chữ ký (dùng repr tránh lỗi so None vs số).
    signed = sorted(columns, key=lambda col: [repr(x) for x in sorted(col, key=repr)])
    canon_rows = sorted(
        (tuple(signed[c][r] for c in range(width)) for r in range(len(rows))),
        key=repr,
    )
    return tuple(canon_rows)


def result_sets_equal(
    gold_rows: list[Row],
    gen_rows: list[Row],
    *,
    float_abs: float = 0.01,
) -> bool:
    """True nếu 2 bảng cùng dữ liệu, bỏ qua thứ tự dòng và tên/thứ tự cột."""
    if gold_rows and gen_rows and len(gold_rows[0]) != len(gen_rows[0]):
        return False
    return _canonical(gold_rows, float_abs) == _canonical(gen_rows, float_abs)


if __name__ == "__main__":  # self-check
    a = [[1, 100.0], [2, 200.0]]
    assert result_sets_equal(a, [[2, 200.0], [1, 100.0]])          # đổi thứ tự dòng
    assert result_sets_equal(a, [[100.0, 1], [200.0, 2]])          # đổi thứ tự cột
    assert result_sets_equal(a, [[1, 100.004], [2, 199.997]])      # dung sai float
    assert not result_sets_equal(a, [[1, 100.0], [2, 999.0]])      # khác giá trị
    assert not result_sets_equal(a, [[1, 100.0]])                  # khác số dòng
    assert not result_sets_equal(a, [[1, 100.0, 5], [2, 200.0, 6]])  # khác số cột
    print("comparator self-check OK")
