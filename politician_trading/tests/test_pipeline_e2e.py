"""End-to-end pipeline test over a tiny, hand-computable dataset.

Hermetic by construction: the roster source is stubbed and sector lookup is
disabled, so nothing here touches the network. Every expected number below is
derived by hand in the comments, so a regression in the return, benchmark or
netting math fails loudly instead of drifting quietly.
"""

import shutil
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

import pandas as pd

from ptrack import db, pipeline
from ptrack.config import load_config
from ptrack.sources.base import FetchResult

# --------------------------------------------------------------------------
# The fixture. Weekdays only, so trading-day math is predictable.
#
#   AAA  100 -> 110 between 2020-01-06 and 2020-01-10   (+10%)
#   SPY  100 -> 102 over the same window                (+2%)
#   XLK  100 -> 105 over the same window                (+5%)
#
# One filer buys AAA on the 6th and sells it on the 10th. Therefore:
#   position_return      = +10%
#   alpha_vs_spy         = 10% - 2%  = +8%
#   alpha_vs_sector_etf  = 10% - 5%  = +5%
# --------------------------------------------------------------------------
DAYS = [date(2020, 1, 6), date(2020, 1, 7), date(2020, 1, 8),
        date(2020, 1, 9), date(2020, 1, 10), date(2020, 1, 13),
        date(2020, 1, 14), date(2020, 1, 15), date(2020, 1, 16),
        date(2020, 1, 17), date(2020, 1, 20), date(2020, 1, 21)]

PRICE_PATHS = {
    "AAA": [100, 102, 104, 106, 110, 111, 112, 113, 114, 115, 116, 117],
    "BBB": [50, 50, 50, 50, 50, 50, 50, 50, 50, 50, 50, 50],
    "SPY": [100, 100.5, 101, 101.5, 102, 102, 102, 102, 102, 102, 102, 102],
    "XLK": [100, 101, 102, 103, 105, 105, 105, 105, 105, 105, 105, 105],
    "XLE": [100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 100],
}

DISCLOSURES = [
    # The hand-computed case: a clean round trip in AAA.
    {"filer_name": "Test Filer One", "chamber": "house", "owner_code": "SELF",
     "trade_date": "2020-01-06", "disclosure_date": "2020-01-09", "ticker": "AAA",
     "asset_name": "AAA Common Stock", "asset_type_hint": "Stock",
     "transaction_type": "Purchase", "amount_range_text": "$1,001 - $15,000",
     "sector": "technology"},
    {"filer_name": "Test Filer One", "chamber": "house", "owner_code": "SELF",
     "trade_date": "2020-01-10", "disclosure_date": "2020-01-15", "ticker": "AAA",
     "asset_name": "AAA Common Stock", "asset_type_hint": "Stock",
     "transaction_type": "Sale (Full)", "amount_range_text": "$1,001 - $15,000",
     "sector": "technology"},
    # Never sold -> must come out UNREALIZED.
    {"filer_name": "Test Filer One", "chamber": "house", "owner_code": "SELF",
     "trade_date": "2020-01-07", "disclosure_date": "2020-01-14", "ticker": "BBB",
     "asset_name": "BBB Common Stock", "asset_type_hint": "Stock",
     "transaction_type": "Purchase", "amount_range_text": "$15,001 - $50,000",
     "sector": "energy"},
    # A spouse-owned row -> must become a separate person keyed to the member.
    {"filer_name": "Test Filer One", "chamber": "house", "owner_code": "SP",
     "trade_date": "2020-01-08", "disclosure_date": "2020-01-16", "ticker": "AAA",
     "asset_name": "AAA Call Options", "asset_type_hint": "Options",
     "transaction_type": "Purchase", "amount_range_text": "$50,001 - $100,000",
     "sector": "technology"},
    # Opened 2 trading days before the energy event below.
    {"filer_name": "Test Filer Two", "chamber": "senate", "owner_code": "SELF",
     "trade_date": "2020-01-13", "disclosure_date": "2020-01-20", "ticker": "BBB",
     "asset_name": "BBB Common Stock", "asset_type_hint": "Stock",
     "transaction_type": "Purchase", "amount_range_text": "$1,001 - $15,000",
     "sector": "energy"},
]

