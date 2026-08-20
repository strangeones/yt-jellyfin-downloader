# YouTube Jellyfin Downloader - Deployment & Update Guide

This guide explains how to deploy and update the YouTube Jellyfin Downloader sidecar alongside your existing Jellyfin media stack using Docker Compose.

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
         # Map to your host's YouTube library directory
         - /path/to/your/jellyfin/youtube/library:/app/media
   ```

3. **Adjust settings**:
   - Update `APP_USERNAME` and `APP_PASSWORD`.
   - Update the `/path/to/your/jellyfin/youtube/library` to match the exact directory Jellyfin uses for your YouTube media library.

4. **Build and start the container**:
   ```bash
   docker compose up -d --build
   ```

## 2. Updating the Application

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

## 3. Server Maintenance

If the underlying host system (e.g., Ubuntu/Debian) needs updates, standard maintenance procedures apply. It's a good practice to run this periodically:
```bash
sudo apt update && sudo apt upgrade -y
```
