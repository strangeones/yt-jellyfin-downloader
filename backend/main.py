import asyncio
import os
import re
import secrets
import json
import subprocess
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, date
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, HTTPException, Request, Response, Query
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from backend import auth

AUTO_UPDATE_YTDLP = os.getenv("AUTO_UPDATE_YTDLP", "false").lower() == "true"

app = FastAPI()

WHITELIST_PATHS = {
    "/",
    "/index.html",
    "/style.css",
    "/app.js",
    "/favicon.ico",
    "/api/auth/status",
    "/api/auth/login",
    "/api/auth/setup",
    "/api/auth/logout",
}

STATIC_EXTENSIONS = (
    ".css", ".js", ".png", ".jpg", ".jpeg", ".gif",
    ".svg", ".ico", ".woff", ".woff2", ".ttf", ".eot", ".map"
)

def is_request_whitelisted(path: str) -> bool:
    if path in WHITELIST_PATHS:
        return True
    if path.startswith("/static/"):
        return True
    if any(path.endswith(ext) for ext in STATIC_EXTENSIONS):
        return True
    return False

class CacheControlledStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope) -> Response:
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response

@app.middleware("http")
async def session_auth_middleware(request: Request, call_next):
    # Allow whitelisted frontend assets and public auth endpoints
    if is_request_whitelisted(request.url.path):
        response = await call_next(request)
        if request.url.path in WHITELIST_PATHS or any(request.url.path.endswith(ext) for ext in STATIC_EXTENSIONS):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response

    # Validate session cookie for protected endpoints
    session_token = request.cookies.get("session_token")
    username = auth.validate_session(session_token) if session_token else None

    if not username:
        return JSONResponse(
            status_code=401,
            content={"detail": "Unauthorized", "authenticated": False}
        )

    # Attach authenticated user to request state
    request.state.user = username
    return await call_next(request)

class LoginRequest(BaseModel):
    username: str
    password: str

class SetupRequest(BaseModel):
    username: str
    password: str

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

class DownloadRequest(BaseModel):
    url: Optional[str] = None
    is_playlist: bool = False
    items: Optional[List[Dict[str, Any]]] = None

class ChannelScanRequest(BaseModel):
    url: str
    date_from: str
    date_to: str
    media_types: Optional[List[str]] = ["all"]

class ChannelQueryRequest(BaseModel):
    url: Optional[str] = None
    channel: Optional[str] = None
    handle: Optional[str] = None
    channel_id: Optional[str] = None
    id: Optional[str] = None
    q: Optional[str] = None

queue = asyncio.Queue()
current_task = None
queued_tasks = []
history = []
active_process = None
state_lock = None

def is_valid_youtube_url(url: str) -> bool:
    pattern = r'^(https?://)?([a-zA-Z0-9-]+\.)*(youtube\.com|youtu\.be)/.+$'
    return re.match(pattern, url) is not None

def format_size(bytes_size):
    if not bytes_size:
        return "Unknown size"
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_size < 1024:
            return f"{bytes_size:.2f}{unit}"
        bytes_size /= 1024
    return f"{bytes_size:.2f}PB"

async def fetch_metadata(task):
    try:
        cmd = ["yt-dlp", "-J", "--no-playlist", task['url']]
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await proc.communicate()
        if proc.returncode == 0:
            info = json.loads(stdout)
            task['title'] = info.get('title', 'Unknown Title')
            size_bytes = info.get('filesize') or info.get('filesize_approx')
            if size_bytes:
                task['size'] = format_size(size_bytes)
            else:
                task['size'] = "Unknown size"
        else:
            task['title'] = "Unknown Title"
            if stderr:
                err_msg = stderr.decode('utf-8').strip()
                task['error'] = err_msg.split('\n')[-1] if err_msg else "Unknown metadata error"
    except Exception as e:
        task['title'] = "Error fetching metadata"
        task['error'] = str(e)
    finally:
        task['metadata_fetched'] = True

async def fetch_playlist(url: str):
    try:
        cmd = ["yt-dlp", "--flat-playlist", "--yes-playlist", "-J", "--compat-options", "no-youtube-unavailable-videos", url]
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, _ = await proc.communicate()
        if proc.returncode == 0:
            info = json.loads(stdout)
            entries = info.get('entries', [])
            for entry in entries:
                video_url = entry.get('url')
                if not video_url and entry.get('id'):
                    video_url = f"https://www.youtube.com/watch?v={entry['id']}"
                    
                if video_url:
                    task_id = secrets.token_hex(8)
                    task = {
                        "id": task_id,
                        "url": video_url,
                        "status": "queued",
                        "added_at": datetime.now().isoformat(),
                        "title": entry.get('title') or 'Unknown Title',
                        "size": "Calculating...",
                        "progress": 0.0,
                        "eta": "",
                        "cancelled": False,
                        "metadata_fetched": True
                    }
                    if state_lock:
                        async with state_lock:
                            queued_tasks.append(task)
                    else:
                        queued_tasks.append(task)
                    await queue.put(task)
                    # We intentionally skip launching fetch_metadata(task) here to 
                    # safely queue mix items without spawning hundreds of subprocesses.
    except Exception as e:
        print(f"Error fetching playlist: {e}")

