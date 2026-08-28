"""Return, benchmark and alpha math."""

import unittest
from datetime import date

import pandas as pd

from ptrack import returns


def book_from(series: dict[str, dict[date, float]]) -> returns.PriceBook:
    rows = [{"ticker": t, "date": d, "adj_close": p}
            for t, points in series.items() for d, p in points.items()]
    return returns.PriceBook(pd.DataFrame(rows))


# Mon 6th .. Fri 10th, then Mon 13th. The 11th/12th are a weekend and absent,
# which is what makes the trading-calendar lookups testable.
WEEK = {d: float(100 + i) for i, d in enumerate(
    [date(2020, 1, 6), date(2020, 1, 7), date(2020, 1, 8),
     date(2020, 1, 9), date(2020, 1, 10), date(2020, 1, 13)])}


class TestPriceBookLookups(unittest.TestCase):
    def setUp(self):
        self.book = book_from({"AAA": WEEK, "SPY": WEEK})

    def test_exact_date_returns_that_price(self):
        self.assertEqual(self.book.price_on_or_after("AAA", date(2020, 1, 8)), 102.0)

    def test_weekend_rolls_forward_to_next_trading_day(self):
        self.assertEqual(self.book.price_on_or_after("AAA", date(2020, 1, 11)), 105.0)

    def test_weekend_rolls_back_for_mark_to_last(self):
        self.assertEqual(self.book.price_on_or_before("AAA", date(2020, 1, 11)), 104.0)

    def test_date_beyond_the_series_has_no_forward_price(self):
        self.assertIsNone(self.book.price_on_or_after("AAA", date(2021, 1, 1)))

    def test_unknown_ticker_returns_none_rather_than_raising(self):
        self.assertIsNone(self.book.price_on_or_after("NOPE", date(2020, 1, 8)))
        self.assertFalse(self.book.has("NOPE"))

    def test_trading_days_ignore_the_weekend(self):
        self.assertEqual(
            self.book.trading_days_between(date(2020, 1, 9), date(2020, 1, 13)), 2)

    def test_trading_days_are_signed(self):
        self.assertEqual(
            self.book.trading_days_between(date(2020, 1, 13), date(2020, 1, 9)), -2)

    def test_empty_book_is_safe(self):
        empty = returns.PriceBook(pd.DataFrame())
        self.assertIsNone(empty.price_on_or_after("AAA", date(2020, 1, 6)))
        self.assertEqual(len(empty.calendar), 0)


class TestReturns(unittest.TestCase):
    def setUp(self):
        self.book = book_from({"AAA": WEEK, "SPY": WEEK})

    def test_long_return_is_the_raw_price_move(self):
        got = returns.position_return(self.book, "AAA", "long",
                                      date(2020, 1, 6), date(2020, 1, 10))
        self.assertAlmostEqual(got.value, 104 / 100 - 1)
        self.assertTrue(got.complete)

    def test_short_return_is_inverted(self):
        got = returns.position_return(self.book, "AAA", "short",
                                      date(2020, 1, 6), date(2020, 1, 10))
        self.assertAlmostEqual(got.value, -(104 / 100 - 1))

    def test_open_position_marks_to_the_last_available_price(self):
        got = returns.position_return(self.book, "AAA", "long", date(2020, 1, 6),
                                      date(2020, 1, 20), mark_to_last=True)
        self.assertAlmostEqual(got.value, 105 / 100 - 1)

    def test_missing_price_yields_no_return_and_is_incomplete(self):
        got = returns.position_return(self.book, "NOPE", "long",
                                      date(2020, 1, 6), date(2020, 1, 10))
        self.assertIsNone(got.value)
        self.assertFalse(got.complete)


class TestAlpha(unittest.TestCase):
    def test_alpha_is_excess_over_the_benchmark(self):
        self.assertAlmostEqual(returns.alpha(0.10, 0.04, "long"), 0.06)

    def test_matching_the_benchmark_is_zero_alpha(self):
        self.assertAlmostEqual(returns.alpha(0.04, 0.04, "long"), 0.0)

    def test_long_benchmark_mode_does_not_flip_for_shorts(self):
        self.assertAlmostEqual(returns.alpha(0.10, 0.04, "short"), 0.06)

    def test_sign_matched_mode_flips_the_benchmark_for_shorts(self):
        got = returns.alpha(0.10, 0.04, "short", mode=returns.SIGN_MATCHED)
        self.assertAlmostEqual(got, 0.14)

    def test_missing_inputs_propagate_as_none(self):
        self.assertIsNone(returns.alpha(None, 0.04, "long"))
        self.assertIsNone(returns.alpha(0.04, None, "long"))


class TestDisclosureDrift(unittest.TestCase):
    def test_drift_spans_trade_date_to_disclosure_date(self):
        book = book_from({"AAA": WEEK})
        got = returns.disclosure_drift(book, "AAA", "long",
                                       date(2020, 1, 6), date(2020, 1, 9))
        self.assertAlmostEqual(got, 103 / 100 - 1)

    def test_missing_disclosure_date_yields_none(self):
        book = book_from({"AAA": WEEK})
        self.assertIsNone(
            returns.disclosure_drift(book, "AAA", "long", date(2020, 1, 6), None))


class TestAggregates(unittest.TestCase):
    def test_none_values_are_excluded_not_treated_as_zero(self):
        self.assertAlmostEqual(returns.mean_of([0.1, None, 0.3]), 0.2)
        self.assertAlmostEqual(returns.median_of([0.1, None, 0.3, 0.5]), 0.3)

    def test_all_missing_yields_none(self):
        self.assertIsNone(returns.mean_of([None, None]))
        self.assertIsNone(returns.median_of([]))


if __name__ == "__main__":
    unittest.main()
