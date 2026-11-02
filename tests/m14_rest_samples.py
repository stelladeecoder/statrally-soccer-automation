"""SYNTHETIC ONLY — OpenAPI 3.35.0-shaped records, never account results."""
from decimal import Decimal

from m14_import import CURRENT_SCHEMA


def rest_fill(fid="synthetic-rest-buy", direction="yes", count="2.00", yes="0.400000", fee="0.020000",
              when="2026-11-01T12:00:00Z", ticker="SYNTHETIC-MARKET"):
    return {"fill_id": fid, "exchange_index": 0, "trade_id": fid, "order_id": "synthetic-order-" + fid,
            "ticker": ticker, "market_ticker": ticker, "outcome_side": direction,
            "book_side": "bid" if direction == "yes" else "ask", "count_fp": count,
            "yes_price_dollars": yes, "no_price_dollars": format(1 - Decimal(yes), ".6f"),
            "is_taker": True, "created_time": when, "fee_cost": fee, "subaccount_number": 0}


def rest_settlement(ticker="SYNTHETIC-MARKET", result="yes", yes_count="2.00", no_count="0.00",
                    yes_cost="0.800000", no_cost="0.000000", revenue=200, fee="0.020000",
                    when="2026-11-03T12:00:00Z"):
    return {"ticker": ticker, "exchange_index": 0, "event_ticker": "SYNTHETIC-EVENT", "market_result": result,
            "yes_count_fp": yes_count, "no_count_fp": no_count, "yes_total_cost_dollars": yes_cost,
            "no_total_cost_dollars": no_cost, "revenue": revenue, "settled_time": when, "fee_cost": fee}


def rest_position(ticker="SYNTHETIC-MARKET", quantity="2.00", fees="0.020000", traded="0.800000",
                  exposure="0.800000", pnl="0.000000", when="2026-11-04T12:00:00Z"):
    return {"ticker": ticker, "exchange_index": 0, "total_traded_dollars": traded, "position_fp": quantity,
            "market_exposure_dollars": exposure, "realized_pnl_dollars": pnl,
            "fees_paid_dollars": fees, "last_updated_ts": when}


def rest_page(array, records, request="", cursor=""):
    response = {array: records, "cursor": cursor}
    if array == "market_positions":
        response["event_positions"] = []
    return {"request_cursor": request, "response": response}


def rest_bundle(fills=None, historical_fills=None, settlements=None, positions=None, archived=None, retained=None):
    spec = {"portfolio_fills": ("/portfolio/fills", "fills", fills or []),
            "historical_fills": ("/historical/fills", "fills", historical_fills or []),
            "portfolio_settlements": ("/portfolio/settlements", "settlements", settlements or []),
            "portfolio_positions": ("/portfolio/positions", "market_positions", positions or []),
            "historical_positions": ("/historical/positions", "market_positions", archived or [])}
    collections = {}
    for name, (endpoint, array, records) in spec.items():
        query = {"subaccount": 0}
        if name in ("portfolio_fills", "portfolio_positions"):
            query["exchange_index"] = 0
        if name == "portfolio_positions":
            query["settlement_status"] = "all"
        collections[name] = {"endpoint": endpoint, "query": query, "pages": [rest_page(array, records)]}
    return {"schema": CURRENT_SCHEMA, "data_kind": "synthetic", "history_from_inception": True,
            "scope": {"account_ref": "SYNTHETIC-ACCOUNT-ONLY", "subaccount_number": 0, "exchange_index": 0, "netting_mode": "net"},
            "captured_at": "2026-11-05T12:00:00Z", "historical_cutoff": {
                "market_settled_ts": "2026-10-01T00:00:00Z", "trades_created_ts": "2026-11-02T00:00:00Z",
                "orders_updated_ts": "2026-10-01T00:00:00Z", "market_positions_last_updated_ts": "2026-10-01T00:00:00Z"},
            "collections": collections, "retained_settlements": retained or []}


def integration_snapshot():
    return rest_bundle(historical_fills=[rest_fill("synthetic-buy", count="4.00", fee="0.040000")],
                       fills=[rest_fill("synthetic-sell", direction="no", count="1.00", yes="0.600000", fee="0.020000", when="2026-11-02T12:00:00Z")],
                       settlements=[rest_settlement(yes_count="3.00", yes_cost="1.200000", revenue=300, fee="0.060000")],
                       positions=[rest_position(quantity="0.00", fees="0.060000", traded="2.200000", exposure="0.000000", pnl="1.940000", when="2026-11-03T12:00:00Z")])


def add_open_fill(snapshot):
    snapshot["collections"]["portfolio_fills"]["pages"][0]["response"]["fills"].append(
        rest_fill("additional", ticker="SYNTHETIC-OTHER", fee="0.000000", when="2026-11-02T13:00:00Z"))
    snapshot["collections"]["portfolio_positions"]["pages"][0]["response"]["market_positions"].append(
        rest_position(ticker="SYNTHETIC-OTHER", fees="0.000000", when="2026-11-02T13:00:00Z"))
