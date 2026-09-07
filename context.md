# Project Context & Session State

**Project**: `youtube-archive` (YouTube to Jellyfin Downloader Sidecar)  
**Repository**: `https://github.com/strangeones/yt-jellyfin-downloader.git` (`main` branch)  
**Last Updated**: September 7, 2026  

---

## 1. Golden Operational Rules

1. **Orchestrator Rules ([`orchestrator-rules.md`](file:///Users/henrystrange/Documents/Antigravity_Projects/youtube-archive/orchestrator-rules.md))**:
   - Environment verification (`HERDR_ENV=1`).
   - State isolation: never work in active directory directly; use git worktrees (`sandbox-<name>-worker`).
   - Spawn subagents in Herdr panes using `herdr pane split` and `herdr agent start`.
   - Generator-Verifier split: coding subagents NEVER verify their own code. Spawn a separate QA & Security Auditor agent in `sandbox-<name>-qa`.
2. **Commit Policy**:
   - **MANDATORY**: Git commits must **ONLY** happen **AFTER** the independent QA Auditor sub-agent has completed its adversarial testing suite and issued an explicit **PASS** verdict.
   - Once QA passes and merges to `main`, updates must be committed and pushed to `origin/main` on GitHub.

---

## 2. Completed Milestones & Git History

| Commit | Summary | Key Additions |
| :--- | :--- | :--- |
| [`7f7ef33`](https://github.com/strangeones/yt-jellyfin-downloader/commit/7f7ef33) | **Fix Playlist Toggle Accessibility & Parity** | Replaced `display: none` with accessible visually-hidden CSS + `:focus-visible` focus rings; added playlist URL auto-detection on `input`/`paste`; added `--yes-playlist` parity to [`get_playlist_info()`](file:///Users/henrystrange/Documents/Antigravity_Projects/youtube-archive/backend/main.py). |
| [`7573dc4`](https://github.com/strangeones/yt-jellyfin-downloader/commit/7573dc4) | **Chore: Add .gitignore** | Ignored `.DS_Store`, `__pycache__/`, `*.pyc`. |
| [`22e8916`](https://github.com/strangeones/yt-jellyfin-downloader/commit/22e8916) | **Channel Date-Range Logarithmic Search** | 3-way segmented control (`Single Video` \| `Playlist / Mix` \| `Channel`); adjacent glassmorphic date pickers; media checkboxes (`All Media` vs `Videos`, `Shorts`, `Live Streams`) with mutual exclusivity; PID-damped step controller with **1-day minimum step threshold**; confirmation preview modal; batch download queueing. |
| [`f2cc6d5`](https://github.com/strangeones/yt-jellyfin-downloader/commit/f2cc6d5) | **Persistent Local Password & Session System** | Created [`backend/auth.py`](file:///Users/henrystrange/Documents/Antigravity_Projects/youtube-archive/backend/auth.py) with `bcrypt` (work factor 12) and `/app/data/auth.json` (chmod 600); 30-day `HttpOnly` `SameSite=Lax` session cookies; WHATWG autofill compatibility (Apple Keychain, Bitwarden, 1Password); in-app password changes; auto-migration from legacy `APP_PASSWORD`; headless CLI reset tool. |

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
cd ./youtube-archive
git pull origin main
cd ..
docker compose up -d --build yt-jellyfin-downloader
```

### Emergency Password Reset (Headless Host Command):
```bash
docker compose exec yt-jellyfin-downloader python3 -m backend.auth reset-password --password <NEW_PASSWORD>
```

---

## 4. Current State & Immediate Next Milestone

### Aesthetic Transformation: "Craft Media Ingest"
- **Status**: Deep research completed by Design Lead and 3 specialized subagents (DevTools Craft Specialist, Media Ecosystem Designer, Design Systems Architect).
- **Proposal Document**: Available in detail at:
  [`aesthetic_design_proposal.md`](file:///Users/henrystrange/.gemini/antigravity-cli/brain/18adba33-8f7f-4a23-87e7-21342dd045a8/aesthetic_design_proposal.md)
- **Objective**: Replace the current "vibecoded" aesthetic (floating neon purple blobs, heavy blur filters, continuous GPU animations) with a high-craft, professional media tool:
  - Solid `#09090B` Obsidian background with subtle static vignette.
  - Hairline borders (`rgba(255, 255, 255, 0.08)`) with top specular bevels.
  - 16:9 thumbnail previews with duration badges and technical spec pills (`4K UHD`, `1080p`, `VP9`, `Opus`).
  - 3-tier ingest hierarchy: **Active Hero Card** (live `MB/s` velocity + 3px progress rail), **Staged Queue Deck**, and **Completed History Ledger**.
  - `tabular-nums` typography to eradicate polling number jitter.
