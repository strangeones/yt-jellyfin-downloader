import unittest
import os
from datetime import date
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient
from fastapi import HTTPException

os.environ["AUTH_DISABLED"] = "true"
from backend.main import (
    app,
    ChannelScanRequest,
    scan_channel_date_range,
    format_channel_entries,
)

class TestChannelDefaultAll(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_channel_scan_request_defaults(self):
        # When dates are not provided, they should default to None
        req = ChannelScanRequest(url="https://www.youtube.com/@testchannel")
        self.assertEqual(req.url, "https://www.youtube.com/@testchannel")
        self.assertIsNone(req.date_from)
        self.assertIsNone(req.date_to)
        self.assertEqual(req.media_types, ["all"])

        # When dates are passed as empty strings
        req_empty = ChannelScanRequest(url="https://www.youtube.com/@testchannel", date_from="", date_to="")
        self.assertEqual(req_empty.date_from, "")
        self.assertEqual(req_empty.date_to, "")

        # When only date_from is given
        req_from = ChannelScanRequest(url="https://www.youtube.com/@testchannel", date_from="2024-01-01")
        self.assertEqual(req_from.date_from, "2024-01-01")
        self.assertIsNone(req_from.date_to)

        # When only date_to is given
        req_to = ChannelScanRequest(url="https://www.youtube.com/@testchannel", date_to="2024-12-31")
        self.assertIsNone(req_to.date_from)
        self.assertEqual(req_to.date_to, "2024-12-31")

    def test_format_channel_entries(self):
        sample_entries = [
            {
                "id": "vid1",
                "title": "YouTube Video 1",
                "upload_date": "20230510"
            },
            {
                "id": "vid2",
                "url": "https://www.youtube.com/watch?v=vid2",
                "title": "YouTube Video 2",
                "upload_date": "20230615"
            },
            {
                "id": "tt1",
                "extractor": "tiktok",
                "uploader": "creator_name",
                "title": "TikTok Video 1",
                "upload_date": "20230720"
            },
            None,  # Invalid entry should be skipped
            "not a dict"
        ]
        formatted = format_channel_entries(sample_entries)
        self.assertEqual(len(formatted), 3)
        self.assertEqual(formatted[0]["id"], "vid1")
        self.assertEqual(formatted[0]["url"], "https://www.youtube.com/watch?v=vid1")
        self.assertEqual(formatted[0]["upload_date"], "2023-05-10")
        self.assertEqual(formatted[1]["url"], "https://www.youtube.com/watch?v=vid2")
        self.assertEqual(formatted[2]["url"], "https://www.tiktok.com/@creator_name/video/tt1")

    @patch("backend.main.scan_entries_date_range_pid")
    @patch("backend.main.fetch_channel_tab_entries")
    def test_scan_channel_both_dates_omitted(self, mock_fetch_tabs, mock_pid_scan):
        import asyncio

        mock_entries = [
            {"id": "v1", "title": "Video 1", "upload_date": "20240101"},
            {"id": "v2", "title": "Video 2", "upload_date": "20240201"},
        ]
        mock_fetch_tabs.return_value = ("Test Creator", mock_entries)

        req = ChannelScanRequest(url="https://www.youtube.com/@testcreator")
        res = asyncio.run(scan_channel_date_range(req))

        # PID logarithmic search must NOT be invoked when dates are omitted
        mock_pid_scan.assert_not_called()
        self.assertEqual(res["channel_title"], "Test Creator")
        self.assertEqual(res["count"], 2)
        self.assertEqual(res["date_from"], "All time")
        self.assertEqual(res["date_to"], "Present")
        self.assertEqual(len(res["items"]), 2)
        self.assertEqual(res["items"][0]["id"], "v1")
        self.assertEqual(res["items"][1]["id"], "v2")

    @patch("backend.main.scan_entries_date_range_pid")
    @patch("backend.main.fetch_channel_tab_entries")
    def test_scan_channel_both_dates_empty_string(self, mock_fetch_tabs, mock_pid_scan):
        import asyncio

        mock_entries = [
            {"id": "v1", "title": "Video 1", "upload_date": "20240101"},
        ]
        mock_fetch_tabs.return_value = ("Test Creator", mock_entries)

        req = ChannelScanRequest(url="https://www.youtube.com/@testcreator", date_from="", date_to="")
        res = asyncio.run(scan_channel_date_range(req))

        mock_pid_scan.assert_not_called()
        self.assertEqual(res["count"], 1)
        self.assertEqual(res["date_from"], "All time")
        self.assertEqual(res["date_to"], "Present")

    @patch("backend.main.scan_entries_date_range_pid")
    @patch("backend.main.fetch_channel_tab_entries")
    def test_scan_channel_only_date_from_given(self, mock_fetch_tabs, mock_pid_scan):
        import asyncio

        mock_fetch_tabs.return_value = ("Test Creator", [{"id": "v1"}])
        mock_pid_scan.return_value = [{"id": "v1", "url": "https://www.youtube.com/watch?v=v1", "title": "Video 1", "upload_date": "2024-03-01"}]

        req = ChannelScanRequest(url="https://www.youtube.com/@testcreator", date_from="2024-01-15")
        res = asyncio.run(scan_channel_date_range(req))

        # Should invoke PID scan with target_date_to defaulting to today
        self.assertTrue(mock_pid_scan.called)
        _, args, _ = mock_pid_scan.mock_calls[0]
        entries_arg, date_from_arg, date_to_arg = args
        self.assertEqual(date_from_arg, date(2024, 1, 15))
        self.assertEqual(date_to_arg, date.today())

        self.assertEqual(res["date_from"], "2024-01-15")
        self.assertEqual(res["date_to"], date.today().strftime("%Y-%m-%d"))

    @patch("backend.main.scan_entries_date_range_pid")
    @patch("backend.main.fetch_channel_tab_entries")
    def test_scan_channel_only_date_to_given(self, mock_fetch_tabs, mock_pid_scan):
        import asyncio

        mock_fetch_tabs.return_value = ("Test Creator", [{"id": "v1"}])
        mock_pid_scan.return_value = [{"id": "v1", "url": "https://www.youtube.com/watch?v=v1", "title": "Video 1", "upload_date": "2015-05-01"}]

        req = ChannelScanRequest(url="https://www.youtube.com/@testcreator", date_to="2020-01-01")
        res = asyncio.run(scan_channel_date_range(req))

        # Should invoke PID scan with target_date_from defaulting to 2005-01-01
        self.assertTrue(mock_pid_scan.called)
        _, args, _ = mock_pid_scan.mock_calls[0]
        entries_arg, date_from_arg, date_to_arg = args
        self.assertEqual(date_from_arg, date(2005, 1, 1))
        self.assertEqual(date_to_arg, date(2020, 1, 1))

        self.assertEqual(res["date_from"], "2005-01-01")
        self.assertEqual(res["date_to"], "2020-01-01")

    @patch("backend.main.scan_entries_date_range_pid")
    @patch("backend.main.fetch_channel_tab_entries")
    def test_scan_channel_both_dates_given(self, mock_fetch_tabs, mock_pid_scan):
        import asyncio

        mock_fetch_tabs.return_value = ("Test Creator", [{"id": "v1"}])
        mock_pid_scan.return_value = [{"id": "v1", "url": "https://www.youtube.com/watch?v=v1", "title": "Video 1", "upload_date": "2023-02-01"}]

        req = ChannelScanRequest(url="https://www.youtube.com/@testcreator", date_from="2023-01-01", date_to="2023-12-31")
        res = asyncio.run(scan_channel_date_range(req))

        self.assertTrue(mock_pid_scan.called)
        _, args, _ = mock_pid_scan.mock_calls[0]
        entries_arg, date_from_arg, date_to_arg = args
        self.assertEqual(date_from_arg, date(2023, 1, 1))
        self.assertEqual(date_to_arg, date(2023, 12, 31))

        self.assertEqual(res["date_from"], "2023-01-01")
        self.assertEqual(res["date_to"], "2023-12-31")

    def test_scan_channel_invalid_dates_reversed(self):
        import asyncio

        req = ChannelScanRequest(url="https://www.youtube.com/@testcreator", date_from="2024-05-01", date_to="2024-01-01")
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(scan_channel_date_range(req))
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("cannot be later than", ctx.exception.detail)

    @patch("backend.auth.validate_session", return_value="admin")
    @patch("backend.main.fetch_channel_tab_entries")
    def test_api_channel_scan_endpoint_defaults_all(self, mock_fetch_tabs, mock_auth):
        self.client.cookies.set("session_token", "valid_test_token")
        mock_fetch_tabs.return_value = (
            "Awesome Channel",
            [
                {"id": "vid_a", "title": "Vid A", "upload_date": "20240101"},
                {"id": "vid_b", "title": "Vid B", "upload_date": "20240201"},
            ]
        )

        # 1. No dates in JSON payload
        res = self.client.post("/api/channel-scan", json={
            "url": "https://www.youtube.com/@AwesomeChannel",
            "media_types": ["videos"]
        })
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertEqual(data["channel_title"], "Awesome Channel")
        self.assertEqual(data["count"], 2)
        self.assertEqual(data["date_from"], "All time")
        self.assertEqual(data["date_to"], "Present")
        self.assertEqual(len(data["items"]), 2)

        # 2. Empty string dates in JSON payload
        res_empty = self.client.post("/api/channel-scan", json={
            "url": "https://www.youtube.com/@AwesomeChannel",
            "date_from": "",
            "date_to": "",
            "media_types": ["videos"]
        })
        self.assertEqual(res_empty.status_code, 200)
        data_empty = res_empty.json()
        self.assertEqual(data_empty["date_from"], "All time")
        self.assertEqual(data_empty["date_to"], "Present")

        # 3. TikTok Creator with no dates
        mock_fetch_tabs.return_value = (
            "TikTok Creator",
            [{"id": "7106594312292453675", "uploader": "famous_tiktok", "title": "Viral TikTok", "upload_date": "20240301"}]
        )
        res_tt = self.client.post("/api/channel-scan", json={
            "url": "https://www.tiktok.com/@famous_tiktok"
        })
        self.assertEqual(res_tt.status_code, 200)
        data_tt = res_tt.json()
        self.assertEqual(data_tt["count"], 1)
        self.assertEqual(data_tt["date_from"], "All time")
        self.assertEqual(data_tt["date_to"], "Present")
        self.assertEqual(data_tt["items"][0]["url"], "https://www.tiktok.com/@famous_tiktok/video/7106594312292453675")

    @patch("backend.auth.validate_session", return_value="admin")
    @patch("backend.main.fetch_channel_tab_entries")
    def test_api_channel_scan_whitespace_dates(self, mock_fetch_tabs, mock_auth):
        self.client.cookies.set("session_token", "valid_test_token")
        mock_fetch_tabs.return_value = (
            "Awesome Channel",
            [{"id": "vid_1", "title": "Vid 1", "upload_date": "20240101"}]
        )
        res = self.client.post("/api/channel-scan", json={
            "url": "https://www.youtube.com/@AwesomeChannel",
            "date_from": "   ",
            "date_to": "   ",
            "media_types": ["videos"]
        })
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["date_from"], "All time")
        self.assertEqual(data["date_to"], "Present")
        self.assertEqual(data["count"], 1)

    @patch("backend.auth.validate_session", return_value="admin")
    def test_api_channel_scan_command_injection_safety(self, mock_auth):
        self.client.cookies.set("session_token", "valid_test_token")
        injection_payloads = [
            "2024-01-01; rm -rf /",
            "$(whoami)",
            "`cat /etc/passwd`",
            "| echo pwned",
            "\" && rm -rf /",
            "../../../etc/shadow",
            "2024-01-01\nrm -rf /",
        ]
        for payload in injection_payloads:
            # Injection in date_from
            res = self.client.post("/api/channel-scan", json={
                "url": "https://www.youtube.com/@AwesomeChannel",
                "date_from": payload,
            })
            self.assertEqual(res.status_code, 400, f"Expected 400 for date_from payload {payload}")
            self.assertIn("Unable to parse date string", res.json()["detail"])

            # Injection in date_to
            res = self.client.post("/api/channel-scan", json={
                "url": "https://www.youtube.com/@AwesomeChannel",
                "date_to": payload,
            })
            self.assertEqual(res.status_code, 400, f"Expected 400 for date_to payload {payload}")
            self.assertIn("Unable to parse date string", res.json()["detail"])

    @patch("backend.auth.validate_session", return_value="admin")
    def test_api_channel_scan_single_date_out_of_bounds(self, mock_auth):
        self.client.cookies.set("session_token", "valid_test_token")
        # Far future date_from with omitted date_to (which defaults to today)
        res = self.client.post("/api/channel-scan", json={
            "url": "https://www.youtube.com/@AwesomeChannel",
            "date_from": "2099-01-01",
        })
        self.assertEqual(res.status_code, 400)
        self.assertIn("From Date cannot be later than To Date", res.json()["detail"])

        # Pre-2005 date_to with omitted date_from (which defaults to 2005-01-01)
        res = self.client.post("/api/channel-scan", json={
            "url": "https://www.youtube.com/@AwesomeChannel",
            "date_to": "1999-01-01",
        })
        self.assertEqual(res.status_code, 400)
        self.assertIn("From Date cannot be later than To Date", res.json()["detail"])

    @patch("backend.auth.validate_session", return_value="admin")
    @patch("backend.main.fetch_channel_tab_entries")
    def test_api_channel_scan_tab_fallback_and_deduplication(self, mock_fetch_tabs, mock_auth):
        self.client.cookies.set("session_token", "valid_test_token")
        # Tab returns items with duplicates across tabs
        mock_fetch_tabs.side_effect = [
            ("Fallback Channel", [
                {"id": "dup_1", "title": "Dup Video 1", "upload_date": "20240101"},
                {"id": "unique_1", "title": "Unique 1", "upload_date": "20240102"},
            ]),
            ("Fallback Channel", [
                {"id": "dup_1", "title": "Dup Video 1 in Tab 2", "upload_date": "20240101"},
                {"id": "unique_2", "title": "Unique 2", "upload_date": "20240103"},
            ]),
            (None, []),
        ]
        res = self.client.post("/api/channel-scan", json={
            "url": "https://www.youtube.com/@FallbackChannel",
            "media_types": ["videos", "shorts", "streams"]
        })
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["count"], 3)
        self.assertEqual(len(data["items"]), 3)
        ids = [item["id"] for item in data["items"]]
        self.assertEqual(ids, ["dup_1", "unique_1", "unique_2"])

if __name__ == "__main__":
    unittest.main()

