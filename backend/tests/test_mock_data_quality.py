from __future__ import annotations

from scripts.generate_mock_data import build_features, data_quality_errors, generate_raw


def test_mock_data_is_repeatable_and_passes_quality_gate():
    first = generate_raw()
    assert first == generate_raw()
    customers, _dates, trips, orders = first
    gsm, vinfast = build_features(customers, trips, orders)
    assert data_quality_errors(customers, trips, orders, gsm, vinfast) == []
