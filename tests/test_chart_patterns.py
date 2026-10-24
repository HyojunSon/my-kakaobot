import unittest
import numpy as np
import pandas as pd
from api.chart_patterns import detect_pattern, pattern_messages
from api.chart_analysis import analysis_text
from api.message_layout import chart_bubbles
from api.recommendations import recommendation_pages


def sample(kind="symmetrical", state="forming"):
    x = np.arange(62)
    slopes = dict(symmetrical=(-.12, .12), ascending=(0, .22), descending=(-.22, 0),
                  rising_wedge=(.05, .22), falling_wedge=(-.22, -.05), parallel=(.05, .05))
    us, ls = slopes[kind]
    upper, lower = 112+us*x, 88+ls*x
    close = (upper+lower)/2+(upper-lower)/2*.98*np.sin(x*np.pi/6)
    df = pd.DataFrame(dict(Open=close, Close=close, High=close+.25, Low=close-.25,
                           Volume=np.linspace(2000, 800, len(x))),
                      index=pd.bdate_range("2026-01-01", periods=len(x)))
    for idx in (-2, -1):
        i = len(x)+idx
        c = float((upper[i]+lower[i])/2)
        if state == "up_attempt" and idx == -1 or state == "up_holding":
            c = float(upper[i]+2)
        elif state == "down_attempt" and idx == -1 or state == "down_holding":
            c = float(lower[i]-2)
        elif state == "failed_up" and idx == -2:
            c = float(upper[i]+2)
        df.iloc[i, df.columns.get_indexer(["Open", "Close", "High", "Low"])] = [c, c, c+.25, c-.25]
    drawings = [dict(type="trendline", start_date=str(df.index[0].date()),
                     end_date=str(df.index[59].date()), start_price=p, end_price=p+s*59)
                for p, s in ((112, us), (88, ls))]
    return df, drawings


class ChartPatternTests(unittest.TestCase):
    def test_five_shapes_with_actual_candle_contacts(self):
        for kind in ("ascending", "descending", "symmetrical", "rising_wedge", "falling_wedge"):
            with self.subTest(kind=kind):
                df, ds = sample(kind)
                result = detect_pattern(df, ds)
                self.assertIsNotNone(result)
                self.assertEqual(result["kind"], kind)
                self.assertGreaterEqual(result["upper_touches"], 2)
                self.assertGreaterEqual(result["lower_touches"], 2)

    def test_candle_only_discovery(self):
        df, _ = sample()
        self.assertEqual(detect_pattern(df)["kind"], "symmetrical")

    def test_parallel_lines_are_not_triangles(self):
        df, ds = sample("parallel")
        self.assertIsNone(detect_pattern(df, ds))

    def test_saved_shape_without_price_contacts_is_not_enough(self):
        df, ds = sample()
        df[["Open", "Close", "High", "Low"]] = [100, 100, 100.1, 99.9]
        self.assertIsNone(detect_pattern(df, ds))

    def test_latest_price_changes_state_not_formation(self):
        for state in ("up_attempt", "down_attempt", "up_holding", "down_holding", "failed_up"):
            with self.subTest(state=state):
                df, ds = sample(state=state)
                r = detect_pattern(df, ds)
                self.assertIsNotNone(r)
                self.assertEqual(r["state"], state)
                self.assertEqual(r["formation_end"], str(df.index[-3].date()))

    def test_volume_is_optional_and_not_a_hard_filter(self):
        df, ds = sample()
        r = detect_pattern(df, ds)
        self.assertTrue(r["volume_contracting"])
        self.assertIsNotNone(detect_pattern(df.drop(columns="Volume"), ds))

    def test_bad_or_short_data(self):
        df, ds = sample()
        self.assertIsNone(detect_pattern(df.iloc[:20], ds))
        df.iloc[30, df.columns.get_loc("Close")] = np.nan
        self.assertIsNone(detect_pattern(df, ds))

    def test_stock_and_index_have_semantic_pattern_opinions(self):
        df, ds = sample()
        for code in ("005930", "KOSPI"):
            text = analysis_text(dict(code=code, name="테스트"), ds, df)
            status, opinion = chart_bubbles(text)
            self.assertIn("대칭 삼각수렴", status)
            self.assertIn("패턴별 전망", opinion)
            self.assertIn("방향을 정하기 어려워요", opinion)
            self.assertLessEqual(len(status), 1000)
            self.assertLessEqual(len(opinion), 1000)

    def test_pattern_recommendation_fits_single_bubble(self):
        df, ds = sample()
        result = dict(code="005930", name="테스트", position="above", support_price=95,
                      resistance_price=120, expected_return_pct=26.3, current_price=96,
                      pattern=detect_pattern(df, ds))
        scan = dict(results=[result]*5, dates=["2026-10-23"], total=5, failed=0, checked_at="10-24 10:00")
        pages = recommendation_pages(scan)
        self.assertEqual(sum(len(stocks) for _, stocks in pages), 5)
        for text, _ in pages:
            self.assertLessEqual(len(text), 1000)
            self.assertIn("패턴별 전망", text)

    def test_pattern_names_never_claim_certainty(self):
        df, ds = sample("ascending")
        status, opinions = pattern_messages(detect_pattern(df, ds))
        self.assertIn("과 유사", status[0])
        self.assertIn("보장은 없어요", opinions[0])

    def test_downside_pattern_prioritizes_caution_in_stock_and_index(self):
        df, ds = sample(state="down_holding")
        for code in ("005930", "KOSPI"):
            text = analysis_text(dict(code=code, name="테스트"), ds, df)
            self.assertIn("서두르지 마세요", text)
            self.assertNotIn("사고 싶다면", text)


if __name__ == "__main__":
    unittest.main()