async def update_yt_dlp():
    if not AUTO_UPDATE_YTDLP:
        print("yt-dlp auto-update is disabled by default. Set AUTO_UPDATE_YTDLP=true to enable.")
        return
    while True:
        try:
            print("Updating yt-dlp...")
            process = await asyncio.create_subprocess_exec(
                "pip", "install", "-U", "yt-dlp",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await process.communicate()
        except Exception as e:
            print(f"Failed to update yt-dlp: {e}")
        await asyncio.sleep(86400) # Update daily

async def process_queue():
    global current_task, active_process
    while True:
        task = await queue.get()
        if task.get('cancelled'):
            queue.task_done()
            continue
            
        while not task.get('metadata_fetched', False) and not task.get('cancelled'):
            await asyncio.sleep(0.5)
            
        if task.get('cancelled'):
            queue.task_done()
            continue
            
        async with state_lock:
            current_task = task
            if task in queued_tasks:
                queued_tasks.remove(task)
            
        task['status'] = 'downloading'
        task['expected_files'] = 1
        task['current_file_index'] = 0
        
        try:
            media_dir = "/app/media"
            os.makedirs(media_dir, exist_ok=True)
            
            cmd = [
                "yt-dlp",
                "--newline",
                "--no-playlist",
                "--write-info-json",
                "--write-thumbnail",
                "--embed-metadata",
                "--socket-timeout", "30",
                "--no-overwrites",
                "-o", f"{media_dir}/%(uploader)s - %(upload_date)s - %(title)s [%(id)s].%(ext)s",
                task['url']
            ]
            
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT
            )
            
            async with state_lock:
                active_process = proc
                if task.get('cancelled'):
                    try:
                        active_process.terminate()
                    except Exception:
                        pass
            
            async def read_output():
                while True:
                    line = await proc.stdout.readline()
                    if not line:
                        break
                    line = line.decode('utf-8').strip()
                    
                    if line.startswith("[info]"):
                        format_match = re.search(r'Downloading \d+ format\(s\):\s*(.+)', line)
                        if format_match:
                            task['expected_files'] = len(format_match.group(1).split('+'))
                            
                    elif line.startswith("[download] Destination:"):
                        if not re.search(r'\.(webp|jpg|png|vtt|srt|json)$', line, re.IGNORECASE):
                            task['current_file_index'] += 1
                        
                    elif "has already been downloaded" in line:
                        if not re.search(r'\.(webp|jpg|png|vtt|srt|json)( \(.+\))?$', line, re.IGNORECASE):
                            task['current_file_index'] += 1
                            
                    elif line.startswith("[Merger]") or line.startswith("[Metadata]") or line.startswith("[ExtractAudio]") or line.startswith("[VideoConvertor]") or line.startswith("[ThumbnailsConvertor]"):
                        task['progress'] = 100.0
                        task['eta'] = "Processing media..."
                        
                    elif line.startswith("[download]"):
                        perc_match = re.search(r'([0-9\.]+)%', line)
                        if perc_match:
                            raw_progress = float(perc_match.group(1))
                            expected = task.get('expected_files', 1)
                            current = task.get('current_file_index', 1)
                            
                            if current == 0:
                                current = 1
                                
                            if current > expected:
                                expected = current
                                
                            base_progress = (current - 1) * 100.0
                            task['progress'] = round((base_progress + raw_progress) / expected, 1)
                            
                        size_match = re.search(r'of\s+~?\s*([0-9\.]+[a-zA-Z]+)', line)
                        if size_match:
                            if task.get('size') in ('Calculating...', 'Unknown size', 'Unknown'):
                                task['size'] = size_match.group(1)
                            
                        eta_match = re.search(r'ETA\s+([0-9:]+)', line)
                        if eta_match:
                            task['eta'] = eta_match.group(1)
                            
            read_task = asyncio.create_task(read_output())
            wait_task = asyncio.create_task(proc.wait())
            
            done, pending = await asyncio.wait(
                [read_task, wait_task], 
                return_when=asyncio.FIRST_COMPLETED
            )
            
            if wait_task in done:
                read_task.cancel()
            else:
                await wait_task
            
            if task.get('cancelled'):
                task['status'] = 'cancelled'
            elif proc.returncode == 0:
                task['status'] = 'completed'
                task['progress'] = 100.0
                task['eta'] = "00:00"
            else:
                task['status'] = 'failed'
                task['error'] = "Download failed or was interrupted."
                
        except Exception as e:
            if not task.get('cancelled'):
                task['status'] = 'failed'
                task['error'] = str(e)
        finally:
            proc_to_wait = None
            async with state_lock:
                if active_process and active_process.returncode is None:
                    try:
                        active_process.terminate()
                        proc_to_wait = active_process
                    except Exception:
                        pass
                task['completed_at'] = datetime.now().isoformat()
                history.insert(0, task)
                if len(history) > 50:
                    history.pop()
                current_task = None
                active_process = None
            
            if proc_to_wait:
                try:
                    await asyncio.wait_for(proc_to_wait.wait(), timeout=5.0)
                except Exception:
                    pass
            queue.task_done()

@app.on_event("startup")
async def startup_event():
    global state_lock
    state_lock = asyncio.Lock()
    auth.auto_migrate_or_init()
    asyncio.create_task(update_yt_dlp())
    asyncio.create_task(process_queue())

# ---------------------------------------------------------------------------
# Authentication Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/auth/status")
async def auth_status(request: Request):
    session_token = request.cookies.get("session_token")
    username = auth.validate_session(session_token) if session_token else None
    setup_req = auth.is_setup_required()
    return {
        "authenticated": username is not None,
        "username": username,
        "setup_required": setup_req
    }

@app.post("/api/auth/login")
async def auth_login(req: LoginRequest, response: Response):
    if auth.is_setup_required():
        raise HTTPException(status_code=400, detail="Initial setup required. Please configure admin credentials first.")

    username = req.username.strip()
    if not auth.authenticate(username, req.password):
        raise HTTPException(status_code=401, detail="Invalid username or password.")

    token = auth.create_session(username)
    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=30 * 24 * 3600,
        path="/"
    )
    return {"success": True, "username": username}

@app.post("/api/auth/setup")
async def auth_setup(req: SetupRequest, response: Response):
    if not auth.is_setup_required():
        raise HTTPException(status_code=400, detail="Setup has already been completed.")

    username = req.username.strip()
    password = req.password
    if not username:
        raise HTTPException(status_code=400, detail="Username cannot be empty.")
    if not password:
        raise HTTPException(status_code=400, detail="Password cannot be empty.")

    auth.setup_credentials(username, password)
    token = auth.create_session(username)
    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=30 * 24 * 3600,
        path="/"
    )
    return {"success": True, "username": username}

@app.post("/api/auth/logout")
async def auth_logout(request: Request, response: Response):
    session_token = request.cookies.get("session_token")
    if session_token:
        auth.delete_session(session_token)
    response.delete_cookie(key="session_token", path="/")
    return {"success": True, "message": "Logged out successfully"}

