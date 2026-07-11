"""Trade-log price extraction for the Shannon Demon dashboard.

The bot (firstnattapon/webull) logs each rebalance with the executed price
at the top level (``last_price``) and nested under ``market_state``. Older
documents carry only the nested form, which ``pd.json_normalize(sep="_")``
flattens to ``market_state_last_price`` — so the lookup accepts the exact
names first and any flattened ``*_<name>`` column as a fallback.
"""

from __future__ import annotations

import pandas as pd

TRADE_PRICE_COLUMNS = (
    "last_price",
    "price",
    "market_state_last_price",
    "decision_last_price",
    "fill_price",
    "filled_price",
    "avg_price",
    "executed_price",
)


def trade_price_column_candidates(columns) -> list[str]:
    """Price-column candidates in priority order: exact names, then columns
    produced by flattening a nested payload (suffix ``_<name>``)."""
    candidates = [column for column in TRADE_PRICE_COLUMNS if column in columns]
    for name in TRADE_PRICE_COLUMNS:
        suffix = f"_{name}"
        for column in columns:
            if column.endswith(suffix) and column not in candidates:
                candidates.append(column)
    return candidates


def find_trade_price_column(trades: pd.DataFrame) -> str | None:
    """First candidate column holding at least one usable (positive) price."""
    for column in trade_price_column_candidates(trades.columns):
        if trade_price_series(trades, column):
            return column
    return None


def trade_price_series(trades: pd.DataFrame, price_column: str) -> list[float]:
    """Chronological positive prices from the (newest-first) trade log."""
    ordered = trades
    if "created_at" in trades.columns:
        ordered = trades.sort_values("created_at")
    prices = pd.to_numeric(ordered[price_column], errors="coerce")
    return [float(price) for price in prices if pd.notna(price) and price > 0]
