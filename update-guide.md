# YouTube Jellyfin Downloader - Deployment & Update Guide

This guide explains how to deploy, manage, and update the YouTube Jellyfin Downloader sidecar alongside your existing Jellyfin media stack using Docker Compose.

## 1. Initial Deployment

1. **Clone the repository** to your server (e.g., in the same directory as your existing `docker-compose.yml`):
   ```bash
   git clone https://github.com/your-username/youtube-archive.git
   ```

2. **Add the service** to your existing `docker-compose.yml` media stack. Open your existing `docker-compose.yml` and append the contents of `youtube-archive/sandbox-infra/docker-compose-snippet.yml`. It should look similar to this:
   ```yaml
   services:
     # ... your existing services (jellyfin, sonarr, radarr, etc.) ...

     yt-jellyfin-downloader:
       build: 
         context: ./youtube-archive/sandbox-infra
         dockerfile: Dockerfile
       container_name: yt-jellyfin-downloader
       restart: unless-stopped
       ports:
         - "8000:8000"
       environment:
         - APP_USERNAME=admin
         - APP_PASSWORD=supersecretpassword
       volumes:
         # Persistent storage for credentials (auth.json)
         - ./data:/app/data
         # Map to your host's YouTube library directory
         - /path/to/your/jellyfin/youtube/library:/app/media
   ```

3. **Adjust settings**:
   - `APP_USERNAME` and `APP_PASSWORD`: If provided, these are automatically imported into `/app/data/auth.json` on the first launch and hashed with bcrypt. If omitted, the web interface will prompt for initial setup on first visit.
   - Volume `./data:/app/data`: Ensures your credentials, password hashes, and local settings persist across container rebuilds and updates.
   - Volume `/path/to/your/jellyfin/youtube/library:/app/media`: Match the exact directory Jellyfin uses for your YouTube media library.

4. **Build and start the container**:
   ```bash
   docker compose up -d --build
   ```

## 2. Password & Credential Management

### Web UI
- You can log in with full browser password manager autofill support (compatible with Apple Keychain, 1Password, Bitwarden, and Google Password Manager).
- Once logged in, click your username badge in the top right to open the **Account Settings** modal where you can change your password or log out.

### CLI Password Reset
If you ever get locked out or need to reset your password via the command line:

**Docker Compose:**
```bash
docker compose exec yt-jellyfin-downloader python3 -m backend.auth reset-password --password "YOUR_NEW_PASSWORD"
```

**Local / Standalone Environment:**
```bash
python3 -m backend.auth reset-password --password "YOUR_NEW_PASSWORD"
```
*(Optional: You can also specify `--username <USER>` if running multi-user or non-admin).*

The reset command writes directly to the persistent credential store (`auth.json`) with strict `0600` file permissions and terminates existing active sessions.

## 3. Updating the Application

When new features or bug fixes are released, you can update your sidecar easily. Follow these steps from the directory containing your `docker-compose.yml`:

1. **Navigate to the codebase directory**:
   ```bash
   cd ./youtube-archive
   ```

2. **Pull the latest code from Git**:
   ```bash
   git pull origin main
   ```
   *(If you are on a different branch, specify that branch instead)*

3. **Navigate back to your Docker Compose directory**:
   ```bash
   cd ..
   ```

4. **Rebuild and restart the container**:
   Running this command will force Docker to rebuild the container image with the newly pulled code and seamlessly recreate the container:
   ```bash
   docker compose up -d --build yt-jellyfin-downloader
   ```

5. **Clean up old unused images** (Optional but recommended to save disk space):
   ```bash
   docker image prune -f
   ```

## 4. Server Maintenance

If the underlying host system (e.g., Ubuntu/Debian) needs updates, standard maintenance procedures apply. It's a good practice to run this periodically:
```bash
sudo apt update && sudo apt upgrade -y
```
