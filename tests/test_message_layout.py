import unittest
from api.message_layout import short_bubbles
from api.index import recommendation_response
from api.recommendations import recommendation_text


class MessageLayoutTests(unittest.TestCase):
    def test_wrapped_korean_rows_are_counted(self):
        chunks = short_bubbles("\n".join(["가"*40]*8))
        self.assertGreater(len(chunks), 1)
        self.assertEqual("\n".join(chunks), "\n".join(["가"*40]*8))

    def test_large_recommendation_list_has_no_silent_omissions(self):
        scan = {"results": [{"name":f"시험종목{i}", "code":f"{i:06}", "gap":.5, "support_tests":2} for i in range(50)],
                "total":50, "failed":0, "skipped":0, "dates":["2026-10-23"], "checked_at":"10-24 10:00"}
        expected = short_bubbles(recommendation_text(scan))
        pages = (len(expected)+2)//3
        collected = []
        for page in range(1, pages+1):
            response = recommendation_response(scan, page)["template"]
            self.assertLessEqual(len(response["outputs"]), 3)
            collected.extend(output["simpleText"]["text"] for output in response["outputs"])
            if page < pages:
                self.assertIn(f"/종목추천 {page+1}", [r["messageText"] for r in response["quickReplies"]])
        self.assertEqual(collected, expected)