@app.post("/api/auth/change-password")
async def auth_change_password(req: ChangePasswordRequest, request: Request, response: Response):
    session_token = request.cookies.get("session_token")
    username = auth.validate_session(session_token) if session_token else None
    if not username:
        raise HTTPException(status_code=401, detail="Unauthorized")

    if not auth.verify_user_password(username, req.current_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect.")

    new_password = req.new_password
    if not new_password:
        raise HTTPException(status_code=400, detail="New password cannot be empty.")

    auth.change_password(username, new_password)
    # Refresh session with new token
    auth.delete_session(session_token)
    new_token = auth.create_session(username)
    response.set_cookie(
        key="session_token",
        value=new_token,
        httponly=True,
        samesite="lax",
        max_age=30 * 24 * 3600,
        path="/"
    )
    return {"success": True, "message": "Password updated successfully"}

# ---------------------------------------------------------------------------
# YouTube Scraper Helpers & Channel Parsers
# ---------------------------------------------------------------------------

def normalize_channel_url(input_str: str) -> str:
    s = (input_str or "").strip()
    if not s:
        return ""
    if s.startswith("http://") or s.startswith("https://") or s.startswith("www.") or "youtube.com/" in s or "youtu.be/" in s:
        if not s.startswith("http://") and not s.startswith("https://"):
            s = f"https://{s}"
    elif s.startswith("@"):
        s = f"https://www.youtube.com/{s}"
    elif s.startswith("UC") and len(s) == 24:
        s = f"https://www.youtube.com/channel/{s}"
    else:
        s = f"https://www.youtube.com/@{s}"
    s = re.sub(r'/(videos|playlists|shorts|featured|streams|podcasts|posts|community|about)/?$', '', s.rstrip('/'))
    return s


def extract_yt_initial_data(html: str) -> Optional[dict]:
    for pattern in (r'var ytInitialData\s*=\s*', r'window\["ytInitialData"\]\s*=\s*', r'ytInitialData\s*=\s*'):
        m = re.search(pattern, html)
        if m:
            start_pos = m.end()
            start_brace = html.find('{', start_pos - 1)
            if start_brace != -1:
                try:
                    data, _ = json.JSONDecoder().raw_decode(html[start_brace:])
                    return data
                except Exception:
                    pass
    idx = html.find('ytInitialData')
    if idx != -1:
        start_brace = html.find('{', idx)
        if start_brace != -1:
            try:
                data, _ = json.JSONDecoder().raw_decode(html[start_brace:])
                return data
            except Exception:
                pass
    return None


def _fetch_youtube_html_sync(url: str) -> str:
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36',
        'Accept-Language': 'en-US,en;q=0.9',
    }
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read().decode('utf-8', errors='ignore')


async def fetch_youtube_html(url: str) -> str:
    return await asyncio.to_thread(_fetch_youtube_html_sync, url)


def extract_channel_metadata(data: dict) -> dict:
    meta = data.get('metadata', {}).get('channelMetadataRenderer', {})
    channel_title = meta.get('title')
    channel_id = meta.get('externalId')
    channel_url = meta.get('channelUrl') or meta.get('vanityChannelUrl')
    avatar_list = meta.get('avatar', {}).get('thumbnails', [])
    avatar = avatar_list[-1].get('url') if avatar_list else ''
    
    if not channel_title:
        header = data.get('header', {})
        for hk in ('pageHeaderRenderer', 'c4TabbedHeaderRenderer', 'carouselHeaderRenderer'):
            hr = header.get(hk, {})
            if hr:
                channel_title = hr.get('pageTitle') or hr.get('title', {}).get('simpleText')
                if not channel_title and 'title' in hr and isinstance(hr['title'], dict):
                    runs = hr['title'].get('runs', [])
                    if runs:
                        channel_title = runs[0].get('text')
                if not avatar:
                    hr_avatar = hr.get('avatar', {}).get('thumbnails', [])
                    if hr_avatar and isinstance(hr_avatar, list):
                        avatar = hr_avatar[-1].get('url')
    
    if not channel_title:
        channel_title = data.get('microformat', {}).get('microformatDataRenderer', {}).get('title')
        
    return {
        'title': channel_title or 'YouTube Channel',
        'channel_id': channel_id or '',
        'channel_url': channel_url or '',
        'avatar': avatar or ''
    }


def parse_video_item(item: Any, channel_name: str = '') -> Optional[dict]:
    if not isinstance(item, dict):
        return None
    if 'richItemRenderer' in item:
        item = item['richItemRenderer'].get('content', {})
    if 'lockupViewModel' in item:
        lvm = item['lockupViewModel']
        content_type = lvm.get('contentType', '')
        if content_type and 'VIDEO' not in content_type and 'SHORTS' not in content_type:
            return None
        vid_id = lvm.get('contentId')
        if not vid_id:
            on_tap = lvm.get('rendererContext', {}).get('commandContext', {}).get('onTap', {})
            vid_id = on_tap.get('innertubeCommand', {}).get('watchEndpoint', {}).get('videoId')
        if not vid_id:
            return None
            
        meta = lvm.get('metadata', {}).get('lockupMetadataViewModel', {})
        title = meta.get('title', {}).get('content', '')
        if not title:
            title = lvm.get('rendererContext', {}).get('accessibilityContext', {}).get('label', '')
            
        duration = ''
        img = lvm.get('contentImage', {}).get('thumbnailViewModel', {})
        if not img:
            img = lvm.get('contentImage', {}).get('collectionThumbnailViewModel', {}).get('primaryThumbnail', {}).get('thumbnailViewModel', {})
            
        overlays = img.get('overlays', [])
        for ov in overlays:
            bottom_ov = ov.get('thumbnailBottomOverlayViewModel', {})
            badges = bottom_ov.get('badges', [])
            for b in badges:
                badge_vm = b.get('thumbnailBadgeViewModel', {})
                if badge_vm.get('text'):
                    duration = badge_vm.get('text')
                    break
            if duration:
                break
                
        sources = img.get('image', {}).get('sources', [])
        thumb = sources[-1].get('url') if sources else f'https://i.ytimg.com/vi/{vid_id}/hqdefault.jpg'
        
        views = ''
        published = ''
        cmvm = meta.get('metadata', {}).get('contentMetadataViewModel', {})
        if not cmvm:
            cmvm = meta.get('contentMetadataViewModel', {})
        rows = cmvm.get('metadataRows', [])
        for row in rows:
            parts = row.get('metadataParts', [])
            for part in parts:
                txt = part.get('text', {}).get('content', '')
                if 'view' in txt.lower():
                    views = txt
                elif 'ago' in txt.lower() or 'stream' in txt.lower() or 'premier' in txt.lower():
                    published = txt
                    
        return {
            'type': 'video',
            'id': vid_id,
            'url': f'https://www.youtube.com/watch?v={vid_id}',
            'title': title,
            'duration': duration,
            'thumbnail': thumb,
            'views': views,
            'published': published,
            'channel': channel_name
        }

    renderer = item.get('videoRenderer') or item.get('gridVideoRenderer')
    if renderer:
        vid_id = renderer.get('videoId')
        if not vid_id:
            return None
        title = renderer.get('title', {}).get('runs', [{}])[0].get('text') or renderer.get('title', {}).get('simpleText', '')
        duration = renderer.get('lengthText', {}).get('simpleText') or renderer.get('thumbnailOverlays', [{}])[0].get('thumbnailOverlayTimeStatusRenderer', {}).get('text', {}).get('simpleText', '')
        thumbs = renderer.get('thumbnail', {}).get('thumbnails', [])
        thumb = thumbs[-1].get('url') if thumbs else f'https://i.ytimg.com/vi/{vid_id}/hqdefault.jpg'
        views = renderer.get('viewCountText', {}).get('simpleText') or renderer.get('shortViewCountText', {}).get('simpleText', '')
        published = renderer.get('publishedTimeText', {}).get('simpleText', '')
        byline = renderer.get('longBylineText', {}).get('runs', [{}])[0].get('text', '') or renderer.get('shortBylineText', {}).get('runs', [{}])[0].get('text', '')
        return {
            'type': 'video',
            'id': vid_id,
            'url': f'https://www.youtube.com/watch?v={vid_id}',
            'title': title,
            'duration': duration,
            'thumbnail': thumb,
            'views': views,
            'published': published,
            'channel': channel_name or byline
        }
    return None


