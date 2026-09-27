# Netuark Media Server — Self-Hosted Android Media CDN

> Run a media server on an Android phone (Termux), exposed permanently to the internet via Cloudflare Pages. Zero cloud storage costs. No API keys needed by callers.

---

## Architecture

```
Netuark App
    │
    ▼
https://ntamediaserver.pages.dev   ← permanent URL, never changes
    │  (Cloudflare Pages — reverse proxies to live phone tunnel)
    │  (discovers live URL from endpoint.json on GitHub, refreshes every 10s)
    ▼
https://xxxx.trycloudflare.com     ← changes on restart, auto-registered
    │
    ▼
Flask server on phone (port 3000)
    │
    ▼
/sdcard/Download/NetuarkMedia/     ← actual files (feed, chat, videos, docs)
```

**Two phones run simultaneously** — one MASTER (serves traffic), one BACKUP (syncs files, takes over if master dies).

---

## API Endpoints

All requests go to `https://ntamediaserver.pages.dev`. No auth required.

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `POST` | `/upload` | Upload a file. Form fields: `file` (binary), `type` (`feed` \| `chat` \| `videos` \| `docs`) |
| `GET` | `/media/<type>/<filename>` | Serve a media file |
| `DELETE` | `/media/<folder>/<filename>` | Delete a media file locally and broadcast deletion across cluster |
| `PUT` | `/v1/storage/objects/<folder>/<filename>` | REST upload (raw binary body) |
| `GET` | `/v1/storage/objects/<folder>/<filename>` | REST serve |
| `DELETE` | `/v1/storage/objects/<folder>/<filename>` | REST delete object and broadcast across cluster |
| `GET` | `/api/sync/list` | Returns JSON map of all files + sizes (used for inter-device sync) |
| `GET` | `/register_tunnel` | Returns currently active tunnel origin |

**Delete File Examples:**
```bash
# Standard Media Route:
curl -X DELETE "https://ntamediaserver.pages.dev/media/videos/1727400000_myvideo.mp4"

# REST Storage Route:
curl -X DELETE "https://ntamediaserver.pages.dev/v1/storage/objects/chat/1727400000_image.jpg"
```

**Storage folders:**

| `type` param | Physical path on phone |
| :--- | :--- |
| `feed` | `/sdcard/Download/NetuarkMedia/feed/` |
| `chat` | `/sdcard/Download/NetuarkMedia/chat/` |
| `videos` | `/sdcard/Download/NetuarkMedia/videos/` |
| `docs` | `/sdcard/Download/NetuarkMedia/docs/` |

---

## Phone Setup (Termux — run once)

```bash
# 1. Install deps
pkg update -y && pkg install python git cloudflared -y
pip install flask

# 2. Clone the repo
git clone https://github.com/Beeta-inc/ntamediaserver.git ~/ntamediaserver
cd ~/ntamediaserver

# 3. Allow storage access
termux-setup-storage
```

---

## Running the Server

```bash
cd ~/ntamediaserver
bash start_cluster.sh
```

This starts both `server.py` (port 3000) and `auto_tunnel.py` in the background with logs at `server.log` and `tunnel.log`.

**What `auto_tunnel.py` does automatically on start:**
1. Launches `cloudflared` tunnel → gets a `trycloudflare.com` URL
2. POSTs the URL to `https://ntamediaserver.pages.dev/register_tunnel` — Pages knows immediately
3. Pushes `endpoint.json` to GitHub — Pages survives cold restarts
4. Sends heartbeats every 10s to Firebase for Master/Backup election
5. If Master dies (no heartbeat for 30s), Backup auto-promotes itself

---

## Cloudflare Pages Setup (one time)

1. Go to [dash.cloudflare.com](https://dash.cloudflare.com) → **Workers & Pages → Create → Pages**
2. **Connect to Git** → select `Beeta-inc/ntamediaserver`
3. Build settings:
   - Framework preset: **None**
   - Build command: *(blank)*
   - Build output directory: `.`
4. **Save and Deploy**

Your permanent URL: `https://ntamediaserver.pages.dev`

---

## File Sync Between Two Phones

`auto_tunnel.py` has a built-in background sync loop:
- Backup phone checks master's `/api/sync/list` every 5s
- Downloads any missing or size-mismatched files concurrently (5 threads)
- No Syncthing required — it's all built in

For physical file sharing (optional fallback): use **Syncthing** on both phones pointed at `/sdcard/Download/NetuarkMedia`.

---

## Firebase Config

Two Firebase projects are used:

| Project | Variable | Purpose |
| :--- | :--- | :--- |
| Main app Firebase | `MAIN_FIRESTORE_URL` | Stores active tunnel URL — Netuark app reads this |
| Sync Firebase | `SYNC_FIRESTORE_URL` | Master/Backup election + heartbeats + telemetry |

Both are in `auto_tunnel.py` at the top. Edit before running if needed.

---

## Logs

```bash
tail -f ~/ntamediaserver/server.log   # Flask server
tail -f ~/ntamediaserver/tunnel.log   # Cloudflare tunnel + sync
```
