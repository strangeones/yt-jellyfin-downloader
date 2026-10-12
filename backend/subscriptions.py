import os
import sys
import json
import time
import uuid
import re
import asyncio
import tempfile
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import List, Dict, Any, Optional

try:
    from curl_cffi import requests as cffi_requests
except ImportError:
    cffi_requests = None


def get_data_dir() -> str:
    """
    Resolve the persistent data directory:
    - SUBSCRIPTIONS_DATA_DIR env variable if set
    - /app/data if running inside Docker container or exists
    - ./data relative to project root in local environments
    """
    env_dir = os.getenv("SUBSCRIPTIONS_DATA_DIR")
    if env_dir:
        return os.path.abspath(env_dir)

    if os.path.isdir("/app/data") or (os.path.isdir("/app") and os.access("/app", os.W_OK)):
        return "/app/data"

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_dir, "data")


def get_subscriptions_file_path() -> str:
    """Resolve absolute path to subscriptions.json."""
    env_path = os.getenv("SUBSCRIPTIONS_FILE_PATH")
    if env_path:
        return os.path.abspath(env_path)
    return os.path.join(get_data_dir(), "subscriptions.json")


class SubscriptionManager:
    """Manages persistent subscriptions in subscriptions.json with atomic save/load."""

    def __init__(self, file_path: Optional[str] = None):
        self.file_path = file_path or get_subscriptions_file_path()
        self._lock = asyncio.Lock()

    def _load_sync(self) -> List[Dict[str, Any]]:
        if not os.path.isfile(self.file_path):
            return []
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
            elif isinstance(data, dict) and "subscriptions" in data:
                return data["subscriptions"]
        except Exception as e:
            print(f"[Subscriptions] Error reading {self.file_path}: {e}", file=sys.stderr)
        return []

    def _save_sync(self, subscriptions: List[Dict[str, Any]]):
        data_dir = os.path.dirname(self.file_path)
        os.makedirs(data_dir, exist_ok=True)
        payload = json.dumps(subscriptions, indent=2, ensure_ascii=False) + "\n"

        # Atomic write: write to temp file then rename
        temp_fd, temp_path = tempfile.mkstemp(
            prefix="subscriptions_",
            suffix=".tmp",
            dir=data_dir
        )
        try:
            with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
                f.write(payload)
            os.replace(temp_path, self.file_path)
        except Exception:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass
            raise

    async def list_subscriptions(self) -> List[Dict[str, Any]]:
        async with self._lock:
            return self._load_sync()

    async def get_subscription(self, sub_id: str) -> Optional[Dict[str, Any]]:
        async with self._lock:
            subs = self._load_sync()
            for s in subs:
                if s.get("id") == sub_id:
                    return dict(s)
            return None

    async def add_subscription(
        self,
        url: str,
        title: Optional[str] = None,
        platform: Optional[str] = None,
        avatar_url: Optional[str] = None,
        channel_id: Optional[str] = None,
        interval_seconds: Optional[int] = None
    ) -> Dict[str, Any]:
        async with self._lock:
            subs = self._load_sync()
            norm_url = normalize_subscription_url(url)
            
            # Check for existing duplicate by normalized URL
            for s in subs:
                if normalize_subscription_url(s.get("url", "")) == norm_url:
                    return s

            detected_platform = platform or detect_platform(url)
            default_interval = 15 if detected_platform == "tiktok" else 60
            chosen_interval = interval_seconds if interval_seconds is not None else default_interval

            sub = {
                "id": str(uuid.uuid4()),
                "url": url,
                "title": title or ("TikTok Creator" if detected_platform == "tiktok" else "YouTube Channel"),
                "platform": detected_platform,
                "avatar_url": avatar_url or "",
                "channel_id": channel_id or "",
                "interval_seconds": int(chosen_interval),
                "enabled": True,
                "last_checked": None,
                "seen_ids": []
            }
            subs.append(sub)
            self._save_sync(subs)
            return sub

    async def update_subscription(
        self,
        sub_id: str,
        enabled: Optional[bool] = None,
        interval_seconds: Optional[int] = None,
        title: Optional[str] = None,
        avatar_url: Optional[str] = None,
        channel_id: Optional[str] = None,
        last_checked: Optional[str] = None,
        seen_ids: Optional[List[str]] = None
    ) -> Optional[Dict[str, Any]]:
        async with self._lock:
            subs = self._load_sync()
            updated_sub = None
            for s in subs:
                if s.get("id") == sub_id:
                    if enabled is not None:
                        s["enabled"] = enabled
                    if interval_seconds is not None:
                        s["interval_seconds"] = int(interval_seconds)
                    if title is not None:
                        s["title"] = title
                    if avatar_url is not None:
                        s["avatar_url"] = avatar_url
                    if channel_id is not None:
                        s["channel_id"] = channel_id
                    if last_checked is not None:
                        s["last_checked"] = last_checked
                    if seen_ids is not None:
                        s["seen_ids"] = list(dict.fromkeys(seen_ids))
                    updated_sub = dict(s)
                    break
            if updated_sub:
                self._save_sync(subs)
            return updated_sub

    async def add_seen_ids(self, sub_id: str, new_ids: List[str]) -> Optional[Dict[str, Any]]:
        async with self._lock:
            subs = self._load_sync()
            updated_sub = None
            for s in subs:
                if s.get("id") == sub_id:
                    existing = list(s.get("seen_ids", []))
                    combined = list(dict.fromkeys(existing + new_ids))
                    # Retain up to last 1000 IDs to avoid unbounded growth
                    if len(combined) > 1000:
                        combined = combined[-1000:]
                    s["seen_ids"] = combined
                    s["last_checked"] = datetime.utcnow().isoformat()
                    updated_sub = dict(s)
                    break
            if updated_sub:
                self._save_sync(subs)
            return updated_sub

    async def delete_subscription(self, sub_id: str) -> bool:
        async with self._lock:
            subs = self._load_sync()
            initial_len = len(subs)
            subs = [s for s in subs if s.get("id") != sub_id]
            if len(subs) != initial_len:
                self._save_sync(subs)
                return True
            return False


