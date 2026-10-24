import unittest
from unittest.mock import patch
import pandas as pd
from fastapi.testclient import TestClient
from api.index import app
from api.chart_analysis import analysis_text


class AnalysisTests(unittest.TestCase):
    def test_indices_give_market_exposure_guidance(self):
        lines = [{"type": "horizontal", "price": 99}, {"type": "horizontal", "price": 120}]
        for code, name in [("KOSPI", "코스피"), ("KOSDAQ", "코스닥")]:
            text = analysis_text({"code":code, "name":name}, lines, self.df)
            self.assertIn("시장 리포트", text)
            self.assertIn("주식 매수:", text)
            self.assertIn("보유 주식:", text)
            self.assertIn("99.00pt", text)
            self.assertIn("개별 주식의 매도 가격은 아니에요", text)
            self.assertNotIn(name+"을 사고", text)
            self.assertNotIn("수수료", text)
            self.assertLess(len(text), 840)

    def test_index_without_lines_does_not_invent_levels(self):
        text = analysis_text({"code":"KOSPI", "name":"코스피"}, [], self.df)
        self.assertIn("선이 부족해요", text)
        self.assertNotIn("아래에서 장을 마치면", text)

    def setUp(self):
        self.stock = {"code": "005930", "name": "삼성전자"}
        self.df = pd.DataFrame({"Open": 100, "High": 102, "Low": 98, "Close": 100, "Volume": 1000},
                               index=pd.bdate_range("2026-01-01", periods=30))

    def test_support_resistance_price_scenario(self):
        lines = [{"type": "horizontal", "price": 99}, {"type": "horizontal", "price": 120}]
        text = analysis_text(self.stock, lines, self.df)
        self.assertIn("사고 싶다면", text)
        self.assertIn("120원", text)
        self.assertIn("계획을 다시 세워야 해요", text)
        self.assertLess(len(text), 420)

    def test_recommended_support_below_price_is_not_relabeled_resistance(self):
        dates = self.df.index
        drawing = {"type": "trendline", "id": "support",
                   "start_date": str(dates[0].date()), "end_date": str(dates[10].date()),
                   "start_price": 100, "end_price": 100}
        df = self.df.copy()
        df["Close"] = 101.0
        df["Low"] = 100
        df.loc[dates[-1], "Close"] = 99.5
        text = analysis_text(self.stock, [drawing, {"type": "horizontal", "price": 120}], df)
        self.assertIn("🟢 지지선: 100원", text)
        self.assertIn("🔴 저항선: 120원", text)
        self.assertIn("회복", text)
        self.assertIn("+20.0%", text)
        self.assertNotIn("🟢 지지선: 확인할 선 없음", text)

    def test_no_lines_does_not_invent_prices(self):
        text = analysis_text(self.stock, [], self.df)
        self.assertIn("제안하기 어려워요", text)
        self.assertNotIn("사고 싶으신가요?", text)

    def test_break_uses_previous_line_price(self):
        d = {"type":"trendline", "start_date":str(self.df.index[-2].date()),
             "end_date":str(self.df.index[-1].date()), "start_price":101, "end_price":99}
        text = analysis_text(self.stock, [d], self.df)
        self.assertIn("가격이 선 위로 올라왔어요", text)

    def test_short_history_and_missing_anchor(self):
        self.assertIn("부족", analysis_text(self.stock, [], self.df.iloc[:1]))
        text = analysis_text(self.stock, [{"type":"trendline", "start_date":"2000-01-01", "end_date":"2000-02-01", "start_price":90,"end_price":100}],self.df)
        self.assertIn("선 1개는 제외했어요", text)

    def test_chart_text_and_callback(self):
        client = TestClient(app)
        with patch("api.index.analyze_chart", return_value="지지 후보 100원"):
            r = client.post("/api/chat", json={"userRequest":{"utterance":"/차트 삼성전자"}})
        outputs = r.json()["template"]["outputs"]
        self.assertIn("simpleImage", outputs[0])
        self.assertIn("지지 후보", outputs[1]["simpleText"]["text"])
        with patch("api.index.send_chart_analysis") as send:
            r = client.post("/api/chat", json={"userRequest":{"utterance":"/차트 삼성전자", "callbackUrl":"https://bot-api.kakao.com/callback/test"}})
        self.assertTrue(r.json()["useCallback"])
        send.assert_called_once()
