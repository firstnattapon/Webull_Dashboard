from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
import pytest

from manual_tools import (
    ConnectionSettings,
    WebullManualClient,
    WebullResponseError,
    build_market_order_payload,
    calculate_shannon_decision,
    calculate_rebalancing_curve,
    decode_dna,
    decode_number_stream,
    dna_summary,
    encode_dna,
    extract_last_price,
    extract_quantity,
    format_order_quantity,
    generate_client_order_id,
    response_json_or_raise,
    rebalancing_scenario_table,
    run_benchmark,
)


def test_default_uat_endpoint_and_production_endpoint():
    uat = ConnectionSettings("Test (UAT)", "a", "k", "s")
    prod = ConnectionSettings("Production", "a", "k", "s")

    assert uat.endpoint == "th-api.uat.webullbroker.com"
    assert not uat.is_production
    assert prod.endpoint == "api.webull.co.th"
    assert prod.is_production


def test_credentials_are_hidden_from_repr():
    settings = ConnectionSettings(
        "Test (UAT)", "account-secret", "key-secret", "app-secret"
    )
    rendered = repr(settings)
    assert "account-secret" not in rendered
    assert "key-secret" not in rendered
    assert "app-secret" not in rendered


def test_connection_settings_require_all_credentials():
    with pytest.raises(ValueError, match="App Secret"):
        ConnectionSettings("Test (UAT)", "account", "key", "").validate()


def test_known_dna_number_stream_and_output_are_stable():
    code = "26021034252903219354832053493"
    assert decode_number_stream(code) == [60, 10, 425, 90, 219, 548, 205, 493]
    output = decode_dna(code)
    assert output.dtype == np.int8
    assert output.tolist() == [
        1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 1,
        1, 0, 1, 1, 1, 1, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0,
        0, 1, 1, 0, 0, 0, 0, 0, 0, 1, 0, 1, 1, 1, 1, 1,
        0, 1, 0, 0, 0, 1, 1, 1, 1, 1, 1, 0, 1,
    ]


def test_encode_round_trip_and_summary():
    code = encode_dna(60, 10, [425, 90, 219, 548, 205, 493])
    summary = dna_summary(code)
    assert code == "26021034252903219354832053493"
    assert summary["length"] == 60
    assert summary["ones"] + summary["zeros"] == 60
    assert len(summary["sha256"]) == 64


@pytest.mark.parametrize("code,length", [("bypass:3", 3), ("[1,4]", 4)])
def test_bypass_dna(code, length):
    assert decode_dna(code).tolist() == [1] * length


def test_rebalancing_curve_models_constant_value_bands():
    rows = calculate_rebalancing_curve(1000.0, 100.0, 50.0, 50.0, 150.0, steps=3)
    assert [round(row["price"], 2) for row in rows] == [50.0, 100.0, 150.0]
    assert rows[1]["quantity"] == 10.0
    assert rows[1]["target_position_value"] == 1000.0
    assert rows[1]["band_low"] == 950.0
    assert rows[1]["band_high"] == 1050.0
    assert rows[0]["action"] == "BUY_ZONE"
    assert rows[1]["action"] == "ANCHOR"
    assert rows[2]["action"] == "SELL_ZONE"


def test_rebalancing_scenario_table_uses_logical_fix_c_rules():
    rows = rebalancing_scenario_table(10.0, 1000.0, 100.0, 50.0, 50.0, 150.0, steps=3)
    assert [row["action"] for row in rows] == ["BUY", "PASS", "SELL"]
    assert rows[0]["order_quantity"] == 10.0
    assert rows[2]["order_quantity"] == pytest.approx(500.0 / 150.0, abs=1e-5)


@pytest.mark.parametrize(
    ("quantity", "expected_action", "expected_qty"),
    [(10.0, "PASS", 0.0), (5.0, "BUY", 5.0), (20.0, "SELL", 10.0)],
)
def test_logical_fix_c_actions(quantity, expected_action, expected_qty):
    decision = calculate_shannon_decision(
        quantity, 100.0, 1000.0, 50.0, 100.0
    )
    assert decision.action == expected_action
    assert decision.order_quantity == expected_qty


def test_logical_fix_c_preserves_output_aliases():
    payload = calculate_shannon_decision(
        10.0, 100.0, 1000.0, 50.0, 100.0
    ).to_dict()
    assert payload["order_qty"] == payload["order_quantity"]
    assert payload["rebalance"] == payload["rebalance_amount"]
    assert payload["baseline"] == payload["baseline_pnl"]


def test_market_order_payload_matches_webull_v2_us_stock_contract():
    payload = build_market_order_payload("smr", "buy", 1.23000, "manual-id")
    assert payload == [{
        "combo_type": "NORMAL",
        "client_order_id": "manual-id",
        "symbol": "SMR",
        "instrument_type": "EQUITY",
        "market": "US",
        "order_type": "MARKET",
        "quantity": "1.23",
        "support_trading_session": "CORE",
        "side": "BUY",
        "time_in_force": "DAY",
        "entrust_type": "QTY",
    }]


def test_installed_webull_sdk_v2_paths_and_category_header_match_payload():
    from webull.trade.request.v2.place_order_request import PlaceOrderRequest
    from webull.trade.request.v2.preview_order_request import PreviewOrderRequest

    payload = build_market_order_payload("SMR", "BUY", 1.0, "manual-id")
    place = PlaceOrderRequest()
    place.set_account_id("account")
    place.set_new_orders(payload)
    place.add_custom_headers_from_order(payload)
    preview = PreviewOrderRequest()
    preview.set_account_id("account")
    preview.set_new_orders(payload)

    assert place._action_name == "/openapi/trade/stock/order/place"
    assert preview._action_name == "/openapi/trade/stock/order/preview"
    assert place._method == preview._method == "POST"
    assert place._header["x-version"] == "v2"
    assert place._header["category"] == "US_STOCK"
    assert place._body_params["new_orders"] == payload
    assert preview._body_params["new_orders"] == payload


