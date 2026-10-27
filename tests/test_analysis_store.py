import copy
import unittest
from unittest.mock import Mock, patch
from api.analysis_store import fetch_analysis_rows, source_mode
from api.chart_service import load_snapshot


class AnalysisStoreTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict("os.environ", {"HTS_DATA_SOURCE": "supabase", "SUPABASE_URL": "https://test.supabase.co",
                                             "SUPABASE_SECRET_KEY": "sb_secret_test"})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_new_secret_is_not_sent_as_bearer_token(self):
        response = Mock(status_code=200, headers={"Content-Range": "*/0"})
        response.json.return_value = []
        with patch("api.analysis_store.requests.get", return_value=response) as get:
            self.assertEqual(fetch_analysis_rows(), [])
        headers = get.call_args.kwargs["headers"]
        self.assertNotIn("Authorization", headers)

    def test_paginate_by_symbol_even_if_server_page_cap_is_smaller(self):
        row = lambda code: dict(symbol=code, drawings=[], name=code, revision=1, updated_at="2026-10-27")
        a, b = Mock(status_code=200, headers={"Content-Range":"0-0/2"}), Mock(status_code=200, headers={"Content-Range":"0-0/1"})
        a.json.return_value, b.json.return_value = [row("000001")], [row("000002")]
        with patch("api.analysis_store.requests.get", side_effect=[a, b]) as get:
            self.assertEqual(len(fetch_analysis_rows()), 2)
        self.assertEqual(get.call_args.kwargs["params"]["symbol"], "gt.000001")

    def test_database_errors_are_not_treated_as_empty_data(self):
        with patch("api.analysis_store.requests.get", return_value=Mock(status_code=403)):
            with self.assertRaises(ValueError):
                fetch_analysis_rows()

    def test_fresh_database_rows_replace_snapshot_including_deleted_drawings(self):
        base = dict(stocks=[dict(code="005930", name="Samsung")], drawings={"005930":[{"old":True}]})
        before = copy.deepcopy(base)
        row = dict(symbol="005930", name="Samsung", drawings=[], revision=2, updated_at="2026-10-27")
        with patch("api.chart_service._file_snapshot", return_value=base), \
             patch("api.chart_service.fetch_analysis_rows", side_effect=[[row], []]) as fetch:
            self.assertEqual(load_snapshot()["drawings"]["005930"], [])
            self.assertEqual(load_snapshot()["drawings"], {})
            self.assertEqual(fetch.call_count, 2)
        self.assertEqual(base, before)

    def test_configured_database_failure_does_not_fall_back_to_git(self):
        with patch("api.chart_service.fetch_analysis_rows", side_effect=ValueError("unavailable")):
            with self.assertRaises(ValueError):
                load_snapshot()


if __name__ == "__main__":
    unittest.main()