# Singleton subscription manager instance
subscription_manager = SubscriptionManager()


def detect_platform(url: str) -> str:
    s = (url or "").lower().strip()
    if "tiktok.com" in s:
        return "tiktok"
    return "youtube"


def normalize_subscription_url(input_str: str) -> str:
    s = (input_str or "").strip()
    if not s:
        return ""
    if not (s.startswith("http://") or s.startswith("https://")):
        if s.startswith("@"):
            if "tiktok" in s:
                s = f"https://www.tiktok.com/{s}"
            else:
                s = f"https://www.youtube.com/{s}"
        elif s.startswith("UC") and len(s) == 24:
            s = f"https://www.youtube.com/channel/{s}"
        else:
            s = f"https://{s}"
    s = s.rstrip('/')
    if "youtube.com" in s:
        s = re.sub(r'/(videos|shorts|streams|playlists|featured|about)$', '', s)
    return s


# ---------------------------------------------------------------------------
# Channel Metadata Extraction (Platform, Title, Avatar, Channel ID)
# ---------------------------------------------------------------------------

def _extract_youtube_meta_sync(url: str) -> Dict[str, Any]:
    norm_url = normalize_subscription_url(url)
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept-Language': 'en-US,en;q=0.9',
    }
    req = urllib.request.Request(norm_url, headers=headers)
    html = ""
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            html = resp.read().decode('utf-8', errors='ignore')
    except Exception as e:
        print(f"[Subscriptions] HTML fetch error for {norm_url}: {e}")

    channel_id = ""
    title = ""
    avatar_url = ""

    # Try extracting channel ID from meta tags or ytInitialData
    m_cid = re.search(r'itemprop="channelId"\s+content="([^"]+)"', html)
    if not m_cid:
        m_cid = re.search(r'"channelId":"(UC[a-zA-Z0-9_-]{22})"', html)
    if not m_cid:
        m_cid = re.search(r'browse_id=(UC[a-zA-Z0-9_-]{22})', html)
    if m_cid:
        channel_id = m_cid.group(1)

    # Extract title
    m_title = re.search(r'<meta property="og:title" content="([^"]+)"', html)
    if not m_title:
        m_title = re.search(r'<title>([^<]+)</title>', html)
    if m_title:
        title = m_title.group(1).replace(" - YouTube", "").strip()

    # Extract avatar
    m_avatar = re.search(r'<meta property="og:image" content="([^"]+)"', html)
    if m_avatar:
        avatar_url = m_avatar.group(1).strip()

    return {
        "title": title or "YouTube Channel",
        "avatar_url": avatar_url or "",
        "channel_id": channel_id or "",
        "platform": "youtube",
        "url": norm_url
    }