def parse_playlist_item(item: Any, channel_name: str = '') -> Optional[dict]:
    if not isinstance(item, dict):
        return None
    if 'richItemRenderer' in item:
        item = item['richItemRenderer'].get('content', {})
    if 'lockupViewModel' in item:
        lvm = item['lockupViewModel']
        content_type = lvm.get('contentType', '')
        if content_type and 'PLAYLIST' not in content_type:
            return None
        pl_id = lvm.get('contentId')
        if not pl_id:
            on_tap = lvm.get('rendererContext', {}).get('commandContext', {}).get('onTap', {})
            pl_id = on_tap.get('innertubeCommand', {}).get('watchEndpoint', {}).get('playlistId')
        if not pl_id:
            return None
            
        meta = lvm.get('metadata', {}).get('lockupMetadataViewModel', {})
        title = meta.get('title', {}).get('content', '')
        if not title:
            title = lvm.get('rendererContext', {}).get('accessibilityContext', {}).get('label', '')
            
        video_count = ''
        img = lvm.get('contentImage', {}).get('collectionThumbnailViewModel', {}).get('primaryThumbnail', {}).get('thumbnailViewModel', {})
        if not img:
            img = lvm.get('contentImage', {}).get('thumbnailViewModel', {})
            
        overlays = img.get('overlays', []) if isinstance(img, dict) else []
        if not overlays:
            overlays = lvm.get('contentImage', {}).get('collectionThumbnailViewModel', {}).get('overlays', [])
        if not overlays:
            overlays = lvm.get('contentImage', {}).get('overlays', [])
        for ov in overlays:
            badge_ov = ov.get('thumbnailOverlayBadgeViewModel', {})
            for b in badge_ov.get('thumbnailBadges', []):
                b_vm = b.get('thumbnailBadgeViewModel', {})
                if b_vm.get('text'):
                    video_count = b_vm.get('text')
                    break
            if video_count:
                break
                
        if not video_count:
            cmvm = meta.get('metadata', {}).get('contentMetadataViewModel', {}) or meta.get('contentMetadataViewModel', {})
            for row in cmvm.get('metadataRows', []):
                for part in row.get('metadataParts', []):
                    txt = part.get('text', {}).get('content', '')
                    if 'video' in txt.lower():
                        video_count = txt
                        break
                if video_count:
                    break
                
        sources = img.get('image', {}).get('sources', [])
        thumb = sources[-1].get('url') if sources else ''
        
        return {
            'type': 'playlist',
            'id': pl_id,
            'url': f'https://www.youtube.com/playlist?list={pl_id}',
            'title': title,
            'video_count': video_count,
            'thumbnail': thumb,
            'channel': channel_name
        }

    renderer = item.get('gridPlaylistRenderer') or item.get('playlistRenderer')
    if renderer:
        pl_id = renderer.get('playlistId')
        if not pl_id:
            return None
        title = renderer.get('title', {}).get('runs', [{}])[0].get('text') or renderer.get('title', {}).get('simpleText', '')
        thumbs = renderer.get('thumbnail', {}).get('thumbnails', [])
        thumb = thumbs[-1].get('url') if thumbs else ''
        video_count = renderer.get('videoCountShortText', {}).get('simpleText') or renderer.get('videoCountText', {}).get('runs', [{}])[0].get('text') or renderer.get('videoCount', '')
        byline = renderer.get('longBylineText', {}).get('runs', [{}])[0].get('text', '') or renderer.get('shortBylineText', {}).get('runs', [{}])[0].get('text', '')
        return {
            'type': 'playlist',
            'id': pl_id,
            'url': f'https://www.youtube.com/playlist?list={pl_id}',
            'title': title,
            'video_count': str(video_count),
            'thumbnail': thumb,
            'channel': channel_name or byline
        }
    return None


def extract_videos_from_tab_content(content: dict, channel_name: str = "") -> List[dict]:
    videos = []
    seen_ids = set()

    def add_video(item):
        parsed = parse_video_item(item, channel_name=channel_name)
        if parsed and parsed.get('id') and parsed['id'] not in seen_ids:
            seen_ids.add(parsed['id'])
            videos.append(parsed)

    if 'richGridRenderer' in content:
        for it in content['richGridRenderer'].get('contents', []):
            add_video(it)

    if 'sectionListRenderer' in content:
        for s in content['sectionListRenderer'].get('contents', []):
            isr = s.get('itemSectionRenderer', {})
            for it in isr.get('contents', []):
                if 'gridRenderer' in it:
                    for git in it['gridRenderer'].get('items', []):
                        add_video(git)
                else:
                    add_video(it)

    if 'gridRenderer' in content:
        for git in content['gridRenderer'].get('items', []):
            add_video(git)

    return videos


def extract_playlists_from_tab_content(content: dict, channel_name: str = "") -> List[dict]:
    playlists = []
    seen_ids = set()

    def add_playlist(item):
        parsed = parse_playlist_item(item, channel_name=channel_name)
        if parsed and parsed.get('id') and parsed['id'] not in seen_ids:
            seen_ids.add(parsed['id'])
            playlists.append(parsed)

    if 'sectionListRenderer' in content:
        for s in content['sectionListRenderer'].get('contents', []):
            isr = s.get('itemSectionRenderer', {})
            for it in isr.get('contents', []):
                if 'gridRenderer' in it:
                    for git in it['gridRenderer'].get('items', []):
                        add_playlist(git)
                else:
                    add_playlist(it)

    if 'richGridRenderer' in content:
        for it in content['richGridRenderer'].get('contents', []):
            add_playlist(it)

    if 'gridRenderer' in content:
        for git in content['gridRenderer'].get('items', []):
            add_playlist(it)

    return playlists


