import unittest
from unittest.mock import patch
from api.message_layout import short_bubbles, chart_bubbles, OPINION_HEADING
from api.index import recommendation_response, chart_response
from api.recommendations import recommendation_text, recommendation_pages


class MessageLayoutTests(unittest.TestCase):
    def test_wrapped_korean_rows_are_counted(self):
        chunks = short_bubbles("\n".join(["가"*40]*8))
        self.assertGreater(len(chunks), 1)
        self.assertEqual("\n".join(chunks), "\n".join(["가"*40]*8))

    def test_large_recommendation_list_has_no_silent_omissions(self):
        scan = {"results": [{"name":f"시험종목{i}", "code":f"{i:06}", "gap":.5, "support_tests":2} for i in range(50)],
                "total":50, "failed":0, "skipped":0, "dates":["2026-10-23"], "checked_at":"10-24 10:00"}
        expected = recommendation_pages(scan)
        pages = len(expected)
        collected = []
        for page in range(1, pages+1):
            response = recommendation_response(scan, page)["template"]
            self.assertEqual(len(response["outputs"]), 1)
            self.assertLessEqual(len(response["outputs"][0]["simpleText"]["text"]), 1000)
            collected.extend(output["simpleText"]["text"] for output in response["outputs"])
            if page < pages:
                self.assertIn(f"/종목추천 {page+1}", [r["messageText"] for r in response["quickReplies"]])
        self.assertEqual(collected, [text for text, _ in expected])
        for stock in scan["results"]:
            self.assertEqual(sum(f"({stock['code']})" in text for text in collected), 1)

    def test_recommendation_blocks_are_whole_and_quick_replies_match_page(self):
        stocks = [dict(name=f"종목{i}", code=f"{i:06}", position="below", current_price=99,
                       support_price=100, resistance_price=120, expected_return_pct=20,
                       support_status="awaiting_confirmation") for i in range(12)]
        scan = dict(results=stocks, dates=["2026-10-23"], total=12, failed=0, checked_at="10-24 10:00")
        pages = recommendation_pages(scan)
        self.assertGreater(len(pages), 1)
        for i, (text, group) in enumerate(pages, 1):
            response = recommendation_response(scan, i)["template"]
            for stock in group:
                self.assertIn(f"{stock['name']} ({stock['code']})", text)
            self.assertEqual(text.count("예상 수익률 +20.0%"), len(group))
            self.assertEqual([q["messageText"] for q in response["quickReplies"] if q["messageText"].startswith("/차트")],
                             ["/차트 "+s["code"] for s in group[:8]])
            self.assertNotIn("🟢", text)
            self.assertNotIn("🟠", text)

    def test_chart_splits_by_meaning_even_when_short(self):
        text = "【현재 상태】\n현재가 100원\n지지선 99원\n\n" + OPINION_HEADING + "\n매수: 안착 확인\n매도: 120원"
        with patch("api.index.analyze_chart", return_value=text):
            response = chart_response({"code":"005930", "name":"삼성전자"}, {}, "https://example.com/chart.png")
        outputs = response["template"]["outputs"]
        self.assertEqual(len(outputs), 3)
        self.assertIn("simpleImage", outputs[0])
        self.assertIn("현재가", outputs[1]["simpleText"]["text"])
        self.assertNotIn("매수:", outputs[1]["simpleText"]["text"])
        self.assertIn("매수:", outputs[2]["simpleText"]["text"])
        self.assertIn("매도:", outputs[2]["simpleText"]["text"])

    def test_long_status_does_not_push_out_opinions(self):
        status = "현재 상태\n" + "가격 확인\n"*70
        opinion = OPINION_HEADING + "\n매수 의견\n매도 의견\n계획 재검토"
        parts = chart_bubbles(status+opinion)
        self.assertEqual(parts, [status.strip(), opinion])