def _extract_tiktok_meta_sync(url: str) -> Dict[str, Any]:
    norm_url = normalize_subscription_url(url)
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept-Language': 'en-US,en;q=0.9',
    }
    html = ""
    cookies_path = os.getenv("COOKIES_FILE", "/app/data/cookies.txt")

    if cffi_requests is not None:
        try:
            cookies = None
            if os.path.exists(cookies_path):
                # curl_cffi supports cookies file via cookies parameter or headers if needed
                pass
            res = cffi_requests.get(norm_url, headers=headers, impersonate="chrome120", timeout=12)
            if res.status_code == 200:
                html = res.text
        except Exception as e:
            print(f"[Subscriptions] curl_cffi error for {norm_url}: {e}")

    if not html:
        try:
            req = urllib.request.Request(norm_url, headers=headers)
            with urllib.request.urlopen(req, timeout=12) as resp:
                html = resp.read().decode('utf-8', errors='ignore')
        except Exception as e:
            print(f"[Subscriptions] urllib error for {norm_url}: {e}")

    title = ""
    avatar_url = ""

    # Parse title / handle from html
    m_title = re.search(r'<meta property="og:title" content="([^"]+)"', html)
    if m_title:
        raw_t = m_title.group(1)
        # Often format is "CreatorName (@handle) | TikTok"
        title = raw_t.split("|")[0].strip()
    if not title:
        m_handle = re.search(r'@([a-zA-Z0-9_.-]+)', norm_url)
        title = f"@{m_handle.group(1)}" if m_handle else "TikTok Creator"

    m_avatar = re.search(r'<meta property="og:image" content="([^"]+)"', html)
    if m_avatar:
        avatar_url = m_avatar.group(1).strip()

    return {
        "title": title,
        "avatar_url": avatar_url,
        "channel_id": "",
        "platform": "tiktok",
        "url": norm_url
    }


async def extract_channel_metadata(url: str) -> Dict[str, Any]:
    """Auto-extract creator title, platform, avatar, and channel ID."""
    platform = detect_platform(url)
    try:
        if platform == "tiktok":
            meta = await asyncio.to_thread(_extract_tiktok_meta_sync, url)
        else:
            meta = await asyncio.to_thread(_extract_youtube_meta_sync, url)
        return meta
    except Exception as e:
        print(f"[Subscriptions] Error extracting metadata for {url}: {e}")
        return {
            "title": "TikTok Creator" if platform == "tiktok" else "YouTube Channel",
            "avatar_url": "",
            "channel_id": "",
            "platform": platform,
            "url": normalize_subscription_url(url)
        }


# ---------------------------------------------------------------------------
# Fast Lightweight Upload Checkers
# ---------------------------------------------------------------------------