EVENTS = [
    {"event_id": "E-ENERGY-1", "date": "2020-01-15", "category": "legislation",
     "sectors": "energy", "description": "Test energy legislation",
     "source": "test", "source_url": "test"},
]


def stub_roster(*_args, **_kwargs) -> FetchResult:
    """Keeps the test hermetic: no clone, no HTTPS call to GitHub."""
    return FetchResult(data=pd.DataFrame([{
        "bioguide_id": "T000001", "full_name": "Test Filer One",
        "filer_name": "Test Filer One", "relation": "self", "chamber": "house",
        "party": "Independent", "state": "ZZ", "district": "1",
        "term_start": "2019-01-03", "term_end": "2021-01-03", "is_current": True,
        "source": "stub", "source_url": "stub",
    }]), source="stub-roster", source_url="stub")


class PipelineE2ETest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="ptrack-e2e-"))
        cls._write_inputs()

        cfg = load_config()
        cfg.report_top_n = 50
        cfg.min_trades_for_ranking = 1     # the fixture is deliberately tiny
        cls.cfg = cfg

        cls.con = db.connect(cls.tmp / "e2e.duckdb")
        run_id = "e2e-test-run"

        with mock.patch.object(pipeline.roster_src, "congress_legislators",
                               side_effect=stub_roster):
            pipeline.ingest(
                cls.con, cfg, run_id,
                events_csv=cls.tmp / "events.csv",
                local_prices_csv=cls.tmp / "prices.csv",
                local_trades_csv=cls.tmp / "trades.csv",
                resolve_sectors=False,
            )
        cls.analysis = pipeline.analyze(cls.con, cfg, run_id, as_of=date(2020, 1, 21))
        cls.paths = pipeline.build_report(cls.con, cfg, run_id, cls.tmp / "report",
                                          as_of=date(2020, 1, 21))
        cls.trade_metrics = cls.con.execute("SELECT * FROM trade_metrics").df()
        cls.person_metrics = cls.con.execute("SELECT * FROM person_metrics").df()
        cls.markdown = (cls.tmp / "report" / "ranked_report.md").read_text()

    @classmethod
    def tearDownClass(cls):
        cls.con.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    @classmethod
    def _write_inputs(cls):
        prices = [{"ticker": t, "date": d.isoformat(), "open": p, "high": p,
                   "low": p, "close": p, "adj_close": p, "volume": 1000}
                  for t, path in PRICE_PATHS.items() for d, p in zip(DAYS, path)]
        pd.DataFrame(prices).to_csv(cls.tmp / "prices.csv", index=False)
        pd.DataFrame(DISCLOSURES).to_csv(cls.tmp / "trades.csv", index=False)
        pd.DataFrame(EVENTS).to_csv(cls.tmp / "events.csv", index=False)

    # -- ingest ----------------------------------------------------------
    def test_all_disclosure_rows_land_in_the_database(self):
        self.assertEqual(db.table_count(self.con, "trades"), len(DISCLOSURES))

    def test_every_deliverable_table_is_populated(self):
        for table in ("people", "trades", "prices", "benchmarks", "events",
                      "trade_event_links", "positions", "trade_metrics",
                      "person_metrics"):
            self.assertGreater(db.table_count(self.con, table), 0, table)

    def test_spouse_row_becomes_a_person_linked_to_the_member(self):
        spouse = self.con.execute(
            "SELECT person_id, official_person_id, relation FROM people "
            "WHERE relation = 'spouse'").fetchall()
        self.assertEqual(len(spouse), 1)
        person_id, official_id, _ = spouse[0]
        self.assertTrue(person_id.endswith("::spouse"))
        self.assertEqual(official_id, "test-filer-one")

    def test_disclosure_lag_is_computed_in_calendar_days(self):
        lag = self.con.execute(
            "SELECT disclosure_lag_days FROM trades "
            "WHERE ticker = 'AAA' AND side = 'buy' AND owner_code = 'SELF'"
        ).fetchone()[0]
        self.assertEqual(lag, 3)          # 2020-01-06 -> 2020-01-09

    def test_amount_midpoint_is_stored_with_its_bounds(self):
        low, high, mid, is_est = self.con.execute(
            "SELECT amount_low, amount_high, amount_mid, amount_is_estimate "
            "FROM trades WHERE amount_range_text = '$1,001 - $15,000' LIMIT 1"
        ).fetchone()
        self.assertEqual((low, high), (1001, 15000))
        self.assertAlmostEqual(mid, 8000.5)
        self.assertTrue(is_est, "a range-derived figure must be flagged an estimate")

    # -- netting and returns ---------------------------------------------
    def test_round_trip_nets_into_one_closed_position(self):
        closed = self.trade_metrics[
            (self.trade_metrics["ticker"] == "AAA")
            & (~self.trade_metrics["is_open"])
            & (self.trade_metrics["asset_type"] == "equity")]
        self.assertEqual(len(closed), 1, "buy+sell must net, not count twice")
        self.assertEqual(str(closed.iloc[0]["open_date"])[:10], "2020-01-06")
        self.assertEqual(str(closed.iloc[0]["close_date"])[:10], "2020-01-10")

    def test_realized_return_matches_the_hand_computed_value(self):
        row = self._closed_aaa()
        self.assertAlmostEqual(row["position_return_pct"], 110 / 100 - 1, places=9)

    def test_alpha_vs_spy_matches_the_hand_computed_value(self):
        # +10% position - +2% SPY = +8%
        self.assertAlmostEqual(self._closed_aaa()["alpha_vs_spy"],
                               (110 / 100 - 1) - (102 / 100 - 1), places=9)

    def test_alpha_vs_sector_etf_matches_the_hand_computed_value(self):
        # technology -> XLK; +10% position - +5% XLK = +5%
        row = self._closed_aaa()
        self.assertEqual(row["sector_etf"], "XLK")
        self.assertFalse(row["sector_benchmark_is_fallback"])
        self.assertAlmostEqual(row["alpha_vs_sector_etf"],
                               (110 / 100 - 1) - (105 / 100 - 1), places=9)

    def test_benchmarks_use_the_identical_window(self):
        row = self._closed_aaa()
        self.assertAlmostEqual(row["spy_return_pct"], 102 / 100 - 1, places=9)
        self.assertAlmostEqual(row["sector_etf_return_pct"], 105 / 100 - 1, places=9)

    def test_disclosure_drift_is_separate_from_the_return(self):
        row = self._closed_aaa()
        # Trade 2020-01-06 (100) -> disclosed 2020-01-09 (106) = +6%,
        # which must NOT equal the +10% held return.
        self.assertAlmostEqual(row["disclosure_drift_pct"], 106 / 100 - 1, places=9)
        self.assertNotAlmostEqual(row["disclosure_drift_pct"],
                                  row["position_return_pct"])

    def test_unsold_position_is_marked_unrealized_at_the_as_of_price(self):
        row = self.trade_metrics[
            (self.trade_metrics["ticker"] == "BBB")
            & (self.trade_metrics["person_id"] == "test-filer-one")].iloc[0]
        self.assertTrue(row["is_open"])
        self.assertTrue(pd.isna(row["close_date"]))
        self.assertAlmostEqual(row["position_return_pct"], 0.0, places=9)

    def test_option_return_is_labelled_an_underlying_proxy(self):
        row = self.trade_metrics[
            self.trade_metrics["asset_type"] == "option_call"].iloc[0]
        self.assertEqual(row["return_basis"], "underlying_proxy_for_option")

    # -- events ----------------------------------------------------------
    def test_trades_before_a_sector_matched_event_are_flagged(self):
        flagged = self.trade_metrics[self.trade_metrics["matched_event_id"].notna()]
        # Both energy purchases fall inside the 10-trading-day window.
        self.assertEqual(len(flagged), 2)
        self.assertTrue((flagged["matched_event_id"] == "E-ENERGY-1").all())
        self.assertTrue((flagged["ticker"] == "BBB").all())
        by_open = {str(r.open_date)[:10]: r.matched_event_days_before
                   for r in flagged.itertuples(index=False)}
        self.assertEqual(by_open["2020-01-13"], 2)   # -> 2020-01-15
        self.assertEqual(by_open["2020-01-07"], 6)

    def test_technology_trade_is_not_matched_to_an_energy_event(self):
        tech = self.trade_metrics[self.trade_metrics["sector"] == "technology"]
        self.assertTrue(tech["matched_event_id"].isna().all())

    # -- scoring ---------------------------------------------------------
    def test_composite_score_reproduces_the_stated_formula(self):
        row = self.person_metrics[
            self.person_metrics["person_id"] == "test-filer-one"].iloc[0]
        w = self.cfg.weights
        expected = (w["mean_alpha_vs_spy"] * row["mean_alpha_vs_spy"]
                    + w["win_rate"] * row["win_rate"]
                    + w["median_alpha_vs_sector_etf"] * row["median_alpha_vs_sector_etf"]
                    + w["event_proximity_rate"] * row["event_proximity_rate"])
        self.assertAlmostEqual(row["composite_score"], expected, places=9)

    def test_metrics_survive_the_round_trip_through_the_database(self):
        # These were silently dropped once by being absent from the schema.
        for column in ("median_disclosure_drift_pct", "win_rate_closed",
                       "positions_dropped_no_prices", "score_components_present"):
            self.assertIn(column, self.person_metrics.columns)
            self.assertTrue(self.person_metrics[column].notna().any(), column)

    # -- report ----------------------------------------------------------
    def test_all_report_artifacts_are_written(self):
        for key in ("markdown", "ranked", "person_metrics", "trade_metrics"):
            self.assertTrue(Path(self.paths[key]).exists(), key)
            self.assertGreater(Path(self.paths[key]).stat().st_size, 0, key)

    def test_report_states_the_scoring_formula(self):
        self.assertIn("0.4*mean_alpha_vs_spy", self.markdown)
        self.assertIn("0.3*win_rate", self.markdown)

    def test_report_carries_the_required_caveats(self):
        for phrase in ("estimate", "UNREALIZED", "correlational",
                       "not** evidence", "Nothing here asserts illegality",
                       "reporting lag"):
            self.assertIn(phrase, self.markdown, f"missing caveat: {phrase}")

    def test_report_never_prints_a_bare_dollar_figure(self):
        """Every dollar figure must be marked an estimate or be a disclosed range."""
        import re
        text = self.markdown
        # Remove the three legitimate forms, then nothing with a $ may remain.
        text = re.sub(r"~\$[\d,]+(?:\.\d+)? \(est\.\)", "", text)      # estimates
        text = re.sub(r"\$[\d,]+(?:\.\d+)? - \$[\d,]+(?:\.\d+)?", "", text)  # ranges
        text = re.sub(r"over \$[\d,]+", "", text)                       # open bracket
        leftover = re.findall(r"\$[\d,]+(?:\.\d+)?", text)
        self.assertEqual(leftover, [],
                         f"unmarked dollar figures in report: {leftover}")

    def test_report_cites_its_data_sources(self):
        self.assertIn("## Data sources", self.markdown)
        self.assertIn("stub-roster", self.markdown,
                      "the report must cite the roster that actually answered, "
                      "not a hardcoded default")

    def _closed_aaa(self):
        return self.trade_metrics[
            (self.trade_metrics["ticker"] == "AAA")
            & (~self.trade_metrics["is_open"])
            & (self.trade_metrics["asset_type"] == "equity")].iloc[0]


if __name__ == "__main__":
    unittest.main()
