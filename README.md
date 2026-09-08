# YouTube Jellyfin Downloader

A lightweight web application and sidecar service designed to seamlessly download and organize YouTube videos, playlists, and channels directly into your Jellyfin media library.

## Quickstart

### 1. Clone the Repository

Clone this repository into the same directory as your server's `docker-compose.yml`:

```bash
git clone https://github.com/strangeones/yt-jellyfin-downloader.git youtube-archive
```

### 2. Docker Compose Configuration

Add the `yt-jellyfin-downloader` service snippet to your existing `docker-compose.yml`:

```yaml
services:
  yt-jellyfin-downloader:
    build:
      # Path to the cloned repository directory relative to docker-compose.yml
      context: ./youtube-archive
      dockerfile: Dockerfile
    container_name: yt-jellyfin-downloader
    restart: unless-stopped
    ports:
      - "8000:8000"
    environment:
      # Optional: Initial credentials auto-migrated into /app/data/auth.json on first run
      - APP_USERNAME=admin
      - APP_PASSWORD=supersecretpassword
    volumes:
      # Persistent storage for authentication credentials (auth.json)
      - ./data:/app/data
      # Map your host media library directory to /app/media inside the container
      - /path/to/your/jellyfin/youtube/library:/app/media
```

#### Volume Mounts

| Host Path | Container Path | Purpose |
| :--- | :--- | :--- |
| `./data` | `/app/data` | Persistent storage for authentication credentials (`auth.json`), session tokens, and local state across container rebuilds. |
| `/path/to/your/jellyfin/youtube/library` | `/app/media` | Target directory where downloaded videos, thumbnails, and metadata are saved for Jellyfin ingestion. |

### 3. Build & Run

Start the service using Docker Compose:

```bash
docker compose up -d --build
```

Access the web interface at `http://<your-server-ip>:8000`.

---

## Authentication & Password Management

- **First Run**: If `APP_USERNAME` and `APP_PASSWORD` are specified in `docker-compose.yml`, they are automatically hashed (bcrypt) and saved to `/app/data/auth.json`. If omitted, initial setup is prompted via the Web UI.
- **Web UI Management**: Change passwords anytime through the in-app Account Settings modal. Full browser password manager autofill (Keychain, Bitwarden, 1Password) is supported.
- **Emergency CLI Password Reset**:
  ```bash
  docker compose exec yt-jellyfin-downloader python3 -m backend.auth reset-password --password "YOUR_NEW_PASSWORD"
  ```

---

## Updating

To update the application to the latest version:

```bash
cd ./youtube-archive
git pull origin main
cd ..
docker compose up -d --build yt-jellyfin-downloader
```

For detailed deployment and maintenance instructions, refer to [update-guide.md](update-guide.md).