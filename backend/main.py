import asyncio
import os
import re
import base64
import secrets
import json
from datetime import datetime
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

AUTH_USER = os.getenv("APP_USERNAME", "admin")
AUTH_PASS = os.getenv("APP_PASSWORD", "password")
AUTO_UPDATE_YTDLP = os.getenv("AUTO_UPDATE_YTDLP", "false").lower() == "true"

app = FastAPI()

@app.middleware("http")
async def basic_auth_middleware(request: Request, call_next):
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Basic "):
        return Response(
            content="Unauthorized",
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="YT Downloader"'}
        )
    try:
        decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
        username, password = decoded.split(":", 1)
        if not (secrets.compare_digest(username, AUTH_USER) and secrets.compare_digest(password, AUTH_PASS)):
            raise Exception()
    except Exception:
        return Response(
            content="Unauthorized",
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="YT Downloader"'}
        )
    return await call_next(request)

class DownloadRequest(BaseModel):
    url: str
    is_playlist: bool = False

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
    asyncio.create_task(update_yt_dlp())
    asyncio.create_task(process_queue())

@app.get("/api/playlist-info")
async def get_playlist_info(url: str):
    if not is_valid_youtube_url(url):
        raise HTTPException(status_code=400, detail="Invalid YouTube URL.")
    
    cmd = ["yt-dlp", "--flat-playlist", "-J", "--compat-options", "no-youtube-unavailable-videos", url]
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

@app.post("/api/download")
async def add_download(request: DownloadRequest):
    if not is_valid_youtube_url(request.url):
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

app.mount("/", StaticFiles(directory="/app/frontend", html=True), name="frontend")
