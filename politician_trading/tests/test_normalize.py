"""Amount-range, asset-type and ticker normalisation."""

import unittest
from datetime import date

from ptrack import normalize
from ptrack.config import load_config

CFG = load_config()


class TestAmountRanges(unittest.TestCase):
    def test_bracket_midpoint_is_average_of_bounds(self):
        got = normalize.parse_amount_range("$1,001 - $15,000", CFG)
        self.assertEqual(got["amount_low"], 1001)
        self.assertEqual(got["amount_high"], 15000)
        self.assertAlmostEqual(got["amount_mid"], 8000.5)
        self.assertTrue(got["amount_is_estimate"])
        self.assertFalse(got["amount_bound_open"])

    def test_open_ended_top_bracket_uses_floor_and_is_flagged(self):
        got = normalize.parse_amount_range("over $50,000,000", CFG)
        self.assertEqual(got["amount_low"], 50000001)
        self.assertIsNone(got["amount_high"])
        self.assertEqual(got["amount_mid"], 50000001)
        self.assertTrue(got["amount_bound_open"],
                        "an open-ended bracket has no midpoint and must be flagged")

    def test_alias_forms_map_to_the_canonical_bracket(self):
        canonical = normalize.parse_amount_range("$15,001 - $50,000", CFG)
        alias = normalize.parse_amount_range("$15,001-$50,000", CFG)
        self.assertEqual(alias["amount_mid"], canonical["amount_mid"])

    def test_unparseable_amount_yields_no_dollar_estimate(self):
        for text in (None, "", "n/a", "some words"):
            got = normalize.parse_amount_range(text, CFG)
            self.assertIsNone(got["amount_mid"],
                              f"must not invent a figure for {text!r}")

    def test_reversed_bounds_are_ordered(self):
        got = normalize.parse_amount_range("$50,000 - $1,000", CFG)
        self.assertEqual((got["amount_low"], got["amount_high"]), (1000, 50000))

    def test_every_configured_bracket_round_trips(self):
        for bracket in CFG.brackets:
            got = normalize.parse_amount_range(bracket.text, CFG)
            self.assertEqual(got["amount_low"], bracket.low, bracket.text)
            self.assertEqual(got["amount_high"], bracket.high, bracket.text)


class TestAssetParsing(unittest.TestCase):
    def test_equity_is_long(self):
        self.assertEqual(normalize.parse_asset("Common Stock"), ("equity", "long"))

    def test_call_is_long_underlying_exposure(self):
        self.assertEqual(normalize.parse_asset("NVDA Call Options"),
                         ("option_call", "long"))

    def test_put_is_short_underlying_exposure(self):
        self.assertEqual(normalize.parse_asset("SPY Put Options"),
                         ("option_put", "short"))

    def test_short_sale_is_short(self):
        self.assertEqual(normalize.parse_asset("XYZ Common Stock - short sale"),
                         ("short", "short"))

    def test_written_options_invert_exposure(self):
        self.assertEqual(normalize.parse_asset("written call on TSLA")[1], "short")
        self.assertEqual(normalize.parse_asset("written put on TSLA")[1], "long")

    def test_etf_recognised(self):
        self.assertEqual(normalize.parse_asset("Vanguard Exchange Traded Fund")[0], "etf")


class TestSideParsing(unittest.TestCase):
    def test_buy_variants(self):
        for text in ("P", "Purchase", "purchase", "Buy", "P (partial)"):
            self.assertEqual(normalize.parse_side(text), "buy", text)

    def test_sell_variants(self):
        for text in ("S", "Sale", "Sale (Full)", "Sale (Partial)", "sold"):
            self.assertEqual(normalize.parse_side(text), "sell", text)

    def test_exchange_and_unknown(self):
        self.assertEqual(normalize.parse_side("Exchange"), "exchange")
        self.assertEqual(normalize.parse_side("gift"), "unknown")
        self.assertEqual(normalize.parse_side(None), "unknown")


class TestTickerAndDates(unittest.TestCase):
    def test_placeholder_tickers_are_rejected(self):
        for text in ("--", "N/A", "", "none", "toolongticker"):
            self.assertIsNone(normalize.clean_ticker(text), text)

    def test_valid_tickers_normalised(self):
        self.assertEqual(normalize.clean_ticker("nvda"), "NVDA")
        self.assertEqual(normalize.clean_ticker("BRK.B"), "BRK.B")

    def test_date_formats(self):
        for text in ("2021-01-15", "01/15/2021"):
            self.assertEqual(normalize.parse_date(text), date(2021, 1, 15), text)
        self.assertIsNone(normalize.parse_date("--"))


class TestSectorResolution(unittest.TestCase):
    def test_override_file_wins_over_resolver(self):
        sector, origin = normalize.resolve_sector("LMT", CFG, {"LMT": "technology"})
        self.assertEqual((sector, origin), ("defense", "override"))

    def test_resolver_used_when_no_override(self):
        self.assertEqual(normalize.resolve_sector("ZZZZ", CFG, {"ZZZZ": "energy"}),
                         ("energy", "resolver"))

    def test_unknown_ticker_falls_back(self):
        self.assertEqual(normalize.resolve_sector("ZZZZ", CFG, {}), (None, "fallback"))


if __name__ == "__main__":
    unittest.main()
