"""FIFO netting of disclosure lines into positions."""

import unittest
from datetime import date

import pandas as pd

from ptrack import netting


def trade(tid, person, ticker, side, amount, day, asset_type="equity",
          direction="long"):
    return {
        "trade_id": tid, "person_id": person, "ticker": ticker, "side": side,
        "amount_mid": amount, "trade_date": date(2020, 1, day),
        "asset_type": asset_type, "direction": direction, "sector": "technology",
        "amount_range_text": "$1,001 - $15,000", "disclosure_date": date(2020, 2, day),
        "disclosure_lag_days": 31,
    }


class TestAssetGrouping(unittest.TestCase):
    def test_equity_and_etf_share_a_group(self):
        self.assertEqual(netting.asset_group("etf"), netting.asset_group("equity"))

    def test_options_and_shorts_are_separate_groups(self):
        groups = {netting.asset_group(t)
                  for t in ("equity", "option_call", "option_put", "short")}
        self.assertEqual(len(groups), 4, "a call must not be netted against stock")

    def test_short_sale_opens_on_the_sell(self):
        self.assertTrue(netting.opens_position("short", "sell"))
        self.assertTrue(netting.closes_position("short", "buy"))

    def test_equity_opens_on_the_buy(self):
        self.assertTrue(netting.opens_position("equity", "buy"))
        self.assertTrue(netting.closes_position("equity", "sell"))


class TestNetting(unittest.TestCase):
    def test_buy_then_sell_produces_one_closed_position(self):
        df = pd.DataFrame([
            trade("t1", "p", "AAA", "buy", 10000, 1),
            trade("t2", "p", "AAA", "sell", 10000, 5),
        ])
        result = netting.net_trades(df)
        self.assertEqual(len(result.positions), 1)
        row = result.positions.iloc[0]
        self.assertFalse(row["is_open"])
        self.assertEqual(row["open_trade_id"], "t1")
        self.assertEqual(row["close_trade_id"], "t2")
        self.assertEqual(row["matched_amount_mid"], 10000)

    def test_unsold_purchase_stays_open(self):
        df = pd.DataFrame([trade("t1", "p", "AAA", "buy", 10000, 1)])
        result = netting.net_trades(df)
        self.assertTrue(result.positions.iloc[0]["is_open"])
        self.assertIsNone(result.positions.iloc[0]["close_trade_id"])

    def test_fifo_order_matches_oldest_lot_first(self):
        df = pd.DataFrame([
            trade("t1", "p", "AAA", "buy", 5000, 1),
            trade("t2", "p", "AAA", "buy", 5000, 2),
            trade("t3", "p", "AAA", "sell", 5000, 3),
        ])
        closed = netting.net_trades(df).positions.query("is_open == False")
        self.assertEqual(len(closed), 1)
        self.assertEqual(closed.iloc[0]["open_trade_id"], "t1",
                         "the oldest lot must be closed first")

    def test_partial_sale_splits_the_lot_and_is_flagged(self):
        df = pd.DataFrame([
            trade("t1", "p", "AAA", "buy", 10000, 1),
            trade("t2", "p", "AAA", "sell", 4000, 5),
        ])
        positions = netting.net_trades(df).positions
        closed = positions.query("is_open == False").iloc[0]
        still_open = positions.query("is_open == True").iloc[0]
        self.assertEqual(closed["matched_amount_mid"], 4000)
        self.assertEqual(closed["open_amount_mid"], 10000)
        self.assertTrue(closed["is_partial_lot"])
        self.assertEqual(still_open["matched_amount_mid"], 6000)

    def test_sale_larger_than_holdings_reports_an_orphan(self):
        df = pd.DataFrame([
            trade("t1", "p", "AAA", "buy", 4000, 1),
            trade("t2", "p", "AAA", "sell", 10000, 5),
        ])
        result = netting.net_trades(df)
        self.assertEqual(result.orphan_closes, 1)
        self.assertEqual(len(result.positions), 1)

    def test_sale_with_no_prior_purchase_is_an_orphan_not_a_position(self):
        df = pd.DataFrame([trade("t1", "p", "AAA", "sell", 10000, 5)])
        result = netting.net_trades(df)
        self.assertEqual(result.orphan_closes, 1)
        self.assertTrue(result.positions.empty)
        self.assertTrue(any("no matching prior purchase" in n for n in result.notes))

    def test_different_people_are_never_netted_together(self):
        df = pd.DataFrame([
            trade("t1", "alice", "AAA", "buy", 10000, 1),
            trade("t2", "bob", "AAA", "sell", 10000, 5),
        ])
        result = netting.net_trades(df)
        self.assertEqual(result.orphan_closes, 1)
        self.assertTrue(result.positions.iloc[0]["is_open"])

    def test_calls_are_not_closed_by_stock_sales(self):
        df = pd.DataFrame([
            trade("t1", "p", "AAA", "buy", 10000, 1, asset_type="option_call"),
            trade("t2", "p", "AAA", "sell", 10000, 5, asset_type="equity"),
        ])
        result = netting.net_trades(df)
        self.assertEqual(result.orphan_closes, 1)
        self.assertTrue(result.positions.iloc[0]["is_open"])

    def test_short_sale_opens_and_purchase_closes(self):
        df = pd.DataFrame([
            trade("t1", "p", "AAA", "sell", 10000, 1, asset_type="short",
                  direction="short"),
            trade("t2", "p", "AAA", "buy", 10000, 9, asset_type="short",
                  direction="short"),
        ])
        positions = netting.net_trades(df).positions
        self.assertEqual(len(positions), 1)
        row = positions.iloc[0]
        self.assertFalse(row["is_open"])
        self.assertEqual(row["open_trade_id"], "t1")
        self.assertEqual(row["direction"], "short")

    def test_empty_input_is_handled(self):
        self.assertTrue(netting.net_trades(pd.DataFrame()).positions.empty)


if __name__ == "__main__":
    unittest.main()
