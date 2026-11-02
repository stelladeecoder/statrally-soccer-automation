"""SYNTHETIC ONLY: SDK-shaped records, never account data or real results."""

def fill(fid="synthetic-fill-1", action="buy", count=2, yes="0.4000", no="0.6000",
         when="2026-11-01T12:00:00Z", side="yes", ticker="SYNTHETIC-MARKET"):
    return {"fill_id": fid, "trade_id": fid, "order_id": "synthetic-order-" + fid,
            "ticker": ticker, "market_ticker": ticker, "side": side, "action": action,
            "count": count, "price": 40, "yes_price_fixed": yes, "no_price_fixed": no,
            "is_taker": True, "created_time": when}


def settlement(result="yes", yes_count=2, no_count=0, yes_cost=80, no_cost=0,
               revenue=200, fee="0", when="2026-11-02T12:00:00Z", ticker="SYNTHETIC-MARKET"):
    return {"ticker": ticker, "event_ticker": "SYNTHETIC-EVENT", "market_result": result,
            "yes_count": yes_count, "no_count": no_count, "yes_total_cost": yes_cost,
            "no_total_cost": no_cost, "revenue": revenue, "fee_cost": fee, "settled_time": when}


def page(name, records, request_cursor="", cursor=""):
    return {"request_cursor": request_cursor, "response": {name: records, "cursor": cursor}}


def bundle(fills=None, settlements=None, fees=None):
    fills = [] if fills is None else fills
    return {"schema": "kalshi-sdk-3.2.0", "data_kind": "synthetic", "history_from_inception": True,
            "fills_pages": [page("fills", fills)], "settlements_pages": [page("settlements", settlements or [])],
            "fill_fees": [{"fill_id": row["fill_id"], "fee_usd": (fees or {}).get(row["fill_id"], "0")} for row in fills]}


def event(eid, action, quantity, price, when, fee="0", side="YES", ticker="SYNTHETIC-MARKET"):
    return {"event_id": eid, "action": action, "quantity": quantity, "price": price,
            "timestamp": when, "fee_usd": fee, "side": side, "market_ticker": ticker}
