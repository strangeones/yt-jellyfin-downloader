import unittest
import os
import json
import re
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

# Set up test environment
os.environ["AUTH_DISABLED"] = "true"  # for test requests
from backend.main import (
    app,
    is_valid_youtube_url,
    is_valid_tiktok_url,
    is_valid_media_url,
    get_ytdlp_base_args,
    normalize_channel_url,
    determine_channel_tab_urls,
)

class TestTikTokSupport(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_url_validation_tiktok(self):
        valid_tiktok_urls = [
            "https://www.tiktok.com/@creator/video/7106594312292453675",
            "http://tiktok.com/@creator/video/7106594312292453675",
            "https://vm.tiktok.com/ZM8rDqYxL/",
            "https://vt.tiktok.com/ZSeXXXXXX/",
            "https://m.tiktok.com/v/7106594312292453675.html",
            "https://www.tiktok.com/t/ZT8rDqYxL/",
            "https://www.tiktok.com/@creator",
            "tiktok.com/@creator/video/12345",
            "www.tiktok.com/@creator",
        ]
        for url in valid_tiktok_urls:
            with self.subTest(url=url):
                self.assertTrue(is_valid_tiktok_url(url), f"Failed for {url}")
                self.assertTrue(is_valid_media_url(url), f"Failed media check for {url}")

    def test_url_validation_youtube(self):
        valid_youtube_urls = [
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "http://youtu.be/dQw4w9WgXcQ",
            "https://youtube.com/shorts/dQw4w9WgXcQ",
            "https://m.youtube.com/watch?v=dQw4w9WgXcQ",
            "https://www.youtube.com/@Veritasium",
            "youtube.com/watch?v=dQw4w9WgXcQ",
        ]
        for url in valid_youtube_urls:
            with self.subTest(url=url):
                self.assertTrue(is_valid_youtube_url(url), f"Failed for {url}")
                self.assertTrue(is_valid_media_url(url), f"Failed media check for {url}")

    def test_invalid_urls(self):
        invalid_urls = [
            "https://twitter.com/user/status/123456",
            "https://instagram.com/p/abcdef",
            "https://example.com/video.mp4",
            "random query string",
            "",
            "https://fake-tiktok.com.attacker.com/@user/video/123",
        ]
        for url in invalid_urls:
            with self.subTest(url=url):
                self.assertFalse(is_valid_tiktok_url(url), f"Should not match {url}")
                self.assertFalse(is_valid_media_url(url), f"Should not match media for {url}")

    def test_ytdlp_base_args(self):
        # Without cookies
        with patch("os.path.exists", return_value=False):
            args = get_ytdlp_base_args("https://www.tiktok.com/@test/video/1")
            self.assertNotIn("--cookies", args)

        # With cookies
        with patch("os.path.exists", return_value=True):
            args = get_ytdlp_base_args("https://www.tiktok.com/@test/video/1")
            self.assertIn("--cookies", args)
            self.assertIn("/app/data/cookies.txt", args)

        # With impersonate env
        with patch.dict(os.environ, {"TIKTOK_IMPERSONATE": "chrome"}):
            args = get_ytdlp_base_args("https://www.tiktok.com/@test/video/1")
            self.assertIn("--impersonate", args)
            self.assertIn("chrome", args)

    def test_normalize_channel_url(self):
        self.assertEqual(
            normalize_channel_url("https://www.tiktok.com/@creator"),
            "https://www.tiktok.com/@creator"
        )
        self.assertEqual(
            normalize_channel_url("tiktok.com/@creator/"),
            "https://tiktok.com/@creator"
        )
        self.assertEqual(
            normalize_channel_url("https://www.youtube.com/@veritasium/videos"),
            "https://www.youtube.com/@veritasium"
        )
        self.assertEqual(
            normalize_channel_url("@veritasium"),
            "https://www.youtube.com/@veritasium"
        )

    def test_determine_channel_tab_urls(self):
        # TikTok should return just the single url without /videos /shorts /streams
        tt_url = "https://www.tiktok.com/@creator"
        self.assertEqual(determine_channel_tab_urls(tt_url, ["all"]), [tt_url])
        self.assertEqual(determine_channel_tab_urls(tt_url, ["videos"]), [tt_url])

        # YouTube should return sub tabs
        yt_url = "https://www.youtube.com/@creator"
        yt_tabs = determine_channel_tab_urls(yt_url, ["all"])
        self.assertEqual(len(yt_tabs), 3)
        self.assertIn(f"{yt_url}/videos", yt_tabs)

    @patch("backend.auth.validate_session", return_value="admin")
    def test_api_download_endpoints(self, mock_auth):
        self.client.cookies.set("session_token", "valid_test_token")
        with patch("backend.main.fetch_metadata") as mock_fetch:
            # 1. Valid TikTok Video
            res = self.client.post("/api/download", json={
                "url": "https://www.tiktok.com/@test/video/7106594312292453675",
                "is_playlist": False
            })
            self.assertEqual(res.status_code, 200, res.text)
            data = res.json()
            self.assertIn("task_id", data)
            self.assertEqual(data.get("message"), "Added to queue")

            # 2. Valid YouTube Video
            res = self.client.post("/api/download", json={
                "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "is_playlist": False
            })
            self.assertEqual(res.status_code, 200)

            # 3. Invalid URL
            res = self.client.post("/api/download", json={
                "url": "https://vimeo.com/12345",
                "is_playlist": False
            })
            self.assertEqual(res.status_code, 400)
            self.assertIn("YouTube or TikTok", res.json()["detail"])

            # 4. Batch items with TikTok
            res = self.client.post("/api/download", json={
                "items": [
                    {"id": "7106594312292453675", "url": "https://www.tiktok.com/@test/video/7106594312292453675", "title": "TikTok Video"},
                    {"id": "dQw4w9WgXcQ", "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "title": "YT Video"},
                ]
            })
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res.json()["count"], 2)

    def test_frontend_regex_parity(self):
        # Emulate the frontend JS regexes:
        # isVideoUrl = /\/video\/|\/watch|\/shorts\/|youtu\.be\/|\/photo\/|vm\.tiktok\.com|vt\.tiktok\.com/
        # isPlaylistUrl = /[?&]list=|\/playlist|\/collection\//
        # isChannelUrl = !isVideoUrl && /\/(@|channel\/|c\/|user\/)/
        is_video = lambda url: bool(re.search(r'/video/|/watch|/shorts/|youtu\.be/|/photo/|vm\.tiktok\.com|vt\.tiktok\.com', url or ''))
        is_playlist = lambda url: bool(re.search(r'[?&]list=|/playlist|/collection/', url or ''))
        is_channel = lambda url: (not is_video(url)) and bool(re.search(r'/(@|channel/|c/|user/)', url or ''))

        # TikTok Video URL containing /@username/video/123 MUST be recognized as Video, NOT Channel
        tt_video = "https://www.tiktok.com/@someuser/video/7106594312292453675"
        self.assertTrue(is_video(tt_video))
        self.assertFalse(is_channel(tt_video), "TikTok video should NOT be classified as channel!")
        self.assertFalse(is_playlist(tt_video))

        # TikTok Creator Profile MUST be recognized as Channel
        tt_creator = "https://www.tiktok.com/@someuser"
        self.assertFalse(is_video(tt_creator))
        self.assertTrue(is_channel(tt_creator), "TikTok profile must be classified as channel!")

        # Short TikTok URL MUST be recognized as Video
        tt_short = "https://vm.tiktok.com/ZM8rDqYxL/"
        self.assertTrue(is_video(tt_short))
        self.assertFalse(is_channel(tt_short))

    @patch("backend.auth.validate_session", return_value="admin")
    def test_playlist_info_validation(self, mock_auth):
        self.client.cookies.set("session_token", "valid_test_token")
        # Invalid URL
        res = self.client.get("/api/playlist-info?url=https://vimeo.com/playlist/123")
        self.assertEqual(res.status_code, 400)
        self.assertIn("YouTube or TikTok", res.json()["detail"])

    @patch("backend.auth.validate_session", return_value="admin")
    def test_channel_scan_validation(self, mock_auth):
        self.client.cookies.set("session_token", "valid_test_token")
        # Invalid URL
        res = self.client.post("/api/channel-scan", json={
            "url": "https://vimeo.com/user/123",
            "date_from": "2024-01-01",
            "date_to": "2024-01-02",
            "media_types": ["all"]
        })
        self.assertEqual(res.status_code, 400)
        self.assertIn("YouTube or TikTok", res.json()["detail"])

    def test_tiktok_playlists_empty(self):
        import asyncio
        from backend.main import fetch_and_parse_channel_playlists
        res = asyncio.run(fetch_and_parse_channel_playlists("https://www.tiktok.com/@creator"))
        self.assertEqual(res["count"], 0)
        self.assertEqual(res["playlists"], [])

if __name__ == "__main__":
    unittest.main()
