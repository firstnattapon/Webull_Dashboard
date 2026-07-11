"""Trade-log price extraction for the Shannon Demon dashboard.

The bot (firstnattapon/webull) logs each rebalance with the executed price
at the top level (``last_price``) and nested under ``market_state``. Older
documents carry only the nested form, which ``pd.json_normalize(sep="_")``
flattens to ``market_state_last_price`` — so the lookup accepts the exact
names first and any flattened ``*_<name>`` column as a fallback.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from manual_tools import rebalancing_cashflow_from_prices

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


# ---------------------------------------------------------------------------
# Grouped, human-readable trade-log table
# ---------------------------------------------------------------------------
#
# The raw log flattens to ~20 columns with three exact duplicates of every
# equation output (baseline_pnl / decision_baseline / decision_baseline_pnl,
# decision_rebalance / decision_rebalance_amount, decision_order_qty /
# decision_order_quantity). ``build_trade_log_display`` renames the useful
# fields to Thai labels and lays them out under three grouped headers:
#
#   ① Logged DNA          — what the bot actually recorded per tick
#   ② เส้นอ้างอิงทางทฤษฎี   — Rₙ = Fix_c × ln(Pₙ / P₀)
#   ③ เส้น Rebalancing จริง — Aₙ (สะสม), ΔAₙ (ต่อสเต็ป), Eₙ = Aₙ − Rₙ
#
# Groups ② and ③ are recomputed from the logged price series with the same
# Fix_c / P₀ the guide charts use, so the table and the charts always agree.

GROUP_LOGGED = "① Logged DNA (บันทึกจากบอท)"
GROUP_REFERENCE = "② เส้นอ้างอิงทางทฤษฎี · Rₙ = Fix_c·ln(Pₙ/P₀)"
GROUP_REBALANCED = "③ เส้น Rebalancing จริง · Aₙ, Eₙ"

# (source column, readable label). The price column is resolved at runtime
# because it may be last_price, market_state_last_price, or a suffix match.
_LOGGED_LABELS: tuple[tuple[str, str], ...] = (
    ("created_at", "เวลา (UTC)"),
    ("symbol", "สินทรัพย์"),
    ("status", "สถานะ"),
    ("dna_step", "DNA step"),
    ("dna_signal", "DNA signal"),
    ("market_state_quantity", "จำนวนถือครอง (หุ้น)"),
    ("decision_action", "คำสั่ง"),
    ("decision_side", "ฝั่ง"),
    ("decision_reason", "เหตุผล"),
    ("decision_order_qty", "จำนวนสั่ง (หุ้น)"),
    ("decision_value_now_usd", "มูลค่าพอร์ต (USD)"),
    ("decision_rebalance", "ส่วนต่างเป้าหมาย (USD)"),
)
_PRICE_LABEL = "ราคา Pₙ (USD)"
# Logged USD amounts carry float noise (e.g. 11.311520399999836); round the
# money-valued logged columns so the table reads cleanly.
_ROUNDED_LOGGED_LABELS = frozenset({"มูลค่าพอร์ต (USD)", "ส่วนต่างเป้าหมาย (USD)"})


def build_trade_log_display(
    trades: pd.DataFrame,
    price_column: str,
    fix_c: float,
    p0: float,
) -> pd.DataFrame:
    """Return a newest-first table with three grouped, renamed column blocks.

    Cumulative figures (group ③) must be summed oldest-first, so the frame is
    ordered chronologically for the maths and reversed for display. Rows
    without a usable price (e.g. ERROR ticks) keep their logged fields and
    show blank reference / rebalancing values.
    """
    ordered = trades
    if "created_at" in trades.columns:
        ordered = trades.sort_values("created_at")
    ordered = ordered.reset_index(drop=True)

    prices = pd.to_numeric(ordered.get(price_column), errors="coerce")
    valid = prices.notna() & (prices > 0)

    reference = pd.Series(np.nan, index=ordered.index)
    delta_actual = pd.Series(np.nan, index=ordered.index)
    actual = pd.Series(np.nan, index=ordered.index)
    excess = pd.Series(np.nan, index=ordered.index)

    valid_prices = [float(price) for price in prices[valid]]
    if valid_prices:
        # rows[0] is the synthetic P₀ anchor; rows[1:] align to the priced ticks.
        cashflow = rebalancing_cashflow_from_prices(valid_prices, fix_c, p0)[1:]
        for position, row in zip(ordered.index[valid], cashflow):
            reference[position] = round(row["ln_reference"], 2)
            delta_actual[position] = round(row["delta_actual"], 2)
            actual[position] = round(row["actual_cumulative"], 2)
            excess[position] = round(row["excess"], 2)

    columns: dict[tuple[str, str], Any] = {}

    def add_logged(source: str, label: str) -> None:
        if source not in ordered.columns:
            return
        series = ordered[source]
        if label in _ROUNDED_LOGGED_LABELS:
            series = pd.to_numeric(series, errors="coerce").round(2)
        columns[(GROUP_LOGGED, label)] = series.to_numpy()

    for source, label in _LOGGED_LABELS:
        add_logged(source, label)
        if source == "dna_signal":  # slot the price right after the DNA fields
            add_logged(price_column, _PRICE_LABEL)

    columns[(GROUP_REFERENCE, "Rₙ อ้างอิง (USD)")] = reference.to_numpy()
    columns[(GROUP_REBALANCED, "ΔAₙ ต่อสเต็ป (USD)")] = delta_actual.to_numpy()
    columns[(GROUP_REBALANCED, "Aₙ สะสม (USD)")] = actual.to_numpy()
    columns[(GROUP_REBALANCED, "Eₙ ส่วนเกินสะสม (USD)")] = excess.to_numpy()

    display = pd.DataFrame(columns)
    display.columns = pd.MultiIndex.from_tuples(display.columns)
    # Chronological order was oldest-first for the cumulative sum; show newest
    # first, matching the log convention.
    return display.iloc[::-1].reset_index(drop=True)