def find_tab_content(data: dict, tab_names: tuple) -> tuple:
    tabs = data.get('contents', {}).get('twoColumnBrowseResultsRenderer', {}).get('tabs', [])
    for t in tabs:
        tr = t.get('tabRenderer', {})
        title = (tr.get('title') or '').strip().lower()
        if any(name.lower() in title for name in tab_names):
            return tr.get('content', {}), tr.get('title')
    
    for t in tabs:
        tr = t.get('tabRenderer', {})
        if tr.get('selected'):
            return tr.get('content', {}), tr.get('title')
            
    for t in tabs:
        tr = t.get('tabRenderer', {})
        if tr.get('content'):
            return tr.get('content', {}), tr.get('title')
            
    return {}, None


def format_duration(dur: Any) -> str:
    if dur is None:
        return ""
    if isinstance(dur, (int, float)):
        try:
            sec = int(dur)
            h = sec // 3600
            m = (sec % 3600) // 60
            s = sec % 60
            if h > 0:
                return f"{h}:{m:02d}:{s:02d}"
            return f"{m}:{s:02d}"
        except (ValueError, TypeError):
            return str(dur)
    return str(dur)


async def fetch_and_parse_channel_videos(channel_input: str) -> dict:
    base_url = normalize_channel_url(channel_input)
    if not base_url:
        raise HTTPException(status_code=400, detail="Invalid YouTube channel URL or identifier.")
        
    target_url = f"{base_url}/videos"
    cmd = ["python3", "-m", "yt_dlp", "--flat-playlist", "-J", "--playlist-end", "500", target_url]
    
    try:
        res = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to execute yt-dlp: {str(e)}")

    if res.returncode != 0 and target_url != base_url:
        cmd_fallback = ["python3", "-m", "yt_dlp", "--flat-playlist", "-J", "--playlist-end", "500", base_url]
        try:
            res_fallback = subprocess.run(
                cmd_fallback,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            if res_fallback.returncode == 0 and res_fallback.stdout.strip():
                res = res_fallback
        except Exception:
            pass

    if res.returncode != 0:
        err = (res.stderr or "").lower()
        if "404" in err or "not found" in err:
            raise HTTPException(status_code=404, detail="Channel not found on YouTube.")
        err_msg = (res.stderr or "").strip()[:200]
        raise HTTPException(status_code=502, detail=f"Failed to fetch channel from YouTube: {err_msg}")

    try:
        stdout = (res.stdout or "").strip()
        start_brace = stdout.find("{")
        end_brace = stdout.rfind("}")
        if start_brace != -1 and end_brace != -1:
            data = json.loads(stdout[start_brace:end_brace + 1])
        else:
            data = json.loads(stdout)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to parse yt-dlp response: {str(e)}")

    if not data or not isinstance(data, dict):
        return {
            "channel": "YouTube Channel",
            "channel_id": "",
            "channel_url": base_url,
            "avatar": "",
            "count": 0,
            "videos": [],
            "items": [],
            "results": []
        }

    channel_name = data.get("channel") or data.get("uploader") or data.get("title") or "YouTube Channel"
    if channel_name.endswith(" - Videos"):
        channel_name = channel_name[:-9]
        
    channel_id = data.get("channel_id") or data.get("id") or ""
    channel_url = data.get("channel_url") or data.get("uploader_url") or base_url

    avatar = ""
    thumbnails = data.get("thumbnails") or []
    if isinstance(thumbnails, list):
        for thumb in reversed(thumbnails):
            if isinstance(thumb, dict) and thumb.get("id") in ("avatar_uncropped", "avatar"):
                avatar = thumb.get("url") or ""
                break
        if not avatar:
            for thumb in reversed(thumbnails):
                if isinstance(thumb, dict) and thumb.get("height") and thumb.get("width") and thumb["height"] == thumb["width"]:
                    avatar = thumb.get("url") or ""
                    break
        if not avatar and thumbnails and isinstance(thumbnails[-1], dict):
            avatar = thumbnails[-1].get("url") or ""

    raw_entries = data.get("entries") or []
    videos = []
    seen_ids = set()

    for entry in raw_entries:
        if not isinstance(entry, dict):
            continue
        vid_id = entry.get("id") or ""
        video_url = entry.get("url") or ""

        if not vid_id and video_url:
            m = re.search(r"(?:v=|/v/|youtu\.be/|/shorts/)([\w-]{11})", video_url)
            if m:
                vid_id = m.group(1)

        if not vid_id:
            continue

        if vid_id in seen_ids:
            continue
        seen_ids.add(vid_id)

        if not video_url or not video_url.startswith("http"):
            video_url = f"https://www.youtube.com/watch?v={vid_id}"

        title = entry.get("title") or ""

        # Duration
        dur = entry.get("duration")
        duration_str = entry.get("duration_string") or format_duration(dur)

        # Thumbnail
        thumb = entry.get("thumbnail") or ""
        if not thumb:
            entry_thumbs = entry.get("thumbnails") or []
            if isinstance(entry_thumbs, list) and entry_thumbs:
                for t in reversed(entry_thumbs):
                    if isinstance(t, dict) and t.get("url"):
                        thumb = t["url"]
                        break
        if not thumb:
            thumb = f"https://i.ytimg.com/vi/{vid_id}/hqdefault.jpg"

        videos.append({
            "id": vid_id,
            "url": video_url,
            "title": title,
            "duration": duration_str,
            "thumbnail": thumb,
            "type": "video"
        })

    return {
        "channel": channel_name,
        "channel_id": channel_id,
        "channel_url": channel_url,
        "avatar": avatar,
        "count": len(videos),
        "videos": videos,
        "items": videos,
        "results": videos
    }


async def fetch_and_parse_channel_playlists(channel_input: str) -> dict:
    base_url = normalize_channel_url(channel_input)
    if not base_url:
        raise HTTPException(status_code=400, detail="Invalid YouTube channel URL or identifier.")
        
    target_url = f"{base_url}/playlists"
    try:
        html = await fetch_youtube_html(target_url)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise HTTPException(status_code=404, detail="Channel not found on YouTube.")
        raise HTTPException(status_code=502, detail=f"Failed to fetch channel from YouTube (HTTP {e.code}).")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch channel from YouTube: {str(e)}")

    data = extract_yt_initial_data(html)
    if not data:
        try:
            html = await fetch_youtube_html(base_url)
            data = extract_yt_initial_data(html)
        except Exception:
            pass

    if not data:
        return {
            "channel": "YouTube Channel",
            "channel_id": "",
            "channel_url": base_url,
            "avatar": "",
            "count": 0,
            "playlists": [],
            "items": [],
            "results": []
        }

    channel_meta = extract_channel_metadata(data)
    channel_name = channel_meta.get('title') or 'YouTube Channel'
    
    tab_content, _ = find_tab_content(data, ('Playlists',))
    playlists = extract_playlists_from_tab_content(tab_content, channel_name=channel_name)
    
    if not playlists:
        tabs = data.get('contents', {}).get('twoColumnBrowseResultsRenderer', {}).get('tabs', [])
        for t in tabs:
            tc = t.get('tabRenderer', {}).get('content', {})
            if tc:
                pls = extract_playlists_from_tab_content(tc, channel_name=channel_name)
                if pls:
                    playlists = pls
                    break

    return {
        "channel": channel_name,
        "channel_id": channel_meta.get('channel_id', ''),
        "channel_url": channel_meta.get('channel_url') or base_url,
        "avatar": channel_meta.get('avatar', ''),
        "count": len(playlists),
        "playlists": playlists,
        "items": playlists,
        "results": playlists
    }


# ---------------------------------------------------------------------------
# Search & Channel Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/search")
async def search_youtube(q: str = Query(...)):
    if not q.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")
    
    try:
        url = f"https://www.youtube.com/results?search_query={urllib.parse.quote(q)}"
        html = await fetch_youtube_html(url)
        
        data = extract_yt_initial_data(html)
        if not data:
            match = re.search(r'var ytInitialData = (\{.*?\});</script>', html)
            if match:
                data = json.loads(match.group(1))
                
        if not data:
            return {"results": []}
            
        # Navigate through the JSON structure safely
        contents = []
        try:
            primary_contents = data['contents']['twoColumnSearchResultsRenderer']['primaryContents']['sectionListRenderer']['contents']
            for section in primary_contents:
                if 'itemSectionRenderer' in section:
                    contents.extend(section['itemSectionRenderer']['contents'])
        except KeyError:
            return {"results": []}
            
        results = []
        for item in contents:
            if 'videoRenderer' in item:
                vr = item['videoRenderer']
                try:
                    results.append({
                        'type': 'video',
                        'id': vr['videoId'],
                        'url': f"https://www.youtube.com/watch?v={vr['videoId']}",
                        'title': vr['title']['runs'][0]['text'],
                        'channel': vr.get('longBylineText', {}).get('runs', [{}])[0].get('text', ''),
                        'duration': vr.get('lengthText', {}).get('simpleText', ''),
                        'thumbnail': vr['thumbnail']['thumbnails'][-1]['url']
                    })
                except (KeyError, IndexError):
                    continue
            elif 'channelRenderer' in item:
                cr = item['channelRenderer']
                try:
                    results.append({
                        'type': 'channel',
                        'id': cr['channelId'],
                        'url': f"https://www.youtube.com/channel/{cr['channelId']}",
                        'title': cr['title']['simpleText'],
                        'channel': cr['title']['simpleText'],
                        'handle': cr.get('subscriberCountText', {}).get('simpleText', ''),
                        'thumbnail': cr['thumbnail']['thumbnails'][-1]['url']
                    })
                except (KeyError, IndexError):
                    continue
            elif 'lockupViewModel' in item:
                lvm = item['lockupViewModel']
                try:
                    ctype = lvm.get('contentType', '')
                    content_id = lvm.get('contentId', '')
                    meta = lvm.get('metadata', {}).get('lockupMetadataViewModel', {})
                    title = meta.get('title', {}).get('content', '')
                    img = lvm.get('contentImage', {}).get('thumbnailViewModel', {})
                    sources = img.get('image', {}).get('sources', [])
                    thumb = sources[-1].get('url') if sources else ''
                    
                    if 'CHANNEL' in ctype:
                        results.append({
                            'type': 'channel',
                            'id': content_id,
                            'url': f"https://www.youtube.com/channel/{content_id}",
                            'title': title,
                            'channel': title,
                            'handle': '',
                            'thumbnail': thumb
                        })
                    elif 'VIDEO' in ctype or content_id:
                        duration = ''
                        overlays = img.get('overlays', [])
                        for ov in overlays:
                            badges = ov.get('thumbnailBottomOverlayViewModel', {}).get('badges', [])
                            for b in badges:
                                txt = b.get('thumbnailBadgeViewModel', {}).get('text')
                                if txt:
                                    duration = txt
                                    break
                            if duration:
                                break
                        results.append({
                            'type': 'video',
                            'id': content_id,
                            'url': f"https://www.youtube.com/watch?v={content_id}",
                            'title': title,
                            'channel': '',
                            'duration': duration,
                            'thumbnail': thumb or f"https://i.ytimg.com/vi/{content_id}/hqdefault.jpg"
                        })
                except Exception:
                    continue
                    
        return {"results": results[:15]}
        
    except Exception as e:
        print(f"Search error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/channel/videos")
async def get_channel_videos(
    url: Optional[str] = Query(None),
    channel: Optional[str] = Query(None),
    handle: Optional[str] = Query(None),
    channel_id: Optional[str] = Query(None),
    id: Optional[str] = Query(None),
    q: Optional[str] = Query(None)
):
    inp = url or channel or handle or channel_id or id or q
    if not inp or not inp.strip():
        raise HTTPException(status_code=400, detail="Channel URL, handle, or ID is required.")
    return await fetch_and_parse_channel_videos(inp)


@app.post("/api/channel/videos")
async def post_channel_videos(req: ChannelQueryRequest):
    inp = req.url or req.channel or req.handle or req.channel_id or req.id or req.q
    if not inp or not inp.strip():
        raise HTTPException(status_code=400, detail="Channel URL, handle, or ID is required.")
    return await fetch_and_parse_channel_videos(inp)


@app.get("/api/channel/playlists")
async def get_channel_playlists(
    url: Optional[str] = Query(None),
    channel: Optional[str] = Query(None),
    handle: Optional[str] = Query(None),
    channel_id: Optional[str] = Query(None),
    id: Optional[str] = Query(None),
    q: Optional[str] = Query(None)
):
    inp = url or channel or handle or channel_id or id or q
    if not inp or not inp.strip():
        raise HTTPException(status_code=400, detail="Channel URL, handle, or ID is required.")
    return await fetch_and_parse_channel_playlists(inp)


@app.post("/api/channel/playlists")
async def post_channel_playlists(req: ChannelQueryRequest):
    inp = req.url or req.channel or req.handle or req.channel_id or req.id or req.q
    if not inp or not inp.strip():
        raise HTTPException(status_code=400, detail="Channel URL, handle, or ID is required.")
    return await fetch_and_parse_channel_playlists(inp)

@app.get("/api/playlist-info")
async def get_playlist_info(url: str):
    if not is_valid_youtube_url(url):
        raise HTTPException(status_code=400, detail="Invalid YouTube URL.")
    
    cmd = ["yt-dlp", "--flat-playlist", "--yes-playlist", "-J", "--compat-options", "no-youtube-unavailable-videos", url]
    try:
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await proc.communicate()
        
        if proc.returncode == 0:
            info = json.loads(stdout)
            count = info.get('playlist_count')
            if count is None:
                entries = info.get('entries', [])
                count = len(entries)
                
            title = info.get('title', 'Unknown Playlist')
            return {"count": count, "title": title}
        else:
            raise HTTPException(status_code=400, detail="Could not fetch playlist info")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

def parse_date_string(date_str: str) -> date:
    cleaned = date_str.strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y/%m/%d", "%Y.%m.%d"):
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"Unable to parse date string '{date_str}'. Expected format: YYYY-MM-DD or YYYYMMDD.")