@pytest.mark.parametrize("quantity", [0, -1, float("nan"), float("inf")])
def test_invalid_order_quantity_is_rejected(quantity):
    with pytest.raises(ValueError):
        format_order_quantity(quantity)


def test_client_order_id_is_stable_and_symbol_normalized():
    first = generate_client_order_id("MANUAL", "aapl", 1)
    assert first == generate_client_order_id("MANUAL", "AAPL", 1)
    assert len(first) == 32


def test_nested_api_responses_are_parsed():
    positions = {"data": [{"ticker": "SMR", "positionQty": "4.5"}]}
    quote = {"data": {"symbol": "SMR", "lastPrice": "11.25"}}
    assert extract_quantity(positions, "SMR") == 4.5
    assert extract_last_price(quote, "SMR") == 11.25


def test_response_parser_rejects_non_2xx():
    response = SimpleNamespace(status_code=401, text="unauthorized")
    with pytest.raises(WebullResponseError, match="401"):
        response_json_or_raise(response)


def test_manual_client_uses_selected_endpoint_without_exposing_secrets():
    api_client = Mock()
    api_client_type = Mock(return_value=api_client)
    data_client_type = Mock(return_value=Mock())
    trade_client_type = Mock(return_value=Mock())
    settings = ConnectionSettings("Test (UAT)", "account", "key", "secret")

    modules = {
        "webull.core.client.ApiClient": api_client_type,
        "webull.data.data_client.DataClient": data_client_type,
        "webull.trade.trade_client.TradeClient": trade_client_type,
    }
    with patch.multiple(
        "webull.core.client", ApiClient=api_client_type
    ), patch.multiple(
        "webull.data.data_client", DataClient=data_client_type
    ), patch.multiple(
        "webull.trade.trade_client", TradeClient=trade_client_type
    ):
        client = WebullManualClient(settings)

    api_client.add_endpoint.assert_called_once_with(
        "th", "th-api.uat.webullbroker.com"
    )
    assert client.settings is settings
    assert modules


def test_account_and_order_management_call_sdk_v2_with_validated_inputs():
    settings = ConnectionSettings("Test (UAT)", "account", "key", "secret")
    account_v2 = Mock()
    order_v2 = Mock()
    account_v2.get_account_list.return_value = {"accounts": []}
    account_v2.get_account_balance.return_value = {"balance": "100"}
    account_v2.get_account_position.return_value = {"positions": []}
    order_v2.get_order_open.return_value = {"open": []}
    order_v2.get_order_history.return_value = {"history": []}
    order_v2.get_order_detail.return_value = {"status": "SUBMITTED"}
    order_v2.cancel_order.return_value = {"status": "CANCELLED"}
    client = WebullManualClient.__new__(WebullManualClient)
    client.settings = settings
    client.trade_client = SimpleNamespace(
        account_v2=account_v2,
        order_v2=order_v2,
    )

    assert client.get_account_list() == {"accounts": []}
    assert client.get_account_balance() == {"balance": "100"}
    assert client.get_positions() == {"positions": []}
    assert client.get_open_orders(25) == {"open": []}
    assert client.get_order_history(20, "2026-07-01", "2026-07-10") == {
        "history": []
    }
    assert client.get_order_detail("order-1") == {"status": "SUBMITTED"}
    assert client.cancel_order("order-1") == {"status": "CANCELLED"}

    account_v2.get_account_balance.assert_called_once_with("account")
    order_v2.get_order_open.assert_called_once_with("account", page_size=25)
    order_v2.get_order_history.assert_called_once_with(
        "account",
        page_size=20,
        start_date="2026-07-01",
        end_date="2026-07-10",
    )
    order_v2.cancel_order.assert_called_once_with("account", "order-1")


@pytest.mark.parametrize("page_size", [0, 101])
def test_order_queries_reject_invalid_page_size(page_size):
    client = WebullManualClient.__new__(WebullManualClient)
    client.settings = ConnectionSettings("Test (UAT)", "account", "key", "secret")
    client.trade_client = SimpleNamespace(order_v2=Mock())
    with pytest.raises(ValueError, match="page_size"):
        client.get_open_orders(page_size)


def test_order_history_rejects_reverse_date_range():
    client = WebullManualClient.__new__(WebullManualClient)
    client.settings = ConnectionSettings("Test (UAT)", "account", "key", "secret")
    client.trade_client = SimpleNamespace(order_v2=Mock())
    with pytest.raises(ValueError, match="start_date"):
        client.get_order_history(20, "2026-07-10", "2026-07-01")


def test_benchmark_reports_both_algorithms():
    result = run_benchmark(
        "bypass:3", 10.0, 100.0, 1000.0, 50.0, 100.0, iterations=2
    )
    assert result["iterations"] == 2
    assert result["logical_fix_c"]["operations_per_second"] > 0
    assert result["decode_dna"]["operations_per_second"] > 0


def test_benchmark_rejects_unbounded_work():
    with pytest.raises(ValueError):
        run_benchmark(
            "bypass:3", 10.0, 100.0, 1000.0, 50.0, 100.0,
            iterations=100_001,
        )