def _check_youtube_rss_sync(channel_id: str) -> List[Dict[str, Any]]:
    """Lightweight XML RSS check for YouTube channels."""
    if not channel_id:
        return []
    rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    req = urllib.request.Request(rss_url, headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            xml_data = resp.read()
        root = ET.fromstring(xml_data)
        ns = {
            'atom': 'http://www.w3.org/2005/Atom',
            'yt': 'http://www.youtube.com/xml/schemas/2015'
        }
        results = []
        for entry in root.findall('atom:entry', ns):
            vid_el = entry.find('yt:videoId', ns)
            title_el = entry.find('atom:title', ns)
            if vid_el is not None and vid_el.text:
                vid_id = vid_el.text.strip()
                title = title_el.text.strip() if title_el is not None and title_el.text else "YouTube Video"
                results.append({
                    "id": vid_id,
                    "url": f"https://www.youtube.com/watch?v={vid_id}",
                    "title": title
                })
        return results
    except Exception as e:
        print(f"[Subscriptions] YouTube RSS check error for {channel_id}: {e}")
        return []


def _check_tiktok_feed_sync(url: str) -> List[Dict[str, Any]]:
    """Lightweight async HTTP check of TikTok creator feed extracting latest video item IDs."""
    norm_url = normalize_subscription_url(url)
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
    }
    cookies_path = os.getenv("COOKIES_FILE", "/app/data/cookies.txt")
    html = ""

    if cffi_requests is not None:
        try:
            res = cffi_requests.get(norm_url, headers=headers, impersonate="chrome120", timeout=12)
            if res.status_code == 200:
                html = res.text
        except Exception as e:
            print(f"[Subscriptions] TikTok curl_cffi check error: {e}")

    if not html:
        try:
            req = urllib.request.Request(norm_url, headers=headers)
            with urllib.request.urlopen(req, timeout=12) as resp:
                html = resp.read().decode('utf-8', errors='ignore')
        except Exception as e:
            print(f"[Subscriptions] TikTok urllib check error: {e}")

    results = []
    if html:
        # Search for video IDs in universal rehydration data or regex
        # Video IDs are 18-20 digit strings: /video/(\d{18,20}) or "id":"(\d{18,20})"
        video_ids = re.findall(r'/video/(\d{18,20})', html)
        if not video_ids:
            # Try finding item IDs in JSON structures
            video_ids = re.findall(r'"(?:id|itemId)":\s*"(\d{18,20})"', html)

        seen = set()
        for vid in video_ids:
            if vid not in seen:
                seen.add(vid)
                results.append({
                    "id": vid,
                    "url": f"https://www.tiktok.com/video/{vid}",
                    "title": f"TikTok Video {vid}"
                })
                if len(results) >= 10:
                    break

    return results


async def _check_ytdlp_fallback(url: str, cookies_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Fallback: yt-dlp flat-playlist end 3."""
    cmd = ["python3", "-m", "yt_dlp", "--flat-playlist", "-J", "--playlist-end", "3"]
    if cookies_path and os.path.exists(cookies_path):
        cmd.extend(["--cookies", cookies_path])
    impersonate_client = os.getenv("TIKTOK_IMPERSONATE")
    if "tiktok.com" in url and impersonate_client:
        cmd.extend(["--impersonate", impersonate_client])
    cmd.append(url)

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        if proc.returncode == 0 and stdout:
            data = json.loads(stdout)
            entries = data.get("entries", [])
            results = []
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                vid_id = entry.get("id") or ""
                if not vid_id:
                    continue
                v_url = entry.get("url") or ""
                if not v_url or not v_url.startswith("http"):
                    if "tiktok.com" in url:
                        v_url = f"https://www.tiktok.com/video/{vid_id}"
                    else:
                        v_url = f"https://www.youtube.com/watch?v={vid_id}"
                results.append({
                    "id": vid_id,
                    "url": v_url,
                    "title": entry.get("title") or vid_id
                })
            return results
    except Exception as e:
        print(f"[Subscriptions] yt-dlp fallback error for {url}: {e}")
    return []


async def check_subscription_new_videos(sub: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Check subscription for latest items.
    Returns list of items: [{"id": ..., "url": ..., "title": ...}]
    """
    platform = sub.get("platform") or detect_platform(sub.get("url", ""))
    url = sub.get("url", "")
    items: List[Dict[str, Any]] = []

    if platform == "youtube":
        channel_id = sub.get("channel_id")
        if channel_id:
            items = await asyncio.to_thread(_check_youtube_rss_sync, channel_id)
        if not items:
            # If no channel_id or RSS empty, fallback to yt-dlp flat-playlist end 3
            cookies_path = os.getenv("COOKIES_FILE", "/app/data/cookies.txt")
            items = await _check_ytdlp_fallback(url, cookies_path)
    elif platform == "tiktok":
        items = await asyncio.to_thread(_check_tiktok_feed_sync, url)
        if not items:
            cookies_path = os.getenv("COOKIES_FILE", "/app/data/cookies.txt")
            items = await _check_ytdlp_fallback(url, cookies_path)

    return items
