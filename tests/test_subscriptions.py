import os
import json
import tempfile
import asyncio
import unittest
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi.testclient import TestClient

from backend import subscriptions
from backend.subscriptions import SubscriptionManager
from backend import main
from backend import auth


class TestSubscriptions(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Create temp file for subscriptions
        self.temp_dir = tempfile.TemporaryDirectory()
        self.sub_file = os.path.join(self.temp_dir.name, "subscriptions.json")
        self.manager = SubscriptionManager(file_path=self.sub_file)

        # Set up test user session for authenticated endpoints
        self.auth_temp_dir = tempfile.TemporaryDirectory()
        auth_file = os.path.join(self.auth_temp_dir.name, "auth.json")
        with patch.object(auth, "get_auth_file_path", return_value=auth_file):
            auth.setup_credentials("testuser", "testpassword123")
            token = auth.create_session("testuser")
            self.session_cookie = {"session_token": token}

        # Patch global subscription manager in main and subscriptions module
        self.patcher1 = patch.object(subscriptions, "subscription_manager", self.manager)
        self.patcher1.start()

        # Initialize event loop queue and lock
        main.queue = asyncio.Queue()
        main.state_lock = asyncio.Lock()
        main.queued_tasks = []
        main.history = []
        main.current_task = None
        main.active_process = None

        self.client = TestClient(main.app, cookies=self.session_cookie)

    async def asyncTearDown(self):
        self.patcher1.stop()
        self.temp_dir.cleanup()
        self.auth_temp_dir.cleanup()

    async def test_add_and_list_subscriptions(self):
        """Test adding subscriptions and listing them."""
        sub1 = await self.manager.add_subscription(
            url="https://www.youtube.com/@Veritasium",
            title="Veritasium",
            platform="youtube",
            avatar_url="https://example.com/v.jpg",
            channel_id="UCHnyfMqiRRG1u-2MsSQLbXA"
        )
        self.assertIsNotNone(sub1.get("id"))
        self.assertEqual(sub1["title"], "Veritasium")
        self.assertEqual(sub1["platform"], "youtube")
        self.assertEqual(sub1["interval_seconds"], 60)
        self.assertTrue(sub1["enabled"])
        self.assertEqual(sub1["seen_ids"], [])

        # Add TikTok sub with default 15s interval
        sub2 = await self.manager.add_subscription(
            url="https://www.tiktok.com/@creator",
            title="Creator",
            platform="tiktok"
        )
        self.assertEqual(sub2["interval_seconds"], 15)
        self.assertEqual(sub2["platform"], "tiktok")

        all_subs = await self.manager.list_subscriptions()
        self.assertEqual(len(all_subs), 2)

    async def test_persistence_atomic_save_load(self):
        """Test that data is atomically persisted and loaded from JSON disk."""
        await self.manager.add_subscription(
            url="https://www.youtube.com/@3blue1brown",
            title="3Blue1Brown",
            platform="youtube"
        )
        self.assertTrue(os.path.exists(self.sub_file))

        # Check raw json
        with open(self.sub_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["title"], "3Blue1Brown")

        # Create new manager pointing to same file and verify load
        new_manager = SubscriptionManager(file_path=self.sub_file)
        loaded = await new_manager.list_subscriptions()
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["title"], "3Blue1Brown")

    async def test_update_and_toggle_subscription(self):
        """Test updating enabled status and interval."""
        sub = await self.manager.add_subscription(
            url="https://www.youtube.com/@TED",
            title="TED"
        )
        sub_id = sub["id"]

        # Pause
        updated = await self.manager.update_subscription(sub_id, enabled=False, interval_seconds=120)
        self.assertFalse(updated["enabled"])
        self.assertEqual(updated["interval_seconds"], 120)

        # Resume
        resumed = await self.manager.update_subscription(sub_id, enabled=True)
        self.assertTrue(resumed["enabled"])

    async def test_delete_subscription(self):
        """Test deleting subscription."""
        sub = await self.manager.add_subscription(
            url="https://www.youtube.com/@TED",
            title="TED"
        )
        sub_id = sub["id"]
        deleted = await self.manager.delete_subscription(sub_id)
        self.assertTrue(deleted)

        remaining = await self.manager.list_subscriptions()
        self.assertEqual(len(remaining), 0)

        # Deleting non-existent returns False
        self.assertFalse(await self.manager.delete_subscription("nonexistent"))

    async def test_seen_ids_deduplication(self):
        """Test adding seen IDs and deduplication."""
        sub = await self.manager.add_subscription(
            url="https://www.youtube.com/@TED",
            title="TED"
        )
        sub_id = sub["id"]

        # Add initial seen IDs
        updated = await self.manager.add_seen_ids(sub_id, ["vid1", "vid2"])
        self.assertEqual(updated["seen_ids"], ["vid1", "vid2"])
        self.assertIsNotNone(updated["last_checked"])

        # Add overlapping seen IDs
        updated2 = await self.manager.add_seen_ids(sub_id, ["vid2", "vid3"])
        self.assertEqual(updated2["seen_ids"], ["vid1", "vid2", "vid3"])

    async def test_check_and_enqueue_detection_of_new_videos(self):
        """Test mock detection of new unseen videos enqueues them into queue."""
        sub = await self.manager.add_subscription(
            url="https://www.youtube.com/@TED",
            title="TED",
            platform="youtube"
        )
        # Mark vid1 and vid2 as already seen
        await self.manager.add_seen_ids(sub["id"], ["vid1", "vid2"])
        sub = await self.manager.get_subscription(sub["id"])

        mock_items = [
            {"id": "vid3", "url": "https://www.youtube.com/watch?v=vid3", "title": "Video 3"},
            {"id": "vid2", "url": "https://www.youtube.com/watch?v=vid2", "title": "Video 2"},
            {"id": "vid1", "url": "https://www.youtube.com/watch?v=vid1", "title": "Video 1"},
        ]

        with patch.object(subscriptions, "check_subscription_new_videos", new=AsyncMock(return_value=mock_items)):
            new_count = await main.check_and_enqueue_subscription(sub)
            self.assertEqual(new_count, 1)

            # Check queue received vid3
            self.assertFalse(main.queue.empty())
            task = await main.queue.get()
            self.assertEqual(task["url"], "https://www.youtube.com/watch?v=vid3")
            self.assertEqual(task["title"], "Video 3")

            # Check subscription now has vid3 in seen_ids
            updated_sub = await self.manager.get_subscription(sub["id"])
            self.assertIn("vid3", updated_sub["seen_ids"])

    def test_api_rest_endpoints(self):
        """Integration test for /api/subscriptions REST endpoints."""
        mock_meta = {
            "title": "Veritasium",
            "avatar_url": "https://yt3.ggpht.com/avatar.jpg",
            "channel_id": "UCHnyfMqiRRG1u-2MsSQLbXA",
            "platform": "youtube",
            "url": "https://www.youtube.com/@Veritasium"
        }

        with patch.object(subscriptions, "extract_channel_metadata", new=AsyncMock(return_value=mock_meta)), \
             patch.object(subscriptions, "check_subscription_new_videos", new=AsyncMock(return_value=[])):

            # 1. POST /api/subscriptions
            post_res = self.client.post("/api/subscriptions", json={
                "url": "https://www.youtube.com/@Veritasium",
                "interval_seconds": 60
            })
            self.assertEqual(post_res.status_code, 200)
            data = post_res.json()
            self.assertEqual(data["title"], "Veritasium")
            sub_id = data["id"]

            # 2. GET /api/subscriptions
            get_res = self.client.get("/api/subscriptions")
            self.assertEqual(get_res.status_code, 200)
            subs_list = get_res.json()
            self.assertEqual(len(subs_list), 1)
            self.assertEqual(subs_list[0]["id"], sub_id)

            # 3. PATCH /api/subscriptions/{sub_id}
            patch_res = self.client.patch(f"/api/subscriptions/{sub_id}", json={
                "enabled": False,
                "interval_seconds": 300
            })
            self.assertEqual(patch_res.status_code, 200)
            patched_data = patch_res.json()
            self.assertFalse(patched_data["enabled"])
            self.assertEqual(patched_data["interval_seconds"], 300)

            # 4. POST /api/subscriptions/{sub_id}/check
            check_res = self.client.post(f"/api/subscriptions/{sub_id}/check")
            self.assertEqual(check_res.status_code, 200)
            check_data = check_res.json()
            self.assertIn("new_count", check_data)

            # 5. DELETE /api/subscriptions/{sub_id}
            del_res = self.client.delete(f"/api/subscriptions/{sub_id}")
            self.assertEqual(del_res.status_code, 200)

            # Verify empty
            get_after = self.client.get("/api/subscriptions")
            self.assertEqual(len(get_after.json()), 0)

    async def test_adversarial_pathological_urls(self):
        """Test pathological URLs including injection attempts and invalid schemes."""
        # Empty string
        res_empty = self.client.post("/api/subscriptions", json={"url": "   "})
        self.assertEqual(res_empty.status_code, 400)

        # Injection vector in URL normalization and metadata extraction
        vectors = [
            "file:///etc/passwd",
            "--exec touch /tmp/pwned",
            "https://www.youtube.com/; rm -rf / ;",
            "https://www.tiktok.com/@attacker`id`",
            "https://www.youtube.com/@$(whoami)",
        ]
        for vec in vectors:
            norm = subscriptions.normalize_subscription_url(vec)
            self.assertTrue(norm.startswith("http://") or norm.startswith("https://"))
            # Ensure it doesn't crash extract_channel_metadata
            meta = await subscriptions.extract_channel_metadata(vec)
            self.assertIn("title", meta)
            self.assertIn("platform", meta)

    async def test_adversarial_file_corruption_recovery(self):
        """Test graceful recovery when subscriptions.json is corrupted."""
        with open(self.sub_file, "w", encoding="utf-8") as f:
            f.write("{ truncated json content: [")

        # Manager should not crash, returns []
        subs = await self.manager.list_subscriptions()
        self.assertEqual(subs, [])

        # Adding new sub recovers file with valid JSON
        new_sub = await self.manager.add_subscription("https://www.youtube.com/@safe", title="Safe")
        self.assertIsNotNone(new_sub["id"])
        with open(self.sub_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["title"], "Safe")

    async def test_adversarial_concurrent_race_conditions(self):
        """Test race condition safety with concurrent coroutines updating subscriptions."""
        async def worker(i):
            sub = await self.manager.add_subscription(
                url=f"https://www.youtube.com/@creator_{i}",
                title=f"Creator {i}"
            )
            s_id = sub["id"]
            await self.manager.update_subscription(s_id, interval_seconds=30 + i)
            await self.manager.add_seen_ids(s_id, [f"v_{i}_a", f"v_{i}_b"])
            if i % 2 == 0:
                await self.manager.delete_subscription(s_id)

        await asyncio.gather(*(worker(i) for i in range(20)))
        remaining = await self.manager.list_subscriptions()
        self.assertEqual(len(remaining), 10)
        # Check file validity
        with open(self.sub_file, "r", encoding="utf-8") as f:
            disk_data = json.load(f)
        self.assertEqual(len(disk_data), 10)


if __name__ == "__main__":
    unittest.main()
