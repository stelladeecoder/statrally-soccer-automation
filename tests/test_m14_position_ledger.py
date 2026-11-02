"""M14 ledger accounting regression tests. No live positions or fake results."""
import unittest
from decimal import Decimal
from m14_position_ledger import summarize

def event(id, action, quantity, price, fee="0", ticker="SAMPLE"):
    return {"event_id":id,"market_ticker":ticker,"side":"YES",
            "action":action,"quantity":quantity,"price":price,"fee_usd":fee}

class M14LedgerTests(unittest.TestCase):
    def test_fully_settled_win_with_fees(self):
        r=summarize([event("a","BUY",10,"0.45","0.10"),
                     event("b","SETTLE",10,"1","0")])
        self.assertEqual(Decimal(r["total_realized_pnl_usd"]),Decimal("5.40"))
        self.assertEqual(r["positions"][0]["open_contracts"],0)
    def test_fully_settled_loss(self):
        r=summarize([event("a","BUY",4,"0.60","0.04"),
                     event("b","SETTLE",4,"0","0")])
        self.assertEqual(Decimal(r["total_realized_pnl_usd"]),Decimal("-2.44"))
    def test_partial_exit_then_settlement_fifo(self):
        r=summarize([event("a","BUY",5,"0.20","0.05"),
                     event("b","BUY",5,"0.40","0.05"),
                     event("c","SELL",7,"0.60","0.07"),
                     event("d","SETTLE",3,"1","0")])
        self.assertEqual(Decimal(r["total_realized_pnl_usd"]),Decimal("4.03"))
    def test_open_position_not_counted_as_win(self):
        r=summarize([event("a","BUY",3,"0.50","0.03")])
        self.assertEqual(r["positions"][0]["open_contracts"],3)
        self.assertEqual(Decimal(r["total_realized_pnl_usd"]),Decimal("0"))
        self.assertEqual(Decimal(r["positions"][0]["open_total_basis_usd"]),Decimal("1.53"))
    def test_over_sell_rejected(self):
        with self.assertRaises(ValueError):
            summarize([event("a","BUY",1,"0.40"),event("b","SELL",2,"0.70")])
    def test_duplicate_id_rejected(self):
        with self.assertRaises(ValueError):
            summarize([event("a","BUY",1,"0.40"),event("a","SELL",1,"0.70")])
    def test_settlement_price_must_be_binary(self):
        with self.assertRaises(ValueError):
            summarize([event("a","BUY",1,"0.40"),event("b","SETTLE",1,"0.70")])
    def test_negative_fee_rejected(self):
        with self.assertRaises(ValueError):
            summarize([event("a","BUY",1,"0.40","-0.01")])
    def test_side_separation(self):
        r=summarize([event("a","BUY",1,"0.40"),dict(event("b","BUY",2,"0.20"),side="NO")])
        self.assertEqual(len(r["positions"]),2)

if __name__ == "__main__":
    unittest.main()
