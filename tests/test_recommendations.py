import unittest
from unittest.mock import patch
import pandas as pd
from fastapi.testclient import TestClient
from api.index import app
from api.recommendations import check_symbol, scan_recommendations, support_evidence


class RecommendationTests(unittest.TestCase):
    def setUp(self):
        self.df = pd.DataFrame({"Close": 102.0, "Low": 101.0}, index=pd.bdate_range("2026-08-01", periods=41))
        for idx in (10, 20):
            self.df.iloc[idx] = [100.3, 100.0]
        self.df.iloc[-1] = [101.0, 100.5]
        self.stock = {"code": "005930", "name": "삼성전자"}
        self.line = {"type": "trendline", "start_date": str(self.df.index[0].date()), "end_date": str(self.df.index[1].date()),
                     "start_price": 100, "end_price": 100}

    def test_boundary_and_deduplicate_lines(self):
        with patch("api.recommendations.fetch_candles", return_value=self.df):
            result, skipped, _ = check_symbol(self.stock, [self.line, self.line])
            self.assertAlmostEqual(result["gap"], 1)
            self.assertEqual(skipped, 0)
            self.assertEqual(result["support_tests"], 2)
            self.df.loc[self.df.index[-1], "Close"] = 101.01
            self.assertIsNone(check_symbol(self.stock, [self.line])[0])
            self.df.loc[self.df.index[-1], "Close"] = 99
            result = check_symbol(self.stock, [self.line])[0]
            self.assertAlmostEqual(result["gap"], -1)
            self.assertEqual(result["position"], "below")
            self.df.loc[self.df.index[-1], "Close"] = 98.99
            self.assertIsNone(check_symbol(self.stock, [self.line])[0])

    def test_below_support_can_pass_but_recent_break_is_excluded(self):
        with patch("api.recommendations.fetch_candles", return_value=self.df):
            self.df.loc[self.df.index[-1], "Close"] = 99.9
            self.assertEqual(check_symbol(self.stock, [self.line])[0]["position"], "below")
            self.df.loc[self.df.index[-1], "Close"] = 100.5
            self.df.loc[self.df.index[-2], "Close"] = 99
            self.assertIsNone(check_symbol(self.stock, [self.line])[0])

    def test_return_uses_support_entry_not_current_price(self):
        from api.recommendations import recommendation_text
        resistance = {"type":"horizontal", "price":120}
        with patch("api.recommendations.fetch_candles", return_value=self.df):
            result = check_symbol(self.stock, [self.line, resistance])[0]
            self.assertEqual(result["support_price"], 100)
            self.assertEqual(result["resistance_price"], 120)
            self.assertAlmostEqual(result["expected_return_pct"], 20)
            scan = {"results":[result], "dates":[], "total":1,"failed":0,"skipped":0,"checked_at":"test"}
            self.assertIn("지지선 위", recommendation_text(scan))
            self.df.loc[self.df.index[-1], "Close"] = 99.5
            scan["results"] = [check_symbol(self.stock, [self.line, resistance])[0]]
        self.assertIn("지지선 소폭 이탈", recommendation_text(scan))

    def test_no_upper_line_does_not_invent_return(self):
        with patch("api.recommendations.fetch_candles", return_value=self.df):
            result = check_symbol(self.stock, [self.line])[0]
        self.assertIsNone(result["expected_return_pct"])
        self.assertIsNone(result["resistance_price"])

    def test_nearest_support_is_by_absolute_distance(self):
        higher = {**self.line, "start_price":100.5, "end_price":100.5}
        self.df.loc[self.df.index[-1], "Close"] = 100.1
        with patch("api.recommendations.fetch_candles", return_value=self.df), \
             patch("api.recommendations.support_evidence", return_value={"support_tests":2,"held_ratio":1}):
            result = check_symbol(self.stock, [higher, self.line])[0]
        self.assertEqual(result["support_price"], 100)

    def test_approach_without_bounce_is_waiting_candidate(self):
        self.df["Low"] = 101
        with patch("api.recommendations.fetch_candles", return_value=self.df):
            result = check_symbol(self.stock, [self.line])[0]
            self.assertEqual(result["support_status"], "awaiting_confirmation")
            self.assertEqual(result["support_tests"], 0)

    def test_prolonged_touch_counts_as_one_visit(self):
        self.df["Low"] = 101
        self.df.iloc[10:13] = [100.3, 100]
        with patch("api.recommendations.fetch_candles", return_value=self.df):
            self.assertEqual(check_symbol(self.stock, [self.line])[0]["support_tests"], 1)

    def test_former_resistance_can_become_support(self):
        self.df.iloc[:28] = [95, 94]
        self.df.iloc[28:] = [102, 101]
        self.df.iloc[33] = [100.3, 100]
        self.df.iloc[-1] = [99.5, 99]
        result = check_symbol(self.stock, [self.line], df=self.df)[0]
        self.assertIsNotNone(result)
        self.assertEqual(result["support_tests"], 1)
        self.assertEqual(result["position"], "below")

    def test_breakout_without_retest_is_not_confirmed_support(self):
        self.df.iloc[:28] = [95, 94]
        self.df.iloc[28:] = [102, 101]
        self.df.iloc[-1] = [100.5, 100]
        self.assertEqual(check_symbol(self.stock, [self.line], df=self.df)[0]["support_status"],
                         "awaiting_confirmation")

    def test_two_small_closing_breaks_reset_old_support(self):
        self.df.iloc[-4:-2] = [99.4, 99]
        self.df.iloc[-2] = [102, 101]
        self.assertIsNone(check_symbol(self.stock, [self.line], df=self.df)[0])

    def test_new_retest_after_break_reestablishes_support(self):
        self.df.iloc[25] = [98, 97]
        self.df.iloc[31] = [100.3, 100]
        result = check_symbol(self.stock, [self.line], df=self.df)[0]
        self.assertIsNotNone(result)
        self.assertEqual(result["support_tests"], 1)

    def test_old_bounce_expires(self):
        self.df = pd.DataFrame({"Close": 102.0, "Low": 101.0},
                               index=pd.bdate_range("2026-08-01", periods=80))
        self.df.iloc[25] = [100.3, 100]
        self.df.iloc[-4:-1] = [99.8, 99.6]
        self.df.iloc[-1] = [100.5, 100]
        self.assertIsNone(check_symbol(self.stock, [self.line], df=self.df)[0])

    def test_latest_bar_cannot_confirm_bounce(self):
        self.df["Low"] = 101
        self.df.iloc[-2] = [100.3, 100]
        self.df.iloc[-1] = [101, 100]
        result = check_symbol(self.stock, [self.line], df=self.df)[0]
        self.assertEqual(result["support_status"], "awaiting_confirmation")
        self.assertEqual(result["support_tests"], 0)

    def test_recent_second_anchor_does_not_block_current_screening(self):
        self.line["end_date"] = str(self.df.index[-2].date())
        result = check_symbol(self.stock, [self.line], df=self.df)[0]
        self.assertIsNotNone(result)

    def test_approach_from_below_is_not_support_candidate(self):
        self.df.iloc[:] = [99.8, 99.6]
        self.df.iloc[-1] = [99.9, 99.5]
        self.assertIsNone(check_symbol(self.stock, [self.line], df=self.df)[0])

    def test_short_history_cannot_establish_support(self):
        with patch("api.recommendations.fetch_candles", return_value=self.df.iloc[:10]):
            self.assertIsNone(check_symbol(self.stock, [self.line])[0])

    def test_sloping_support_uses_each_sessions_line_price(self):
        for i in range(len(self.df)):
            self.df.iloc[i] *= 1+i*.001
        self.line["end_price"] = 100.1
        with patch("api.recommendations.fetch_candles", return_value=self.df):
            result, _, _ = check_symbol(self.stock, [self.line])
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result["gap"], 1)

    def test_missing_anchor_is_not_guessed(self):
        self.line["start_date"] = "2000-01-01"
        with patch("api.recommendations.fetch_candles", return_value=self.df):
            result, skipped, _ = check_symbol(self.stock, [self.line])
        self.assertIsNone(result)
        self.assertEqual(skipped, 1)

    def test_indices_horizontal_and_fetch_failure(self):
        snapshot = {"stocks": [self.stock, {"code": "KOSPI", "name": "코스피"}, {"code": "000660", "name": "SK하이닉스"}],
                    "drawings": {"005930": [self.line], "KOSPI": [self.line], "000660": [{"type": "horizontal", "price": 100}]}}
        with patch("api.recommendations.fetch_candles", side_effect=ValueError("unavailable")) as fetch:
            scan = scan_recommendations(snapshot)
        self.assertEqual(scan["total"], 1)
        self.assertEqual(scan["failed"], 1)
        self.assertEqual(fetch.call_count, 1)

    def test_command_returns_names(self):
        result = {"results": [{"name": "대우건설", "code": "047040", "gap": .5}],
                  "total": 1, "failed": 0, "skipped": 0, "dates": ["2026-10-19"], "checked_at": "10-19 15:00"}
        with patch("api.recommendations.scan_recommendations", return_value=result):
            response = TestClient(app).post("/api/chat", json={"userRequest": {"utterance": "/종목추천"}})
        self.assertEqual(response.status_code, 200)
        self.assertIn("대우건설", response.json()["template"]["outputs"][0]["simpleText"]["text"])

    def test_callback_accepts_without_inline_scan(self):
        with patch("api.index.send_recommendations") as send, patch("api.recommendations.scan_recommendations") as scan:
            response = TestClient(app).post("/api/chat", json={"userRequest": {
                "utterance": "/종목추천", "callbackUrl": "https://bot-api.kakao.com/callback/test"}})
        self.assertEqual(response.json(), {"version": "2.0", "useCallback": True})
        send.assert_called_once()
        scan.assert_not_called()

    def test_callback_rejects_foreign_host(self):
        with patch("api.index.send_recommendations") as send:
            response = TestClient(app).post("/api/chat", json={"userRequest": {
                "utterance": "/종목추천", "callbackUrl": "https://example.com/callback"}})
        self.assertIn("simpleText", response.json()["template"]["outputs"][0])
        send.assert_not_called()
