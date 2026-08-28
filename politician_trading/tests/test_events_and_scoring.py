"""Event-proximity windowing and composite scoring."""

import unittest
from datetime import date, timedelta

import pandas as pd

from ptrack import event_proximity, returns, scoring

WEIGHTS = {"mean_alpha_vs_spy": 0.4, "win_rate": 0.3,
           "median_alpha_vs_sector_etf": 0.2, "event_proximity_rate": 0.1}


def calendar_book(days: int = 60) -> returns.PriceBook:
    """A price book whose SPY series defines the trading calendar (weekdays)."""
    rows, day = [], date(2020, 1, 1)
    while len(rows) < days:
        if day.weekday() < 5:
            rows.append({"ticker": "SPY", "date": day, "adj_close": 100.0})
        day += timedelta(days=1)
    return returns.PriceBook(pd.DataFrame(rows))


def positions(open_date, sector="defense"):
    return pd.DataFrame([{
        "open_trade_id": "t1", "position_id": "t1::open", "person_id": "p",
        "ticker": "AAA", "sector": sector, "open_date": open_date,
    }])


def events(event_date, sectors="defense"):
    return pd.DataFrame([{
        "event_id": "E1", "event_date": event_date, "sectors": sectors,
        "category": "war", "description": "test",
    }])


class TestEventSectorParsing(unittest.TestCase):
    def test_pipe_separated_sectors(self):
        self.assertEqual(event_proximity.parse_event_sectors("defense|energy"),
                         {"defense", "energy"})

    def test_blank_and_null_are_empty(self):
        self.assertEqual(event_proximity.parse_event_sectors(None), set())
        self.assertEqual(event_proximity.parse_event_sectors(""), set())


class TestProximityWindow(unittest.TestCase):
    def setUp(self):
        self.book = calendar_book()

    def _link(self, open_date, event_date, **kw):
        return event_proximity.link_trades_to_events(
            positions(open_date, kw.get("trade_sector", "defense")),
            events(event_date, kw.get("event_sectors", "defense")),
            self.book, kw.get("window", 10))

    def test_trade_shortly_before_a_matching_event_is_flagged(self):
        links = self._link(date(2020, 1, 6), date(2020, 1, 10))
        self.assertEqual(len(links), 1)
        self.assertEqual(links.iloc[0]["trading_days_before"], 4)

    def test_boundary_is_inclusive_at_the_window_edge(self):
        # 2020-01-06 + 10 trading days = 2020-01-20
        self.assertEqual(len(self._link(date(2020, 1, 6), date(2020, 1, 20))), 1)

    def test_just_outside_the_window_is_not_flagged(self):
        self.assertEqual(len(self._link(date(2020, 1, 6), date(2020, 1, 21))), 0)

    def test_trade_after_the_event_is_never_flagged(self):
        self.assertEqual(len(self._link(date(2020, 1, 15), date(2020, 1, 10))), 0)

    def test_sector_must_match(self):
        self.assertEqual(
            len(self._link(date(2020, 1, 6), date(2020, 1, 10),
                           trade_sector="energy")), 0)

    def test_multi_sector_event_matches_any_listed_sector(self):
        links = self._link(date(2020, 1, 6), date(2020, 1, 10),
                           event_sectors="energy|defense")
        self.assertEqual(len(links), 1)
        self.assertEqual(links.iloc[0]["matched_sector"], "defense")

    def test_weekend_days_do_not_count_toward_the_window(self):
        links = self._link(date(2020, 1, 6), date(2020, 1, 13))
        self.assertEqual(links.iloc[0]["trading_days_before"], 5)
        self.assertEqual(links.iloc[0]["calendar_days_before"], 7)

    def test_unclassified_sector_never_matches(self):
        links = event_proximity.link_trades_to_events(
            positions(date(2020, 1, 6), sector=None),
            events(date(2020, 1, 10)), self.book, 10)
        self.assertTrue(links.empty)

    def test_no_events_yields_no_links(self):
        links = event_proximity.link_trades_to_events(
            positions(date(2020, 1, 6)), pd.DataFrame(), self.book, 10)
        self.assertTrue(links.empty)


class TestNearestEvent(unittest.TestCase):
    def test_closest_event_wins(self):
        links = pd.DataFrame([
            {"trade_id": "t1", "event_id": "far", "trading_days_before": 9},
            {"trade_id": "t1", "event_id": "near", "trading_days_before": 2},
        ])
        self.assertEqual(event_proximity.nearest_event_by_trade(links)["t1"],
                         ("near", 2))


class TestScoring(unittest.TestCase):
    def test_formula_string_matches_the_configured_weights(self):
        self.assertEqual(
            scoring.formula_text(WEIGHTS),
            "0.4*mean_alpha_vs_spy + 0.3*win_rate + "
            "0.2*median_alpha_vs_sector_etf + 0.1*event_proximity_rate")

    def test_score_equals_the_hand_computed_weighted_sum(self):
        df = pd.DataFrame([{
            "person_id": "a", "positions_analyzed": 10, "mean_alpha_vs_spy": 0.10,
            "win_rate": 0.60, "median_alpha_vs_sector_etf": 0.05,
            "event_proximity_rate": 0.20,
        }])
        got = scoring.compute_scores(df, WEIGHTS, min_trades=5)
        expected = 0.4 * 0.10 + 0.3 * 0.60 + 0.2 * 0.05 + 0.1 * 0.20
        self.assertAlmostEqual(got.iloc[0]["composite_score"], expected)

    def test_thin_records_are_excluded_from_the_ranking(self):
        df = pd.DataFrame([
            {"person_id": "thin", "positions_analyzed": 2, "mean_alpha_vs_spy": 9.0,
             "win_rate": 1.0, "median_alpha_vs_sector_etf": 9.0,
             "event_proximity_rate": 1.0},
            {"person_id": "thick", "positions_analyzed": 40, "mean_alpha_vs_spy": 0.05,
             "win_rate": 0.6, "median_alpha_vs_sector_etf": 0.02,
             "event_proximity_rate": 0.1},
        ])
        got = scoring.compute_scores(df, WEIGHTS, min_trades=5).set_index("person_id")
        self.assertFalse(got.loc["thin", "eligible_for_ranking"],
                         "a 2-trade record must not top the leaderboard")
        self.assertIsNone(got.loc["thin", "rank_composite"])
        self.assertEqual(got.loc["thick", "rank_composite"], 1)

    def test_missing_components_are_counted_not_hidden(self):
        df = pd.DataFrame([{
            "person_id": "a", "positions_analyzed": 10, "mean_alpha_vs_spy": 0.10,
            "win_rate": None, "median_alpha_vs_sector_etf": None,
            "event_proximity_rate": 0.0,
        }])
        got = scoring.compute_scores(df, WEIGHTS, min_trades=5)
        self.assertEqual(got.iloc[0]["score_components_present"], 2)
        self.assertAlmostEqual(got.iloc[0]["composite_score"], 0.04)

    def test_empty_input_is_handled(self):
        self.assertTrue(scoring.compute_scores(pd.DataFrame(), WEIGHTS, 5).empty)


if __name__ == "__main__":
    unittest.main()
