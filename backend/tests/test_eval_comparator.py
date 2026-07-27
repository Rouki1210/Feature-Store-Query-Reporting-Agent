"""Comparator: order- & column-name-insensitive + float tolerance (offline)."""
import decimal

from app.eval.comparator import result_sets_equal


def test_recall_at_five_counts_each_expected_feature():
    from app.eval.evaluator import _recall_at_5

    assert _recall_at_5({"a", "b"}, ["a", "x", "b"]) == 1.0
    assert _recall_at_5({"a", "b"}, ["a", "x", "y", "z", "q"]) == 0.5

BASE = [[1, 100.0], [2, 200.0], [3, 300.0]]


def test_row_order_insensitive():
    assert result_sets_equal(BASE, [[3, 300.0], [1, 100.0], [2, 200.0]])


def test_column_order_insensitive():
    assert result_sets_equal(BASE, [[100.0, 1], [200.0, 2], [300.0, 3]])


def test_float_tolerance():
    assert result_sets_equal(BASE, [[1, 100.004], [2, 199.997], [3, 300.002]])


def test_decimal_equals_float():
    d = [[1, decimal.Decimal("100.0")], [2, decimal.Decimal("200.0")], [3, decimal.Decimal("300.0")]]
    assert result_sets_equal(BASE, d)


def test_different_values_not_equal():
    assert not result_sets_equal(BASE, [[1, 100.0], [2, 200.0], [3, 999.0]])


def test_different_rowcount_not_equal():
    assert not result_sets_equal(BASE, BASE[:2])


def test_different_colcount_not_equal():
    assert not result_sets_equal(BASE, [[1, 100.0, 0], [2, 200.0, 0], [3, 300.0, 0]])


def test_empty_both_equal():
    assert result_sets_equal([], [])


def test_null_values_handled():
    a = [[1, None], [2, 5.0]]
    assert result_sets_equal(a, [[2, 5.0], [1, None]])
    assert not result_sets_equal(a, [[1, 0.0], [2, 5.0]])
