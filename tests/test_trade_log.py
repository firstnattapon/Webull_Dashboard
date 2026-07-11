from __future__ import annotations

import pandas as pd

from trade_log import (
    TRADE_PRICE_COLUMNS,
    find_trade_price_column,
    trade_price_series,
)


def normalize(rows: list[dict]) -> pd.DataFrame:
    """Flatten Firestore documents exactly like the dashboard does."""
    return pd.json_normalize(rows, sep="_")


def test_nested_market_state_last_price_is_found():
    trades = normalize([
        {
            "created_at": 2,
            "status": "ORDER_SUBMITTED",
            "market_state": {"quantity": 1.0, "last_price": 101.5},
        },
        {
            "created_at": 1,
            "status": "PASS_THRESHOLD",
            "market_state": {"quantity": 1.0, "last_price": 100.0},
        },
    ])

    column = find_trade_price_column(trades)

    assert column == "market_state_last_price"
    assert trade_price_series(trades, column) == [100.0, 101.5]


def test_top_level_last_price_takes_priority_over_nested():
    trades = normalize([
        {"created_at": 1, "last_price": 100.0, "market_state": {"last_price": 999.0}},
    ])

    assert find_trade_price_column(trades) == "last_price"


def test_unknown_nesting_prefix_is_found_by_suffix():
    trades = normalize([
        {"created_at": 1, "order_result": {"fill_price": 55.0}},
    ])

    assert find_trade_price_column(trades) == "order_result_fill_price"


def test_column_without_usable_prices_is_skipped():
    trades = normalize([
        {"created_at": 1, "price": None, "market_state": {"last_price": 100.0}},
    ])

    assert find_trade_price_column(trades) == "market_state_last_price"


def test_rows_without_market_state_do_not_break_extraction():
    trades = normalize([
        {"created_at": 2, "status": "ERROR", "error_message": "boom"},
        {"created_at": 1, "status": "ORDER_SUBMITTED", "market_state": {"last_price": 100.0}},
    ])

    column = find_trade_price_column(trades)

    assert column == "market_state_last_price"
    assert trade_price_series(trades, column) == [100.0]


def test_no_price_column_returns_none():
    trades = normalize([{"created_at": 1, "status": "ERROR"}])

    assert find_trade_price_column(trades) is None


def test_series_is_chronological_and_filters_invalid_values():
    trades = pd.DataFrame({
        "created_at": [3, 1, 2],
        "last_price": ["101.5", None, -5],
    })

    assert trade_price_series(trades, "last_price") == [101.5]


def test_known_columns_cover_the_bot_log_schema():
    assert "last_price" in TRADE_PRICE_COLUMNS
    assert "market_state_last_price" in TRADE_PRICE_COLUMNS
