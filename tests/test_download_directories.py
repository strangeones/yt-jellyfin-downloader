import os
import asyncio
import unittest
from unittest.mock import patch, MagicMock, AsyncMock

# Configure environment before importing application modules
os.environ["AUTH_DISABLED"] = "true"

from backend import main
from backend.main import (
    download_worker,
    process_queue,
    get_media_dir,
    is_valid_tiktok_url,
    is_valid_youtube_url,
)


class TestDownloadDirectories(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Create a clean event loop queue and lock for each test
        main.queue = asyncio.Queue()
        main.state_lock = asyncio.Lock()
        main.queued_tasks = []
        main.history = []
        main.current_task = None
        main.active_process = None

    async def asyncTearDown(self):
        tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        for t in tasks:
            t.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _process_task_with_mock(self, task: dict):
        """Helper to run download_worker on a single task and return (mock_exec, mock_makedirs)."""
        mock_proc = MagicMock()
        mock_proc.stdout.readline = AsyncMock(return_value=b"")
        mock_proc.wait = AsyncMock(return_value=0)
        mock_proc.returncode = 0

        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_proc)) as mock_exec, \
             patch("os.makedirs") as mock_makedirs:
            await main.queue.put(task)
            worker = asyncio.create_task(download_worker())
            await main.queue.join()
            worker.cancel()
            try:
                await worker
            except asyncio.CancelledError:
                pass

            return mock_exec, mock_makedirs

    # -------------------------------------------------------------------------
    # Helper Function: get_media_dir tests
    # -------------------------------------------------------------------------
    def test_get_media_dir_default(self):
        env_clean = {k: v for k, v in os.environ.items() if k not in ("MEDIA_DIR", "TIKTOK_MEDIA_DIR", "YOUTUBE_MEDIA_DIR")}
        with patch.dict(os.environ, env_clean, clear=True):
            # TikTok URLs
            self.assertEqual(get_media_dir("https://www.tiktok.com/@creator/video/123456"), "/app/media/tiktok")
            self.assertEqual(get_media_dir("https://www.tiktok.com/@creator"), "/app/media/tiktok")
            self.assertEqual(get_media_dir("https://vm.tiktok.com/ZM8rDqYxL/"), "/app/media/tiktok")

            # YouTube URLs
            self.assertEqual(get_media_dir("https://www.youtube.com/watch?v=dQw4w9WgXcQ"), "/app/media")
            self.assertEqual(get_media_dir("https://youtube.com/shorts/dQw4w9WgXcQ"), "/app/media")
            self.assertEqual(get_media_dir("https://www.youtube.com/@Veritasium"), "/app/media")

            # Fallback/Other
            self.assertEqual(get_media_dir("https://example.com/video.mp4"), "/app/media")

    def test_get_media_dir_custom_env_vars(self):
        # 1. Custom MEDIA_DIR
        with patch.dict(os.environ, {"MEDIA_DIR": "/custom/storage"}):
            self.assertEqual(get_media_dir("https://www.tiktok.com/@creator/video/123"), "/custom/storage/tiktok")
            self.assertEqual(get_media_dir("https://www.youtube.com/watch?v=123"), "/custom/storage")

        # 2. Custom TIKTOK_MEDIA_DIR
        with patch.dict(os.environ, {"TIKTOK_MEDIA_DIR": "/storage/tt"}):
            self.assertEqual(get_media_dir("https://www.tiktok.com/@creator/video/123"), "/storage/tt")
            self.assertEqual(get_media_dir("https://www.youtube.com/watch?v=123"), "/app/media")

        # 3. Custom YOUTUBE_MEDIA_DIR
        with patch.dict(os.environ, {"YOUTUBE_MEDIA_DIR": "/storage/yt"}):
            self.assertEqual(get_media_dir("https://www.tiktok.com/@creator/video/123"), "/app/media/tiktok")
            self.assertEqual(get_media_dir("https://www.youtube.com/watch?v=123"), "/storage/yt")

        # 4. Custom both
        with patch.dict(os.environ, {"TIKTOK_MEDIA_DIR": "/storage/tt", "YOUTUBE_MEDIA_DIR": "/storage/yt"}):
            self.assertEqual(get_media_dir("https://www.tiktok.com/@creator/video/123"), "/storage/tt")
            self.assertEqual(get_media_dir("https://www.youtube.com/watch?v=123"), "/storage/yt")

    # -------------------------------------------------------------------------
    # Default Environment: Routing & yt-dlp arguments in download_worker
    # -------------------------------------------------------------------------
    async def test_tiktok_video_default_routing(self):
        env_clean = {k: v for k, v in os.environ.items() if k not in ("MEDIA_DIR", "TIKTOK_MEDIA_DIR", "YOUTUBE_MEDIA_DIR")}
        with patch.dict(os.environ, env_clean, clear=True):
            task = {
                "id": "task_tt_1",
                "url": "https://www.tiktok.com/@creator/video/7106594312292453675",
                "metadata_fetched": True,
                "cancelled": False,
            }
            mock_exec, mock_makedirs = await self._process_task_with_mock(task)

            # Check os.makedirs was called for /app/media/tiktok
            mock_makedirs.assert_called_with("/app/media/tiktok", exist_ok=True)

            # Check yt-dlp arguments
            self.assertTrue(mock_exec.called)
            cmd = mock_exec.call_args[0]
            self.assertEqual(cmd[0], "yt-dlp")
            self.assertIn("-o", cmd)
            o_index = cmd.index("-o")
            template = cmd[o_index + 1]
            self.assertTrue(
                template.startswith("/app/media/tiktok/"),
                f"Expected template to start with /app/media/tiktok/, got: {template}",
            )
            self.assertEqual(
                template,
                "/app/media/tiktok/%(uploader,channel,creator,uploader_id)s - %(upload_date)s - %(title,id).120s [%(id)s].%(ext)s"
            )
            self.assertEqual(cmd[-1], task["url"])

    async def test_tiktok_creator_default_routing(self):
        env_clean = {k: v for k, v in os.environ.items() if k not in ("MEDIA_DIR", "TIKTOK_MEDIA_DIR", "YOUTUBE_MEDIA_DIR")}
        with patch.dict(os.environ, env_clean, clear=True):
            task = {
                "id": "task_tt_creator",
                "url": "https://www.tiktok.com/@charlidamelio",
                "metadata_fetched": True,
                "cancelled": False,
            }
            mock_exec, mock_makedirs = await self._process_task_with_mock(task)

            mock_makedirs.assert_called_with("/app/media/tiktok", exist_ok=True)
            cmd = mock_exec.call_args[0]
            o_index = cmd.index("-o")
            template = cmd[o_index + 1]
            self.assertTrue(template.startswith("/app/media/tiktok/"))

    async def test_tiktok_short_url_default_routing(self):
        env_clean = {k: v for k, v in os.environ.items() if k not in ("MEDIA_DIR", "TIKTOK_MEDIA_DIR", "YOUTUBE_MEDIA_DIR")}
        with patch.dict(os.environ, env_clean, clear=True):
            task = {
                "id": "task_tt_short",
                "url": "https://vm.tiktok.com/ZM8rDqYxL/",
                "metadata_fetched": True,
                "cancelled": False,
            }
            mock_exec, mock_makedirs = await self._process_task_with_mock(task)

            mock_makedirs.assert_called_with("/app/media/tiktok", exist_ok=True)
            cmd = mock_exec.call_args[0]
            o_index = cmd.index("-o")
            template = cmd[o_index + 1]
            self.assertTrue(template.startswith("/app/media/tiktok/"))

    async def test_youtube_video_default_routing(self):
        env_clean = {k: v for k, v in os.environ.items() if k not in ("MEDIA_DIR", "TIKTOK_MEDIA_DIR", "YOUTUBE_MEDIA_DIR")}
        with patch.dict(os.environ, env_clean, clear=True):
            task = {
                "id": "task_yt_1",
                "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "metadata_fetched": True,
                "cancelled": False,
            }
            mock_exec, mock_makedirs = await self._process_task_with_mock(task)

            # Check os.makedirs was called for /app/media
            mock_makedirs.assert_called_with("/app/media", exist_ok=True)

            # Check yt-dlp arguments
            self.assertTrue(mock_exec.called)
            cmd = mock_exec.call_args[0]
            self.assertEqual(cmd[0], "yt-dlp")
            self.assertIn("-o", cmd)
            o_index = cmd.index("-o")
            template = cmd[o_index + 1]
            self.assertTrue(
                template.startswith("/app/media/"),
                f"Expected template to start with /app/media/, got: {template}",
            )
            self.assertFalse(template.startswith("/app/media/tiktok/"))
            self.assertEqual(
                template,
                "/app/media/%(uploader,channel,creator,uploader_id)s - %(upload_date)s - %(title,id).120s [%(id)s].%(ext)s"
            )
            self.assertEqual(cmd[-1], task["url"])

    async def test_youtube_channel_default_routing(self):
        env_clean = {k: v for k, v in os.environ.items() if k not in ("MEDIA_DIR", "TIKTOK_MEDIA_DIR", "YOUTUBE_MEDIA_DIR")}
        with patch.dict(os.environ, env_clean, clear=True):
            task = {
                "id": "task_yt_channel",
                "url": "https://www.youtube.com/@Veritasium",
                "metadata_fetched": True,
                "cancelled": False,
            }
            mock_exec, mock_makedirs = await self._process_task_with_mock(task)

            mock_makedirs.assert_called_with("/app/media", exist_ok=True)
            cmd = mock_exec.call_args[0]
            o_index = cmd.index("-o")
            template = cmd[o_index + 1]
            self.assertTrue(template.startswith("/app/media/"))
            self.assertFalse(template.startswith("/app/media/tiktok/"))

    # -------------------------------------------------------------------------
    # Custom Environment Variables: Routing & yt-dlp arguments
    # -------------------------------------------------------------------------
    async def test_custom_media_base_dir(self):
        with patch.dict(os.environ, {"MEDIA_DIR": "/mnt/media_pool"}):
            # TikTok task
            tt_task = {
                "id": "task_tt_custom_base",
                "url": "https://www.tiktok.com/@creator/video/12345",
                "metadata_fetched": True,
                "cancelled": False,
            }
            mock_exec_tt, mock_makedirs_tt = await self._process_task_with_mock(tt_task)
            mock_makedirs_tt.assert_called_with("/mnt/media_pool/tiktok", exist_ok=True)
            cmd_tt = mock_exec_tt.call_args[0]
            template_tt = cmd_tt[cmd_tt.index("-o") + 1]
            self.assertTrue(template_tt.startswith("/mnt/media_pool/tiktok/"))

            # YouTube task
            yt_task = {
                "id": "task_yt_custom_base",
                "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "metadata_fetched": True,
                "cancelled": False,
            }
            mock_exec_yt, mock_makedirs_yt = await self._process_task_with_mock(yt_task)
            mock_makedirs_yt.assert_called_with("/mnt/media_pool", exist_ok=True)
            cmd_yt = mock_exec_yt.call_args[0]
            template_yt = cmd_yt[cmd_yt.index("-o") + 1]
            self.assertTrue(template_yt.startswith("/mnt/media_pool/"))
            self.assertFalse(template_yt.startswith("/mnt/media_pool/tiktok/"))

    async def test_custom_tiktok_media_dir(self):
        with patch.dict(os.environ, {"TIKTOK_MEDIA_DIR": "/fast_ssd/tiktok_videos"}):
            # TikTok task routes to custom TIKTOK_MEDIA_DIR
            tt_task = {
                "id": "task_tt_custom",
                "url": "https://www.tiktok.com/@creator/video/12345",
                "metadata_fetched": True,
                "cancelled": False,
            }
            mock_exec_tt, mock_makedirs_tt = await self._process_task_with_mock(tt_task)
            mock_makedirs_tt.assert_called_with("/fast_ssd/tiktok_videos", exist_ok=True)
            cmd_tt = mock_exec_tt.call_args[0]
            template_tt = cmd_tt[cmd_tt.index("-o") + 1]
            self.assertTrue(template_tt.startswith("/fast_ssd/tiktok_videos/"))

            # YouTube task still routes to default /app/media
            yt_task = {
                "id": "task_yt_default",
                "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "metadata_fetched": True,
                "cancelled": False,
            }
            mock_exec_yt, mock_makedirs_yt = await self._process_task_with_mock(yt_task)
            mock_makedirs_yt.assert_called_with("/app/media", exist_ok=True)
            cmd_yt = mock_exec_yt.call_args[0]
            template_yt = cmd_yt[cmd_yt.index("-o") + 1]
            self.assertTrue(template_yt.startswith("/app/media/"))

    async def test_custom_youtube_media_dir(self):
        with patch.dict(os.environ, {"YOUTUBE_MEDIA_DIR": "/hdd/youtube_library"}):
            # YouTube task routes to custom YOUTUBE_MEDIA_DIR
            yt_task = {
                "id": "task_yt_custom",
                "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "metadata_fetched": True,
                "cancelled": False,
            }
            mock_exec_yt, mock_makedirs_yt = await self._process_task_with_mock(yt_task)
            mock_makedirs_yt.assert_called_with("/hdd/youtube_library", exist_ok=True)
            cmd_yt = mock_exec_yt.call_args[0]
            template_yt = cmd_yt[cmd_yt.index("-o") + 1]
            self.assertTrue(template_yt.startswith("/hdd/youtube_library/"))

            # TikTok task still routes to default /app/media/tiktok
            tt_task = {
                "id": "task_tt_default",
                "url": "https://www.tiktok.com/@creator/video/12345",
                "metadata_fetched": True,
                "cancelled": False,
            }
            mock_exec_tt, mock_makedirs_tt = await self._process_task_with_mock(tt_task)
            mock_makedirs_tt.assert_called_with("/app/media/tiktok", exist_ok=True)
            cmd_tt = mock_exec_tt.call_args[0]
            template_tt = cmd_tt[cmd_tt.index("-o") + 1]
            self.assertTrue(template_tt.startswith("/app/media/tiktok/"))

    async def test_custom_both_tiktok_and_youtube_media_dirs(self):
        with patch.dict(os.environ, {
            "TIKTOK_MEDIA_DIR": "/volume1/media/tiktok",
            "YOUTUBE_MEDIA_DIR": "/volume1/media/youtube",
        }):
            # TikTok task
            tt_task = {
                "id": "task_tt_both",
                "url": "https://www.tiktok.com/@creator/video/99999",
                "metadata_fetched": True,
                "cancelled": False,
            }
            mock_exec_tt, mock_makedirs_tt = await self._process_task_with_mock(tt_task)
            mock_makedirs_tt.assert_called_with("/volume1/media/tiktok", exist_ok=True)
            cmd_tt = mock_exec_tt.call_args[0]
            template_tt = cmd_tt[cmd_tt.index("-o") + 1]
            self.assertTrue(template_tt.startswith("/volume1/media/tiktok/"))

            # YouTube task
            yt_task = {
                "id": "task_yt_both",
                "url": "https://www.youtube.com/watch?v=abcdef",
                "metadata_fetched": True,
                "cancelled": False,
            }
            mock_exec_yt, mock_makedirs_yt = await self._process_task_with_mock(yt_task)
            mock_makedirs_yt.assert_called_with("/volume1/media/youtube", exist_ok=True)
            cmd_yt = mock_exec_yt.call_args[0]
            template_yt = cmd_yt[cmd_yt.index("-o") + 1]
            self.assertTrue(template_yt.startswith("/volume1/media/youtube/"))

    # -------------------------------------------------------------------------
    # process_queue alias parity
    # -------------------------------------------------------------------------
    def test_process_queue_is_download_worker(self):
        self.assertIs(process_queue, download_worker)


if __name__ == "__main__":
    unittest.main()