def extract_entry_date(entry: dict) -> Optional[date]:
    upload_date = entry.get('upload_date')
    if upload_date and isinstance(upload_date, str) and len(upload_date) == 8 and upload_date.isdigit():
        try:
            return datetime.strptime(upload_date, "%Y%m%d").date()
        except ValueError:
            pass
    ts = entry.get('timestamp') or entry.get('release_timestamp')
    if ts is not None:
        try:
            return datetime.fromtimestamp(float(ts)).date()
        except Exception:
            pass
    return None

async def resolve_entry_date(entry: dict) -> Optional[date]:
    d = extract_entry_date(entry)
    if d is not None:
        return d
    video_url = entry.get('url')
    if not video_url and entry.get('id'):
        video_url = f"https://www.youtube.com/watch?v={entry['id']}"
    if not video_url:
        return None
    try:
        cmd = ["yt-dlp", "-J", "--no-playlist", video_url]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        if proc.returncode == 0:
            info = json.loads(stdout)
            if 'upload_date' in info:
                entry['upload_date'] = info['upload_date']
            if 'timestamp' in info:
                entry['timestamp'] = info['timestamp']
            return extract_entry_date(entry)
    except Exception:
        pass
    return None

async def find_boundary_index_pid(
    entries: list,
    target_date: date,
    is_upper_bound: bool,
    min_step_threshold_days: float = 1.0,
    kp: float = 0.65,
    ki: float = 0.05,
    kd: float = 0.25
) -> int:
    n = len(entries)
    if n == 0:
        return 0

    date_0 = await resolve_entry_date(entries[0])
    date_last = await resolve_entry_date(entries[-1])

    if is_upper_bound:
        # First index where date <= target_date (newest qualifying item)
        if date_0 is not None and date_0 <= target_date:
            return 0
        if date_last is not None and date_last > target_date:
            return n
    else:
        # First index where date < target_date (boundary where items become too old)
        if date_0 is not None and date_0 < target_date:
            return 0
        if date_last is not None and date_last >= target_date:
            return n

    low = 0
    high = n - 1
    curr = (low + high) // 2
    integral = 0.0
    prev_error = 0.0

    max_iterations = (n.bit_length() + 2) * 2
    iteration = 0

    while low + 1 < high and iteration < max_iterations:
        iteration += 1
        date_curr = await resolve_entry_date(entries[curr])

        if date_curr is None:
            curr = (low + high) // 2
            continue

        # Measure temporal delta in days:
        temporal_delta_days = float((date_curr - target_date).days)

        if is_upper_bound:
            if date_curr <= target_date:
                high = curr
            else:
                low = curr
        else:
            if date_curr < target_date:
                high = curr
            else:
                low = curr

        if low + 1 >= high:
            break

        # Apply minimum 1-day step threshold to avoid hourly oscillation
        if abs(temporal_delta_days) < min_step_threshold_days:
            error = 0.0
        else:
            error = temporal_delta_days

        # PID step computation
        integral += error
        integral = max(-30.0, min(30.0, integral))  # Anti-windup
        derivative = error - prev_error
        prev_error = error

        pid_output = kp * error + ki * integral + kd * derivative

        date_low = await resolve_entry_date(entries[low])
        date_high = await resolve_entry_date(entries[high])
        if date_low and date_high and date_low > date_high:
            bracket_span_days = max(1.0, float((date_low - date_high).days))
            density = float(high - low) / bracket_span_days
        else:
            density = 1.0

        pid_step = pid_output * density

        mid = (low + high) // 2
        if abs(temporal_delta_days) < min_step_threshold_days:
            next_idx = mid
        else:
            pid_target = int(round(curr + pid_step))
            pid_clamped = max(low + 1, min(high - 1, pid_target))
            # Guaranteed logarithmic bracket shrinkage blended with PID guidance
            next_idx = int(round(0.5 * pid_clamped + 0.5 * mid))
            next_idx = max(low + 1, min(high - 1, next_idx))

        curr = next_idx

    return high

