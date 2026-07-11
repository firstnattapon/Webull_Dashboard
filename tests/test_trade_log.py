from __future__ import annotations

import pandas as pd

from manual_tools import rebalancing_cashflow_from_prices
from trade_log import (
    GROUP_LOGGED,
    GROUP_REBALANCED,
    GROUP_REFERENCE,
    TRADE_PRICE_COLUMNS,
    build_trade_log_display,
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


# ---------------------------------------------------------------------------
# build_trade_log_display
# ---------------------------------------------------------------------------

def sample_log() -> pd.DataFrame:
    """Two priced ticks, oldest-first prices 100 then 110, flattened."""
    return normalize([
        {
            "created_at": "2026-07-10T19:00:00Z",
            "symbol": "AAPL",
            "strategy_id": "SHANNON_DEMON_DNA",
            "state_document": "SHANNON_DEMON_DNA_SMR",
            "status": "ORDER_SUBMITTED",
            "dna_step": 1,
            "dna_signal": 1,
            "baseline_pnl": 9.9,
            "decision": {
                "action": "BUY", "side": "BUY", "reason": "BELOW_TARGET",
                "order_qty": 0.5, "order_quantity": 0.5,
                "rebalance": 55.0, "rebalance_amount": 55.0,
                "value_now_usd": 1100.123456, "baseline_pnl": 9.9, "baseline": 9.9,
            },
            "market_state": {"quantity": 10.0, "last_price": 110.0},
        },
        {
            "created_at": "2026-07-10T18:00:00Z",
            "symbol": "AAPL",
            "strategy_id": "SHANNON_DEMON_DNA",
            "state_document": "SHANNON_DEMON_DNA_SMR",
            "status": "PASS_THRESHOLD",
            "dna_step": 0,
            "dna_signal": 1,
            "baseline_pnl": 0.0,
            "decision": {
                "action": "PASS", "side": None, "reason": "WITHIN_THRESHOLD",
                "order_qty": 0.0, "order_quantity": 0.0,
                "rebalance": 0.0, "rebalance_amount": 0.0,
                "value_now_usd": 1000.0, "baseline_pnl": 0.0, "baseline": 0.0,
            },
            "market_state": {"quantity": 10.0, "last_price": 100.0},
        },
    ])


def test_display_has_three_grouped_headers_in_order():
    display = build_trade_log_display(sample_log(), "market_state_last_price", 1500.0, 100.0)

    groups = list(dict.fromkeys(level0 for level0, _ in display.columns))
    assert groups == [GROUP_LOGGED, GROUP_REFERENCE, GROUP_REBALANCED]


def test_display_drops_duplicate_and_constant_columns():
    display = build_trade_log_display(sample_log(), "market_state_last_price", 1500.0, 100.0)

    labels = [label for _group, label in display.columns]
    # exact duplicates of equation outputs and constant metadata are gone
    for gone in ("decision_baseline", "decision_baseline_pnl", "decision_order_quantity",
                 "decision_rebalance_amount", "strategy_id", "state_document"):
        assert gone not in labels
    # readable price / dna fields are present
    assert (GROUP_LOGGED, "ราคา Pₙ (USD)") in display.columns
    assert (GROUP_LOGGED, "DNA step") in display.columns


def test_display_is_newest_first_and_matches_cashflow():
    display = build_trade_log_display(sample_log(), "market_state_last_price", 1500.0, 100.0)

    prices_col = display[(GROUP_LOGGED, "ราคา Pₙ (USD)")].tolist()
    assert prices_col == [110.0, 100.0]  # newest first

    # groups ② / ③ recompute from the oldest-first series [100, 110]
    cashflow = rebalancing_cashflow_from_prices([100.0, 110.0], 1500.0, 100.0)[1:]
    ref = display[(GROUP_REFERENCE, "Rₙ อ้างอิง (USD)")].tolist()
    actual = display[(GROUP_REBALANCED, "Aₙ สะสม (USD)")].tolist()
    excess = display[(GROUP_REBALANCED, "Eₙ ส่วนเกินสะสม (USD)")].tolist()
    # display is newest-first, cashflow is oldest-first -> reverse to compare
    assert ref == [round(cashflow[1]["ln_reference"], 2), round(cashflow[0]["ln_reference"], 2)]
    assert actual == [round(cashflow[1]["actual_cumulative"], 2), round(cashflow[0]["actual_cumulative"], 2)]
    assert excess == [round(cashflow[1]["excess"], 2), round(cashflow[0]["excess"], 2)]


def test_excess_equals_actual_minus_reference():
    display = build_trade_log_display(sample_log(), "market_state_last_price", 1500.0, 100.0)

    ref = display[(GROUP_REFERENCE, "Rₙ อ้างอิง (USD)")]
    actual = display[(GROUP_REBALANCED, "Aₙ สะสม (USD)")]
    excess = display[(GROUP_REBALANCED, "Eₙ ส่วนเกินสะสม (USD)")]
    assert (actual - ref).round(2).tolist() == excess.round(2).tolist()


def test_logged_money_columns_are_rounded():
    display = build_trade_log_display(sample_log(), "market_state_last_price", 1500.0, 100.0)

    value_now = display[(GROUP_LOGGED, "มูลค่าพอร์ต (USD)")].tolist()
    assert value_now == [1100.12, 1000.0]  # 1100.123456 rounded to 2dp


def test_rows_without_price_keep_logged_fields_and_blank_equations():
    trades = normalize([
        {"created_at": "2026-07-10T19:00:00Z", "status": "ERROR",
         "dna_step": 1, "error_message": "boom"},
        {"created_at": "2026-07-10T18:00:00Z", "status": "PASS_THRESHOLD",
         "dna_step": 0, "market_state": {"last_price": 100.0}},
    ])

    display = build_trade_log_display(trades, "market_state_last_price", 1500.0, 100.0)

    status = display[(GROUP_LOGGED, "สถานะ")].tolist()
    assert status == ["ERROR", "PASS_THRESHOLD"]  # both rows kept, newest first
    ref = display[(GROUP_REFERENCE, "Rₙ อ้างอิง (USD)")]
    assert pd.isna(ref.iloc[0])  # ERROR row has no price -> blank reference
    assert pd.notna(ref.iloc[1])  # priced row is filled


def test_price_column_is_resolved_dynamically():
    trades = normalize([
        {"created_at": "2026-07-10T18:00:00Z", "status": "OK",
         "last_price": 100.0, "quantity": 10.0},
    ])

    display = build_trade_log_display(trades, "last_price", 1500.0, 100.0)

    assert display[(GROUP_LOGGED, "ราคา Pₙ (USD)")].tolist() == [100.0]
