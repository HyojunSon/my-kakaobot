import unittest
from unittest.mock import patch
import pandas as pd
from api.chart_service import line_values, resolve_stock, render_chart, fetch_candles

class ChartTests(unittest.TestCase):
    def test_alias_catalog_and_no_ambiguous_tokens(self):
        from api.chart_service import load_snapshot
        data = load_snapshot()
        expected = {"삼전":"005930", "삼전우":"005935", "하닉":"000660",
                    "엘전":"066570", "엘전우":"066575", "네이버":"035420",
                    "코덱스 200":"069500"}
        for alias, code in expected.items():
            with self.subTest(alias=alias):
                self.assertEqual(resolve_stock(alias, data)["code"], code)
        owners = {}
        for stock in data["stocks"]:
            for token in (stock["name"], stock["code"], *stock.get("aliases", [])):
                key = "".join(token.split()).casefold()
                owners.setdefault(key, set()).add(stock["code"])
        self.assertTrue(all(len(codes) == 1 for codes in owners.values()))

    def test_bundled_font_contains_korean_title(self):
        from api.chart_service import ROOT
        from matplotlib.ft2font import FT2Font
        font = FT2Font(str(ROOT / "assets/chart-font.ttf"))
        for char in "이뮨온시아삼성전자":
            self.assertNotEqual(font.get_char_index(ord(char)), 0, char)

    def test_exact_name_and_code_only(self):
        data = {"stocks": [{"code":"424870", "name":"이뮨온시아"}]}
        self.assertEqual(resolve_stock("이뮨온시아", data)["code"], "424870")
        self.assertEqual(resolve_stock("424870", data)["name"], "이뮨온시아")
        self.assertIsNone(resolve_stock("이뮨", data))

    def test_trading_sessions_not_calendar_days(self):
        dates = {"2026-10-09":0, "2026-10-12":1, "2026-10-13":2}
        d = {"type":"trendline", "start_date":"2026-10-09", "end_date":"2026-10-12", "start_price":100, "end_price":110}
        self.assertEqual(line_values(d, dates, 0, 2), (100, 120))
        d["start_date"] = "2026-10-08"
        self.assertIsNone(line_values(d, dates, 0, 2))

    def test_provider_parsing(self):
        with patch("requests.get") as get:
            import requests
            response = requests.Response()
            response.status_code = 200
            response.encoding = "EUC-KR"
            response._content = ('<?xml version="1.0" encoding="EUC-KR" ?>'
                '<protocol><chartdata name="이뮨온시아"><item data="20261016|100|120|90|110|1000"/></chartdata></protocol>').encode("euc-kr")
            get.return_value = response
            df = fetch_candles("424870")
        self.assertEqual(df.Close.iloc[-1], 110)
        self.assertEqual(df.index[-1], pd.Timestamp("2026-10-16"))

    def test_fresh_fetch_on_each_image_and_png(self):
        dates = pd.bdate_range("2025-01-01", "2026-10-16")
        df = pd.DataFrame({"Open":100,"High":120,"Low":90,"Close":110,"Volume":1000},index=dates)
        stock = {"code":"424870","name":"이뮨온시아"}
        snapshot = {"drawings":{"424870":[{"type":"horizontal","price":105},
            {"type":"trendline","start_date":"2025-01-01","end_date":"2026-10-16","start_price":90,"end_price":115}]}}
        with patch("api.chart_service.fetch_candles",return_value=df) as fetch:
            for _ in range(2):
                png = render_chart(stock,snapshot)
                self.assertTrue(png.startswith(b'\x89PNG\r\n\x1a\n'))
            self.assertEqual(fetch.call_count,2)

class ApiTests(unittest.TestCase):
    def setUp(self):
        try:
            from fastapi.testclient import TestClient
            from api.index import app
        except ImportError:
            self.skipTest("Install FastAPI to run HTTP integration tests")
        self.client = TestClient(app)

    def test_abbreviated_chart_commands(self):
        for alias, code in [("삼전", "005930"), ("하닉", "000660"), ("엘전", "066570"),
                            ("코덱스200", "069500"), ("KODEX 200", "069500")]:
            with self.subTest(alias=alias):
                r = self.client.post("/api/chat", json={"userRequest": {"utterance": f"/차트 {alias}"}})
                self.assertIn(f"/api/chart/{code}.png?", r.json()["template"]["outputs"][0]["simpleImage"]["imageUrl"])

    def test_every_exported_stock_command_and_image_route(self):
        import json
        from api.chart_service import ROOT
        # Exercise each HTS export through HTTP; full catalog collision
        # coverage is handled separately without thousands of HTTP calls.
        exported = json.loads((ROOT / "data/hts_snapshot.json").read_text(encoding="utf-8"))
        for stock in exported["stocks"]:
            for query in {stock["code"], stock["name"]}:
                with self.subTest(code=stock["code"], query=query):
                    response = self.client.post("/api/chat", json={
                        "userRequest": {"utterance": f"/차트 {query}"}
                    })
                    self.assertEqual(response.status_code, 200)
                    outputs = response.json()["template"]["outputs"]
                    self.assertEqual(len(outputs), 1, outputs)
                    url = outputs[0]["simpleImage"]["imageUrl"]
                    self.assertIn(f"/api/chart/{stock['code']}.png?", url)
            with self.subTest(image=stock["code"]):
                with patch("api.index.render_chart", return_value=b"PNG") as render:
                    response = self.client.get(f"/api/chart/{stock['code']}.png")
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(render.call_args.args[0]["code"], stock["code"])

    def test_webhook_does_not_fetch_or_render(self):
        with patch("api.chart_service.fetch_candles") as fetch:
            response = self.client.post("/api/chat",json={"userRequest":{"utterance":"/차트 이뮨온시아"}})
        self.assertEqual(response.status_code,200)
        image = response.json()["template"]["outputs"][0]["simpleImage"]["imageUrl"]
        self.assertIn("/api/chart/424870.png?request=",image)
        fetch.assert_not_called()

    def test_image_route_and_error(self):
        with patch("api.index.render_chart",return_value=b"PNG"):
            r = self.client.get("/api/chart/424870.png")
            self.assertEqual(r.content,b"PNG")
            self.assertEqual(r.headers["content-type"],"image/png")
            self.assertEqual(r.headers["cache-control"],"no-store")
        with patch("api.index.render_chart",side_effect=ValueError("no data")):
            self.assertEqual(self.client.get("/api/chart/424870.png").status_code,502)

    def test_invalid_input(self):
        for body in ({}, {"userRequest":{"utterance":None}}, {"userRequest":{"utterance":"/차트 없는종목"}}):
            r = self.client.post("/api/chat",json=body)
            self.assertIn("simpleText",r.json()["template"]["outputs"][0])
        self.assertEqual(self.client.get("/api/chart/invalid.png").status_code,404)
