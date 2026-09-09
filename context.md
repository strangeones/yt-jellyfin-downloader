# Project Context & Session State

**Project**: `youtube-archive` (YouTube to Jellyfin Downloader Sidecar)  
**Repository**: `https://github.com/strangeones/yt-jellyfin-downloader.git` (`main` branch)  
**Last Updated**: September 9, 2026  

---

## 1. Golden Operational Rules

1. **Orchestrator Rules ([`orchestrator-rules.md`](file:///Users/henrystrange/Documents/Antigravity_Projects/youtube-archive/orchestrator-rules.md))**:
   - Environment verification (`HERDR_ENV=1`).
   - State isolation: never work in active directory directly; use git worktrees (`sandbox-<name>-worker`).
   - Spawn subagents in Herdr panes using `herdr pane split` and `herdr agent start`.
   - Generator-Verifier split: coding subagents NEVER verify their own code. Spawn a separate QA & Security Auditor agent in `sandbox-<name>-qa`.
2. **Commit Policy**:
   - **MANDATORY**: Git commits must **ONLY** happen **AFTER** the independent QA Auditor sub-agent has completed its adversarial testing suite and issued an explicit **PASS** verdict.
   - **QA Targeting Rule**: QA Auditors MUST identify and review the code for the *latest* feature in the **Completed Milestones & Git History** table, rather than arbitrarily reviewing old milestones.
   - Once QA passes and merges to `main`, updates must be committed and pushed to `origin/main` on GitHub.

---

## 2. Completed Milestones & Git History

| Commit | Summary | Key Additions |
| :--- | :--- | :--- |
| [`0466525`](https://github.com/strangeones/yt-jellyfin-downloader/commit/0466525) | **Fix: Search UI Variables** | Updated the search results container in `style.css` to use the 'Craft Media Ingest' custom properties (`--bg-card`, `--border-hairline`, `--bg-surface`, etc.) to match the aesthetic standard perfectly. |
| [`28e0b3f`](https://github.com/strangeones/yt-jellyfin-downloader/commit/28e0b3f) | **Feature: Integrated Lightning-Fast YouTube Search** | Converted the single URL input into a Unified Omnibox (`type="text"`); intercepted text queries via `app.js` to dispatch a search instead of a URL download; built an insanely fast custom Python backend scraper in `main.py` (`/api/search`) parsing `ytInitialData` to support instant queries for both Videos and Channels without needing an API key; added an inline animated search results UI in `index.html` that automatically selects the appropriate download mode (Single/Channel) and triggers queue submission when a result is clicked. |
| [`7f7ef33`](https://github.com/strangeones/yt-jellyfin-downloader/commit/7f7ef33) | **Fix Playlist Toggle Accessibility & Parity** | Replaced `display: none` with accessible visually-hidden CSS + `:focus-visible` focus rings; added playlist URL auto-detection on `input`/`paste`; added `--yes-playlist` parity to [`get_playlist_info()`](file:///Users/henrystrange/Documents/Antigravity_Projects/youtube-archive/backend/main.py). |
| [`7573dc4`](https://github.com/strangeones/yt-jellyfin-downloader/commit/7573dc4) | **Chore: Add .gitignore** | Ignored `.DS_Store`, `__pycache__/`, `*.pyc`. |
| [`22e8916`](https://github.com/strangeones/yt-jellyfin-downloader/commit/22e8916) | **Channel Date-Range Logarithmic Search** | 3-way segmented control (`Single Video` \| `Playlist / Mix` \| `Channel`); adjacent glassmorphic date pickers; media checkboxes (`All Media` vs `Videos`, `Shorts`, `Live Streams`) with mutual exclusivity; PID-damped step controller with **1-day minimum step threshold**; confirmation preview modal; batch download queueing. |
| [`f2cc6d5`](https://github.com/strangeones/yt-jellyfin-downloader/commit/f2cc6d5) | **Persistent Local Password & Session System** | Created [`backend/auth.py`](file:///Users/henrystrange/Documents/Antigravity_Projects/youtube-archive/backend/auth.py) with `bcrypt` (work factor 12) and `/app/data/auth.json` (chmod 600); 30-day `HttpOnly` `SameSite=Lax` session cookies; WHATWG autofill compatibility (Apple Keychain, Bitwarden, 1Password); in-app password changes; auto-migration from legacy `APP_PASSWORD`; headless CLI reset tool. |
| [`11e47d7`](https://github.com/strangeones/yt-jellyfin-downloader/commit/11e47d7) | **Fix: Set docker build context to ./youtube-archive** | Updated `docker-compose-snippet.yml`, `update-guide.md`, and `README.md` to reference the renamed repository directory `./youtube-archive`. |
| [`8c9b64a`](https://github.com/strangeones/yt-jellyfin-downloader/commit/8c9b64a) | **Feature: Dual Light/Dark Aesthetic & Theme Switcher** | Professional "Craft Media Ingest" design system with both Light and Dark themes; interactive Sun/Moon theme switcher toggle with `localStorage` persistence and OS `prefers-color-scheme` fallback; 3-way segmented control with inline SVGs for Single Video, Playlist/Mix, and Channel; static spotlight vignette replacing blur blobs; `tabular-nums` typography; and `CacheControlledStaticFiles` + `Cache-Control: no-cache, no-store, must-revalidate` HTTP headers + cache-busting query strings `?v=2.1.0`. |

---

## 3. Deployment & Update Workflow

### Docker Compose Volume Configuration:
To ensure persistent credentials across restarts, `docker-compose.yml` requires:
```yaml
services:
  yt-jellyfin-downloader:
    build:
      context: ./youtube-archive
      dockerfile: Dockerfile
    container_name: yt-jellyfin-downloader
    restart: unless-stopped
    ports:
      - "8000:8000"
    volumes:
      - ./data:/app/data                         # Persistent credential database
      - /path/to/your/jellyfin/library:/app/media # Jellyfin library mount
```

### Pulling Updates to Server:
```bash
cd ~/arr_stack/youtube-archive
git pull origin main
cd ..
docker compose up -d --build yt-jellyfin-downloader
```

### Emergency Password Reset (Headless Host Command):
```bash
docker compose exec yt-jellyfin-downloader python3 -m backend.auth reset-password --password <NEW_PASSWORD>
```

---

## 4. Current State & Completed Aesthetic Milestone

### Aesthetic Transformation: "Craft Media Ingest"
- **Status**: Implemented, rigorously tested by independent QA Auditor with 16/16 test PASS, committed, and pushed to `origin/main`.
- **Features Active**:
  - **Dual Light / Dark Mode**: Obsidian `#09090b` dark theme with hairline borders and top specular bevels; crisp Zinc `#f8fafc` light theme with clean white cards and deep slate typography.
  - **Theme Toggle**: Accessible Sun/Moon toggle button in header, syncing with `localStorage` and OS `prefers-color-scheme`.
  - **Prominent 3-Way Segmented Control**: Distinct icons and labels for `Single Video`, `Playlist/Mix`, and `Channel`, immediately revealing date pickers and media filters when Channel is clicked.
  - **Cache Prevention**: `CacheControlledStaticFiles` and `Cache-Control: no-cache, no-store, must-revalidate` response headers, combined with `?v=2.1.0` query strings on CSS and JS.
  - **Anti-Jitter Typography**: Tabular numerals (`font-variant-numeric: tabular-nums`) applied across telemetry, progress, badges, and counters.