async def scan_entries_date_range_pid(entries: list, date_from: date, date_to: date) -> list:
    if not entries:
        return []

    # Verify chronological descending order; reverse if channel tab is ascending
    d0 = await resolve_entry_date(entries[0])
    d_last = await resolve_entry_date(entries[-1])
    if d0 and d_last and d0 < d_last:
        entries = list(reversed(entries))

    # Resolve boundary indices
    start_idx = await find_boundary_index_pid(entries, date_to, is_upper_bound=True)
    end_idx = await find_boundary_index_pid(entries, date_from, is_upper_bound=False)

    if start_idx >= end_idx:
        return []

    # Slice target items
    target_entries = entries[start_idx:end_idx]
    result_items = []
    for entry in target_entries:
        vid_id = entry.get('id')
        url = entry.get('url')
        if not url and vid_id:
            url = f"https://www.youtube.com/watch?v={vid_id}"
        if url:
            d = extract_entry_date(entry)
            d_str = d.strftime("%Y-%m-%d") if d else ""
            result_items.append({
                "id": vid_id or "",
                "url": url,
                "title": entry.get('title') or 'Unknown Title',
                "upload_date": d_str
            })
    return result_items

async def fetch_channel_tab_entries(tab_url: str):
    cmd = [
        "yt-dlp",
        "--flat-playlist",
        "--yes-playlist",
        "-J",
        "--compat-options", "no-youtube-unavailable-videos",
        tab_url
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        if proc.returncode == 0:
            info = json.loads(stdout)
            title = info.get('channel') or info.get('uploader') or info.get('title') or 'YouTube Channel'
            entries = info.get('entries') or []
            return title, entries
    except Exception as e:
        print(f"Error fetching channel tab {tab_url}: {e}")
    return None, []

def determine_channel_tab_urls(url: str, media_types: Optional[List[str]]) -> List[str]:
    base_url = re.sub(r'/(videos|shorts|streams|featured)/?$', '', url.rstrip('/'))
    types = [t.lower() for t in (media_types or ['all'])]
    if 'all' in types:
        return [f"{base_url}/videos", f"{base_url}/shorts", f"{base_url}/streams"]
    
    urls = []
    if 'videos' in types:
        urls.append(f"{base_url}/videos")
    if 'shorts' in types:
        urls.append(f"{base_url}/shorts")
    if 'streams' in types:
        urls.append(f"{base_url}/streams")
    return urls if urls else [url]

async def scan_channel_date_range(request: ChannelScanRequest):
    if not is_valid_youtube_url(request.url):
        raise HTTPException(status_code=400, detail="Invalid YouTube channel URL. Must be from youtube.com or youtu.be.")

    try:
        target_date_from = parse_date_string(request.date_from)
        target_date_to = parse_date_string(request.date_to)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))

    if target_date_from > target_date_to:
        raise HTTPException(status_code=400, detail="From Date cannot be later than To Date.")

    tab_urls = determine_channel_tab_urls(request.url, request.media_types)
    all_matched_items = []
    channel_name = None
    found_any_tab = False

    for tab_url in tab_urls:
        title, entries = await fetch_channel_tab_entries(tab_url)
        if title and not channel_name:
            channel_name = title
        if entries:
            found_any_tab = True
            matched = await scan_entries_date_range_pid(entries, target_date_from, target_date_to)
            all_matched_items.extend(matched)

    if not found_any_tab:
        title, entries = await fetch_channel_tab_entries(request.url)
        if title and not channel_name:
            channel_name = title
        if entries:
            matched = await scan_entries_date_range_pid(entries, target_date_from, target_date_to)
            all_matched_items.extend(matched)

    unique_items = []
    seen_ids = set()
    for item in all_matched_items:
        vid_id = item.get('id') or item.get('url')
        if vid_id and vid_id not in seen_ids:
            seen_ids.add(vid_id)
            unique_items.append(item)

    return {
        "channel_title": channel_name or "Channel",
        "count": len(unique_items),
        "date_from": request.date_from,
        "date_to": request.date_to,
        "items": unique_items
    }

