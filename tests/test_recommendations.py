import unittest
from unittest.mock import patch
import pandas as pd
from fastapi.testclient import TestClient
from api.index import app
from api.recommendations import check_symbol, scan_recommendations


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
            self.assertIsNone(check_symbol(self.stock, [self.line])[0])

    def test_resistance_and_recent_break_are_excluded(self):
        with patch("api.recommendations.fetch_candles", return_value=self.df):
            self.df.loc[self.df.index[-1], "Close"] = 99.9
            self.assertIsNone(check_symbol(self.stock, [self.line])[0])
            self.df.loc[self.df.index[-1], "Close"] = 100.5
            self.df.loc[self.df.index[-2], "Close"] = 99
            self.assertIsNone(check_symbol(self.stock, [self.line])[0])

    def test_nearby_line_without_bounce_history_is_excluded(self):
        self.df["Low"] = 101
        with patch("api.recommendations.fetch_candles", return_value=self.df):
            self.assertIsNone(check_symbol(self.stock, [self.line])[0])

    def test_prolonged_touch_counts_as_one_visit(self):
        self.df["Low"] = 101
        self.df.iloc[10:14] = [100.3, 100]
        with patch("api.recommendations.fetch_candles", return_value=self.df):
            self.assertIsNone(check_symbol(self.stock, [self.line])[0])

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
