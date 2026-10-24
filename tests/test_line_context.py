import unittest
import pandas as pd
from api.line_context import line_context, CONVERGENCE_NOTE
from api.chart_analysis import analysis_text
from api.recommendations import check_symbol, recommendation_text, recommendation_pages


class LineContextTests(unittest.TestCase):
    def setUp(self):
        self.df = pd.DataFrame(dict(Open=102., High=103., Low=101., Close=102., Volume=1000),
                               index=pd.bdate_range("2026-01-01", periods=61))
        self.stock = dict(code="005930", name="시험종목")

    def trend(self, start, end):
        return dict(type="trendline", start_date=str(self.df.index[0].date()),
                    end_date=str(self.df.index[-1].date()), start_price=start, end_price=end)

    def test_within_five_percent_is_zone_not_resistance(self):
        ds = [self.trend(100, 100), self.trend(110, 104), dict(type="horizontal", price=120)]
        c = line_context(ds, self.df, 100)
        self.assertEqual(c["zone_count"], 2)
        self.assertEqual(c["resistance_price"], 120)
        self.assertTrue(c["converging"])

    def test_exact_five_percent_is_included(self):
        ds = [self.trend(100, 100), self.trend(105, 105), dict(type="horizontal", price=105.01)]
        c = line_context(ds, self.df, 100)
        self.assertEqual(c["zone_high"], 105)
        self.assertAlmostEqual(c["resistance_price"], 105.01)

    def test_parallel_or_diverging_or_already_crossed_are_not_converging(self):
        for ds in ([self.trend(100, 100), self.trend(104, 104)],
                   [self.trend(100, 100), self.trend(102, 104)],
                   [self.trend(100, 100), self.trend(110, 99)]):
            self.assertFalse(line_context(ds, self.df, 100)["converging"])

    def test_two_rising_lines_can_converge(self):
        self.assertTrue(line_context([self.trend(90, 100), self.trend(100, 104)], self.df, 100)["converging"])

    def test_lines_meeting_now_are_converging(self):
        c = line_context([self.trend(90, 100), self.trend(110, 100)], self.df, 100)
        self.assertEqual(c["zone_count"], 2)
        self.assertTrue(c["converging"])

    def test_no_outside_line_does_not_invent_target(self):
        self.assertIsNone(line_context([self.trend(100, 100), self.trend(110, 104)], self.df, 100)["resistance_price"])

    def test_nearby_chain_does_not_expand_zone_indefinitely(self):
        c = line_context([self.trend(100, 100), self.trend(104, 104), self.trend(108, 108)], self.df, 100)
        self.assertEqual(c["zone_high"], 104)
        self.assertEqual(c["resistance_price"], 108)

    def test_duplicates_do_not_fake_convergence(self):
        d = self.trend(90, 100)
        c = line_context([d, d], self.df, 100)
        self.assertEqual(c["zone_count"], 1)
        self.assertFalse(c["converging"])

    def test_recommendation_and_chart_share_target_and_note(self):
        self.df.loc[self.df.index[-1], "Close"] = 99.5
        ds = [self.trend(100, 100), self.trend(110, 104), dict(type="horizontal", price=120)]
        r = check_symbol(self.stock, ds, df=self.df)[0]
        self.assertEqual(r["resistance_price"], 120)
        self.assertAlmostEqual(r["expected_return_pct"], 20)
        scan = dict(results=[r], total=1, failed=0, dates=[], checked_at="test")
        text = recommendation_text(scan)
        self.assertIn(CONVERGENCE_NOTE, text)
        self.assertIn("선 밀집 구간", text)
        self.assertNotIn("저항선 104원", text)
        self.assertLessEqual(len(recommendation_pages(scan)[0][0]), 1000)
        for stock in (self.stock, dict(code="KOSPI", name="코스피")):
            text = analysis_text(stock, ds, self.df)
            self.assertIn(CONVERGENCE_NOTE, text)
            self.assertIn("선 밀집 구간", text)
            self.assertNotIn("저항선: 104", text)