@app.post("/api/channel-scan")
async def channel_scan_endpoint(request: ChannelScanRequest):
    return await scan_channel_date_range(request)

@app.post("/api/download")
async def add_download(request: DownloadRequest):
    # Support batch channel items
    if request.items:
        queued_count = 0
        for item in request.items:
            video_url = item.get('url')
            if not video_url and item.get('id'):
                video_url = f"https://www.youtube.com/watch?v={item['id']}"
            if video_url:
                task_id = secrets.token_hex(8)
                task = {
                    "id": task_id,
                    "url": video_url,
                    "status": "queued",
                    "added_at": datetime.now().isoformat(),
                    "title": item.get('title') or 'Unknown Title',
                    "size": "Calculating...",
                    "progress": 0.0,
                    "eta": "",
                    "cancelled": False,
                    "metadata_fetched": True
                }
                if state_lock:
                    async with state_lock:
                        queued_tasks.append(task)
                else:
                    queued_tasks.append(task)
                await queue.put(task)
                queued_count += 1
        return {"message": f"Successfully queued {queued_count} videos", "count": queued_count}

    if not request.url or not is_valid_youtube_url(request.url):
        raise HTTPException(status_code=400, detail="Invalid YouTube URL. Must be from youtube.com or youtu.be.")
        
    if request.is_playlist:
        asyncio.create_task(fetch_playlist(request.url))
        return {"message": "Parsing playlist in background...", "task_id": "playlist"}
        
    task_id = secrets.token_hex(8)
    task = {
        "id": task_id,
        "url": request.url,
        "status": "queued",
        "added_at": datetime.now().isoformat(),
        "title": "Fetching metadata...",
        "size": "Calculating...",
        "progress": 0.0,
        "eta": "",
        "cancelled": False,
        "metadata_fetched": False
    }
    
    if state_lock:
        async with state_lock:
            queued_tasks.append(task)
    else:
        queued_tasks.append(task)
        
    await queue.put(task)
    asyncio.create_task(fetch_metadata(task))
    
    return {"message": "Added to queue", "task_id": task_id}

@app.get("/api/status")
async def get_status():
    if state_lock:
        async with state_lock:
            return {
                "current": current_task,
                "queued": list(queued_tasks),
                "history": list(history)
            }
    else:
        return {
            "current": current_task,
            "queued": list(queued_tasks),
            "history": list(history)
        }

@app.delete("/api/cancel/{task_id}")
async def cancel_task(task_id: str):
    global active_process, current_task
    
    async with state_lock:
        for t in queued_tasks:
            if t['id'] == task_id:
                t['cancelled'] = True
                t['status'] = 'cancelled'
                queued_tasks.remove(t)
                history.insert(0, t)
                return {"message": "Queued task cancelled"}
                
        if current_task and current_task['id'] == task_id:
            current_task['cancelled'] = True
            if active_process and active_process.returncode is None:
                try:
                    active_process.terminate()
                except Exception:
                    pass
            return {"message": "Active task cancelled"}
            
    raise HTTPException(status_code=404, detail="Task not found")

frontend_dir = "/app/frontend" if os.path.exists("/app/frontend") else os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.exists(frontend_dir):
    app.mount("/", CacheControlledStaticFiles(directory=frontend_dir, html=True), name="frontend")
