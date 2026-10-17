import os
import time
import urllib.request
import urllib.parse
import json
import sys
import subprocess
import shutil
import gc
from flask import Flask, request, jsonify, send_from_directory, render_template_string
from werkzeug.utils import secure_filename

import telemetry

# Attempt to load configuration from auto_tunnel
try:
    import auto_tunnel
    SYNC_URL = auto_tunnel.SYNC_FIRESTORE_URL
except Exception:
    SYNC_URL = "https://firestore.googleapis.com/v1/projects/ntamedia-1f03d/databases/(default)/documents/serverSync/coordinator"

app = Flask(__name__)

# Base storage directories on the phone's public visible storage
BASE_DIR = '/sdcard/Download/NetuarkMedia'

# Ensure base directory exists
os.makedirs(BASE_DIR, exist_ok=True)

# Standard directories
FEED_DIR = os.path.join(BASE_DIR, 'feed')
CHAT_DIR = os.path.join(BASE_DIR, 'chat')
VIDEO_DIR = os.path.join(BASE_DIR, 'videos')
DOC_DIR = os.path.join(BASE_DIR, 'docs')

for d in [FEED_DIR, CHAT_DIR, VIDEO_DIR, DOC_DIR]:
    os.makedirs(d, exist_ok=True)

def get_folder_path(folder):
    """Dynamically resolves and creates any storage folder inside BASE_DIR."""
    if not folder:
        folder = 'chat'
    folder_safe = secure_filename(str(folder).strip().lower())
    if not folder_safe:
        folder_safe = 'chat'
    target_dir = os.path.join(BASE_DIR, folder_safe)
    os.makedirs(target_dir, exist_ok=True)
    return target_dir

# Negative cache for 404 lookups (prevents hammering peers repeatedly for missing files)
_404_CACHE = {}
_404_CACHE_TTL = 30  # seconds

def is_negative_cached(key):
    now = time.time()
    ts = _404_CACHE.get(key)
    if ts and (now - ts) < _404_CACHE_TTL:
        return True
    return False

def set_negative_cache(key):
    _404_CACHE[key] = time.time()
    # Prune old entries periodically
    if len(_404_CACHE) > 500:
        now = time.time()
        for k in list(_404_CACHE.keys()):
            if now - _404_CACHE[k] >= _404_CACHE_TTL:
                del _404_CACHE[k]

@app.after_request
def add_cors_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, Range'
    response.headers['Access-Control-Expose-Headers'] = 'Accept-Ranges, Content-Encoding, Content-Length, Content-Range'
    return response

@app.route('/docs')
def docs():
    docs_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'docs.html')
    if os.path.exists(docs_path):
        with open(docs_path, 'r', encoding='utf-8') as f:
            return f.read(), 200, {'Content-Type': 'text/html; charset=utf-8'}
    return "Docs not found", 404

@app.route('/api/telemetry')
@app.route('/telemetry')
def get_telemetry_endpoint():
    device_id = ""
    if os.path.exists('.device_id'):
        try:
            with open('.device_id', 'r') as f:
                device_id = f.read().strip()
        except Exception:
            pass
    current_url = ""
    try:
        if 'auto_tunnel' in sys.modules:
            current_url = getattr(auto_tunnel, 'current_url', '') or ""
    except Exception:
        pass
    return jsonify(telemetry.get_full_telemetry(device_id=device_id, current_url=current_url)), 200

@app.route('/')
def index():
    return f"""
    <!DOCTYPE html>
    <html lang="en">
        <head>
            <title>Netuark HA Media Cluster — Live Dashboard</title>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <link rel="preconnect" href="https://fonts.googleapis.com">
            <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
            <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
            <style>
                :root {{
                    --bg-dark: #070b13;
                    --card-bg: #0f172a;
                    --border: #1e293b;
                    --cyan: #00f3ff;
                    --emerald: #10b981;
                    --amber: #f59e0b;
                    --rose: #f43f5e;
                    --blue: #3b82f6;
                    --purple: #a855f7;
                    --text-main: #f8fafc;
                    --text-sub: #94a3b8;
                }}
                * {{ box-sizing: border-box; margin: 0; padding: 0; }}
                body {{
                    font-family: 'Plus Jakarta Sans', -apple-system, sans-serif;
                    background: var(--bg-dark);
                    color: var(--text-main);
                    padding: 24px 16px;
                    max-width: 1040px;
                    margin: 0 auto;
                    line-height: 1.5;
                }}
                .top-bar {{
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    padding-bottom: 20px;
                    border-bottom: 1px solid var(--border);
                    margin-bottom: 24px;
                }}
                .brand-title {{
                    font-size: 20px;
                    font-weight: 800;
                    letter-spacing: -0.02em;
                    display: flex;
                    align-items: center;
                    gap: 8px;
                }}
                .brand-badge {{
                    font-family: 'JetBrains Mono', monospace;
                    font-size: 11px;
                    background: rgba(0, 243, 255, 0.1);
                    color: var(--cyan);
                    padding: 3px 8px;
                    border-radius: 6px;
                    border: 1px solid rgba(0, 243, 255, 0.2);
                }}
                .docs-btn {{
                    background: linear-gradient(135deg, #10b981, #059669);
                    color: #fff;
                    padding: 8px 16px;
                    border-radius: 8px;
                    text-decoration: none;
                    font-weight: 700;
                    font-size: 13px;
                    display: flex;
                    align-items: center;
                    gap: 6px;
                    transition: opacity 0.2s;
                }}
                .docs-btn:hover {{ opacity: 0.9; }}
                
                .summary-banner {{
                    background: var(--card-bg);
                    border: 1px solid var(--border);
                    border-radius: 12px;
                    padding: 16px 20px;
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    flex-wrap: wrap;
                    gap: 12px;
                    margin-bottom: 24px;
                }}
                .summary-item {{ display: flex; flex-direction: column; }}
                .summary-label {{ font-size: 11px; font-family: 'JetBrains Mono', monospace; color: var(--text-sub); text-transform: uppercase; }}
                .summary-value {{ font-size: 15px; font-weight: 700; color: #fff; display: flex; align-items: center; gap: 6px; }}
                
                .pulse-dot {{
                    width: 8px;
                    height: 8px;
                    border-radius: 50%;
                    background: var(--emerald);
                    box-shadow: 0 0 10px var(--emerald);
                    animation: pulse 2s infinite;
                }}
                @keyframes pulse {{
                    0% {{ transform: scale(0.95); opacity: 0.8; }}
                    50% {{ transform: scale(1.3); opacity: 1; }}
                    100% {{ transform: scale(0.95); opacity: 0.8; }}
                }}
                
                .section-header {{
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    margin-bottom: 16px;
                }}
                .section-title {{
                    font-size: 16px;
                    font-weight: 700;
                    letter-spacing: -0.01em;
                    color: #fff;
                }}
                .sync-timer {{
                    font-family: 'JetBrains Mono', monospace;
                    font-size: 11px;
                    color: var(--text-sub);
                }}
                
                .dashboard-grid {{
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
                    gap: 16px;
                    margin-bottom: 28px;
                }}
                .node-card {{
                    background: var(--card-bg);
                    border: 1px solid var(--border);
                    border-radius: 12px;
                    padding: 20px;
                    position: relative;
                    transition: border-color 0.2s;
                }}
                .node-card.master {{ border-color: rgba(16, 185, 129, 0.5); }}
                .node-card.phone {{ border-color: rgba(0, 243, 255, 0.4); }}
                .node-card.offline {{ opacity: 0.7; border-color: rgba(244, 63, 94, 0.3); }}
                
                .card-header {{
                    display: flex;
                    justify-content: space-between;
                    align-items: flex-start;
                    margin-bottom: 14px;
                }}
                .node-title {{
                    font-size: 15px;
                    font-weight: 700;
                    color: #fff;
                }}
                .node-sub {{
                    font-size: 11px;
                    font-family: 'JetBrains Mono', monospace;
                    color: var(--text-sub);
                    margin-top: 2px;
                }}
                
                .badge {{
                    font-family: 'JetBrains Mono', monospace;
                    font-size: 10px;
                    font-weight: 700;
                    padding: 3px 8px;
                    border-radius: 999px;
                    text-transform: uppercase;
                }}
                .badge.active {{ background: rgba(16, 185, 129, 0.15); color: var(--emerald); border: 1px solid rgba(16, 185, 129, 0.3); }}
                .badge.standby {{ background: rgba(245, 158, 11, 0.15); color: var(--amber); border: 1px solid rgba(245, 158, 11, 0.3); }}
                .badge.offline {{ background: rgba(244, 63, 94, 0.15); color: var(--rose); border: 1px solid rgba(244, 63, 94, 0.3); }}
                
                .metric-row {{
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    font-size: 12px;
                    padding: 6px 0;
                    border-top: 1px solid rgba(255,255,255,0.05);
                }}
                .metric-label {{ color: var(--text-sub); display: flex; align-items: center; gap: 5px; }}
                .metric-val {{ font-family: 'JetBrains Mono', monospace; color: #fff; text-align: right; }}
                
                .bar-container {{
                    background: rgba(255,255,255,0.06);
                    height: 6px;
                    border-radius: 3px;
                    overflow: hidden;
                    margin-top: 4px;
                    margin-bottom: 4px;
                }}
                .bar-fill {{
                    height: 100%;
                    border-radius: 3px;
                    background: var(--blue);
                    transition: width 0.3s ease;
                }}
                .bar-fill.green {{ background: var(--emerald); }}
                .bar-fill.amber {{ background: var(--amber); }}
                .bar-fill.rose {{ background: var(--rose); }}
                .bar-fill.cyan {{ background: var(--cyan); }}
                .bar-fill.purple {{ background: var(--purple); }}
                
                .folder-chips {{
                    display: flex;
                    flex-wrap: wrap;
                    gap: 6px;
                    margin-top: 8px;
                    padding-top: 8px;
                    border-top: 1px dashed rgba(255,255,255,0.08);
                }}
                .folder-chip {{
                    font-family: 'JetBrains Mono', monospace;
                    font-size: 10px;
                    padding: 3px 6px;
                    background: rgba(255,255,255,0.04);
                    border: 1px solid rgba(255,255,255,0.08);
                    border-radius: 4px;
                    color: var(--text-sub);
                }}
                .folder-chip span {{ color: #fff; font-weight: 600; }}
                
                .tunnel-link {{
                    display: block;
                    font-family: 'JetBrains Mono', monospace;
                    font-size: 11px;
                    color: var(--cyan);
                    text-decoration: none;
                    white-space: nowrap;
                    overflow: hidden;
                    text-overflow: ellipsis;
                    margin-top: 10px;
                    padding: 6px 10px;
                    background: rgba(0, 243, 255, 0.05);
                    border-radius: 6px;
                    border: 1px dashed rgba(0, 243, 255, 0.2);
                }}
                .tunnel-link:hover {{ text-decoration: underline; }}
                
                .upload-container {{
                    background: var(--card-bg);
                    border: 1px solid var(--border);
                    border-radius: 12px;
                    padding: 24px;
                }}
                .upload-form {{ display: grid; gap: 14px; margin-top: 14px; }}
                .form-control {{
                    width: 100%;
                    padding: 10px 14px;
                    background: var(--bg-dark);
                    border: 1px solid var(--border);
                    border-radius: 8px;
                    color: #fff;
                    font-size: 13px;
                    font-family: inherit;
                }}
                .form-control:focus {{ outline: none; border-color: var(--cyan); }}
                .btn-submit {{
                    background: linear-gradient(135deg, #00f3ff, #0088ff);
                    color: #000;
                    border: none;
                    border-radius: 8px;
                    padding: 12px;
                    font-weight: 700;
                    cursor: pointer;
                    font-size: 13px;
                    font-family: inherit;
                    transition: opacity 0.2s;
                }}
                .btn-submit:hover {{ opacity: 0.9; }}
                #result {{
                    margin-top: 14px;
                    font-family: 'JetBrains Mono', monospace;
                    font-size: 12px;
                    word-break: break-all;
                }}
            </style>
        </head>
        <body>
            <div class="top-bar">
                <div class="brand-title">
                    ⚡ Netuark <span style="color:var(--cyan)">Media Cluster</span>
                    <span class="brand-badge">HA v2.2 Sovereign</span>
                </div>
                <div style="display:flex; gap:10px; align-items:center;">
                    <a href="/docs" class="docs-btn">📁 Media Docs</a>
                    <a href="https://ntawebsearch.pages.dev/docs" target="_blank" class="docs-btn" style="background:linear-gradient(135deg, #00f3ff, #0077ff); color:#000;">🔍 Search Docs</a>
                </div>
            </div>

            <div class="summary-banner">
                <div class="summary-item">
                    <span class="summary-label">Cluster Status</span>
                    <span class="summary-value" id="cluster-status-text">
                        <span class="pulse-dot"></span> Active Sovereign Mesh
                    </span>
                </div>
                <div class="summary-item">
                    <span class="summary-label">Media Edge Gateway</span>
                    <span class="summary-value" style="font-family:'JetBrains Mono', monospace; font-size:13px; color:var(--cyan);">
                        https://ntamediaserver.pages.dev
                    </span>
                </div>
                <div class="summary-item">
                    <span class="summary-label">WebSearch API Gateway</span>
                    <span class="summary-value" style="font-family:'JetBrains Mono', monospace; font-size:13px; color:var(--emerald);">
                        https://ntawebsearch.pages.dev
                    </span>
                </div>
                <div class="summary-item">
                    <span class="summary-label">Network Health</span>
                    <span class="summary-value" id="network-health-text" style="font-family:'JetBrains Mono', monospace; font-size:13px;">
                        <span style="color:var(--emerald)">● Online (Pinging Active)</span>
                    </span>
                </div>
            </div>

            <div class="section-header">
                <div class="section-title">Hardware Telemetry & Node Cluster</div>
                <div class="sync-timer" id="sync-timer">Auto-refresh: 3s</div>
            </div>

            <div class="dashboard-grid" id="telemetry-dashboard">
                <div class="node-card">
                    <p style="color:var(--text-sub); font-size:13px;">Polling hardware vitals and mesh nodes...</p>
                </div>
            </div>

            <div class="search-hub-container" style="background:var(--card-bg); border:1px solid var(--border); border-radius:12px; padding:24px; margin-bottom:28px;">
                <div class="section-header" style="margin-bottom:8px;">
                    <div>
                        <div class="section-title" style="display:flex; align-items:center; gap:8px;">
                            <span>⚡ Sovereign WebSearch Engine & Chromium Sandbox</span>
                            <span class="badge" id="search-status-badge" style="background:rgba(245,158,11,0.15); color:var(--amber); border:1px solid rgba(245,158,11,0.3);">CONNECTING...</span>
                        </div>
                        <p style="color:var(--text-sub); font-size:12px; margin-top:4px;">
                            100% SerpAPI drop-in schema parity hosted natively on this Lenovo phone (Port 3001 & CDP 9222).
                        </p>
                    </div>
                    <div style="font-family:'JetBrains Mono', monospace; font-size:11px; color:var(--text-sub);">
                        Port: <span style="color:var(--cyan)">3001</span> &bull; CDP: <span style="color:var(--purple)">9222</span>
                    </div>
                </div>

                <!-- Two-column grid -->
                <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap:20px; margin-top:16px;">
                    
                    <!-- Left Column: Key Generator & Active Keys -->
                    <div style="background:rgba(255,255,255,0.02); border:1px solid rgba(255,255,255,0.06); border-radius:10px; padding:18px;">
                        <div style="font-weight:700; font-size:14px; color:#fff; margin-bottom:4px; display:flex; justify-content:space-between; align-items:center;">
                            <span>🔑 Sovereign API Key Creator</span>
                            <span style="font-family:'JetBrains Mono',monospace; font-size:10px; color:var(--text-sub);">SHA-256 Hashed</span>
                        </div>
                        <p style="font-size:11px; color:var(--text-sub); margin-bottom:12px;">
                            Generate sovereign API keys for NeTuArk Chat AI and Mobile Clients. Keys are revealed <strong>once</strong> and stored hashed on-device.
                        </p>
                        
                        <form id="createKeyForm" style="display:flex; gap:8px;">
                            <input type="text" id="keyClientName" placeholder="Client Name (e.g. NeTuArk-Chat-AI)" class="form-control" style="font-size:12px; padding:8px 12px;" required />
                            <button type="submit" class="btn-submit" style="padding:8px 14px; white-space:nowrap; font-size:12px; background:linear-gradient(135deg, #10b981, #059669); color:#fff;">+ Create Key</button>
                        </form>

                        <div id="newKeyAlert" style="display:none; margin-top:12px; padding:12px; background:rgba(16,185,129,0.1); border:1px solid rgba(16,185,129,0.4); border-radius:8px;">
                            <div style="color:var(--emerald); font-weight:700; font-size:11px; margin-bottom:4px;">✅ NEW API KEY GENERATED (ONE-TIME REVEAL):</div>
                            <div style="display:flex; gap:8px; align-items:center;">
                                <input type="text" id="revealedKeyInput" readonly class="form-control" style="font-family:'JetBrains Mono', monospace; font-size:11px; padding:6px 10px; background:#000; color:var(--cyan); border-color:var(--emerald);" />
                                <button type="button" onclick="copyRevealedKey()" class="docs-btn" style="padding:6px 12px; font-size:11px; cursor:pointer;">Copy</button>
                            </div>
                            <div style="color:var(--amber); font-size:10px; margin-top:6px; line-height:1.4;">
                                ⚠️ Copy this key now! It is stored as a SHA-256 hash on your device and cannot be retrieved again.
                            </div>
                        </div>

                        <div style="margin-top:16px;">
                            <div style="font-size:12px; font-weight:600; color:var(--text-sub); margin-bottom:8px; display:flex; justify-content:space-between;">
                                <span>Active Hardware Keys</span>
                                <span id="keysCountBadge" style="font-family:'JetBrains Mono', monospace; font-size:10px; color:var(--cyan);">0 keys</span>
                            </div>
                            <div id="activeKeysList" style="max-height:160px; overflow-y:auto; display:flex; flex-direction:column; gap:6px;">
                                <div style="font-size:11px; color:var(--text-sub); font-style:italic;">Loading keys...</div>
                            </div>
                        </div>
                    </div>

                    <!-- Right Column: Interactive Live Search Tester -->
                    <div style="background:rgba(255,255,255,0.02); border:1px solid rgba(255,255,255,0.06); border-radius:10px; padding:18px;">
                        <div style="font-weight:700; font-size:14px; color:#fff; margin-bottom:4px; display:flex; justify-content:space-between; align-items:center;">
                            <span>🔎 Interactive Search Console</span>
                            <span style="font-family:'JetBrains Mono', monospace; font-size:10px; color:var(--emerald);">SerpAPI Drop-in</span>
                        </div>
                        <p style="font-size:11px; color:var(--text-sub); margin-bottom:12px;">
                            Execute queries directly through the phone's Chromium CDP browser sandbox.
                        </p>

                        <form id="searchTestForm" style="display:flex; flex-direction:column; gap:8px;">
                            <div style="display:flex; gap:8px;">
                                <input type="text" id="testSearchQuery" placeholder="Enter query (e.g. quantum computing 2026)" class="form-control" style="font-size:12px; padding:8px 12px;" required />
                                <select id="testSearchEngine" class="form-control" style="width:140px; font-size:11px; padding:8px;">
                                    <option value="google">Google Web</option>
                                    <option value="google_images">Google Images</option>
                                    <option value="multi">Fast Multi-Engine</option>
                                </select>
                            </div>
                            <div style="display:flex; gap:8px;">
                                <input type="text" id="testApiKey" placeholder="API Key (optional if no keys created yet)" class="form-control" style="font-size:11px; padding:6px 10px; font-family:'JetBrains Mono', monospace;" />
                                <button type="submit" id="searchSubmitBtn" class="btn-submit" style="padding:6px 16px; white-space:nowrap; font-size:12px; background:linear-gradient(135deg, #00f3ff, #0088ff); color:#000;">🚀 Run Search</button>
                            </div>
                        </form>

                        <div id="searchTestResults" style="display:none; margin-top:12px; max-height:220px; overflow-y:auto; background:var(--bg-dark); border:1px solid var(--border); border-radius:8px; padding:10px; font-family:'JetBrains Mono', monospace; font-size:11px; color:#e2e8f0; white-space:pre-wrap; word-break:break-word;">
                        </div>
                    </div>

                </div>
            </div>

            <div class="upload-container">
                <div class="section-title">Ingestion Test Console</div>
                <p style="color:var(--text-sub); font-size:12px; margin-top:2px;">
                    Uploaded assets stream directly to hardware flash storage with zero memory accumulation.
                </p>
                <form id="uploadForm" class="upload-form">
                    <div>
                        <label style="display:block; font-size:11px; font-family:'JetBrains Mono', monospace; color:var(--text-sub); margin-bottom:6px;">Target Storage Category</label>
                        <select name="type" class="form-control">
                            <option value="chat">Chat (Images, Audio, Voice notes)</option>
                            <option value="videos">Videos (Streaming, MP4, WebM)</option>
                            <option value="docs">Docs (PDF, Archives, Text)</option>
                            <option value="feed">Feed (Banners, Posts, Stickers)</option>
                            <option value="avatars">Avatars (User Profiles)</option>
                            <option value="stickers">Stickers (Packs, WebP)</option>
                        </select>
                    </div>
                    <div>
                        <label style="display:block; font-size:11px; font-family:'JetBrains Mono', monospace; color:var(--text-sub); margin-bottom:6px;">Choose File</label>
                        <input type="file" name="file" class="form-control" required />
                    </div>
                    <button type="submit" class="btn-submit">Upload to Sovereign CDN</button>
                </form>
                <div id="result"></div>
            </div>

            <script>
                const SYNC_URL = "{SYNC_URL}";
                const PHONE_NODE_URL = "https://phone-whisper-server.pages.dev/telemetry";

                function formatAgo(timestampStr) {{
                    if (!timestampStr) return "Never";
                    const diff = Math.floor((Date.now() - new Date(timestampStr).getTime()) / 1000);
                    if (diff < 5) return "Just now";
                    if (diff < 60) return diff + "s ago";
                    if (diff < 3600) return Math.floor(diff / 60) + "m ago";
                    return Math.floor(diff / 3600) + "h ago";
                }}

                function getBarColor(pct) {{
                    if (pct > 85) return 'rose';
                    if (pct > 70) return 'amber';
                    return 'green';
                }}

                async function fetchAllTelemetry() {{
                    const dashboardEl = document.getElementById('telemetry-dashboard');
                    let cardsHtml = '';

                    // ── 1. Fetch THIS Local Sovereign Node (/api/telemetry) ──
                    try {{
                        const localRes = await fetch('/api/telemetry', {{ signal: AbortSignal.timeout(3000) }});
                        if (localRes.ok) {{
                            const d = await localRes.json();
                            const ramPct = Math.round(d.memory?.used_percent || 0);
                            const storPct = Math.round(d.storage?.used_percent || 0);
                            const cpuPct = Math.round(d.cpu?.usage_percent || 0);
                            const batLvl = d.battery?.level || 100;
                            const batTemp = d.battery?.temperature_c || 32;
                            const batStatus = d.battery?.status || 'Active';
                            const cpuTemp = d.cpu?.temperature_c || 35;
                            const cores = d.cpu?.cores || 8;

                            let folderChipsHtml = '';
                            if (d.storage?.folders) {{
                                for (const [fName, fData] of Object.entries(d.storage.folders)) {{
                                    if (fData.count > 0) {{
                                        folderChipsHtml += `<div class="folder-chip">${{fName}}: <span>${{fData.size_mb}}MB</span> (${{fData.count}})</div>`;
                                    }}
                                }}
                            }}

                            const tunnelUrl = d.network?.active_tunnel || window.location.origin;

                            cardsHtml += `
                            <div class="node-card master">
                                <div class="card-header">
                                    <div>
                                        <div class="node-title">${{d.device?.model || 'Lenovo L38012'}} (Local Sovereign Node)</div>
                                        <div class="node-sub">${{d.device?.arch || 'ARM64 Cortex-A53'}} &bull; 4GB RAM Dedicated Media Host</div>
                                    </div>
                                    <span class="badge active">● ACTIVE HOST</span>
                                </div>
                                <div class="metric-row">
                                    <span class="metric-label">🔋 Battery Vitals</span>
                                    <span class="metric-val">${{batLvl}}% (${{batStatus}}, ${{batTemp}}°C${{d.battery?.voltage_mv ? ', ' + (d.battery.voltage_mv/1000).toFixed(2) + 'V' : ''}})</span>
                                </div>
                                <div class="bar-container"><div class="bar-fill ${{getBarColor(100 - batLvl)}}" style="width:${{batLvl}}%"></div></div>
                                
                                <div class="metric-row" style="margin-top:6px;">
                                    <span class="metric-label">⚡ CPU Workload</span>
                                    <span class="metric-val">${{cpuPct}}% (${{cores}} Cores, ${{cpuTemp}}°C)</span>
                                </div>
                                <div class="bar-container"><div class="bar-fill ${{getBarColor(cpuPct)}}" style="width:${{Math.max(cpuPct, 5)}}%"></div></div>
                                
                                <div class="metric-row" style="margin-top:6px;">
                                    <span class="metric-label">🧠 RAM Allocation</span>
                                    <span class="metric-val">${{d.memory?.used_mb || 0}} / ${{d.memory?.total_mb || 0}} MB (${{ramPct}}%)</span>
                                </div>
                                <div class="bar-container"><div class="bar-fill ${{getBarColor(ramPct)}}" style="width:${{ramPct}}%"></div></div>
                                
                                <div class="metric-row" style="margin-top:6px;">
                                    <span class="metric-label">💾 Flash Storage</span>
                                    <span class="metric-val">${{d.storage?.used_gb || 0}} / ${{d.storage?.total_gb || 0}} GB (${{storPct}}% Used, ${{d.storage?.free_gb || 0}}GB Free)</span>
                                </div>
                                <div class="bar-container"><div class="bar-fill ${{getBarColor(storPct)}}" style="width:${{storPct}}%"></div></div>
                                
                                ${{folderChipsHtml ? `<div class="folder-chips">${{folderChipsHtml}}</div>` : ''}}
                                
                                <a href="${{tunnelUrl}}" target="_blank" class="tunnel-link">
                                    🌐 ${{tunnelUrl}}
                                </a>
                            </div>`;
                        }}
                    }} catch (err) {{
                        console.warn('Local telemetry error:', err);
                    }}

                    // ── 2. Fetch Peer Node (Redmi 9i Sovereign Micro-Datacenter) ──
                    try {{
                        const phoneRes = await fetch(PHONE_NODE_URL, {{ signal: AbortSignal.timeout(3000) }});
                        if (phoneRes.ok) {{
                            const p = await phoneRes.json();
                            const ramPct = Math.round((p.memory?.used_mb / (p.memory?.total_mb || 1)) * 100);
                            const storUsed = (p.storage?.total_gb - p.storage?.free_gb).toFixed(1);
                            const storPct = Math.round((storUsed / (p.storage?.total_gb || 1)) * 100);

                            cardsHtml += `
                            <div class="node-card phone">
                                <div class="card-header">
                                    <div>
                                        <div class="node-title">${{p.device?.model || 'Redmi 9i'}} (Cluster Peer Node)</div>
                                        <div class="node-sub">${{p.device?.arch || 'ARM64 Cortex-A53'}} &bull; Secondary Mesh Replica</div>
                                    </div>
                                    <span class="badge active">● ONLINE PEER</span>
                                </div>
                                <div class="metric-row">
                                    <span class="metric-label">🔋 Battery Vitals</span>
                                    <span class="metric-val">${{p.battery?.level || 0}}% (${{p.battery?.status || 'Active'}}, ${{p.battery?.temperature || 32}}°C)</span>
                                </div>
                                <div class="metric-row">
                                    <span class="metric-label">⚡ CPU Workload</span>
                                    <span class="metric-val">${{p.cpu?.usage_percent || 0}}% (${{p.cpu?.cores || 8}} Cores)</span>
                                </div>
                                <div class="metric-row">
                                    <span class="metric-label">🧠 RAM Allocation</span>
                                    <span class="metric-val">${{p.memory?.used_mb || 0}} / ${{p.memory?.total_mb || 0}} MB (${{ramPct}}%)</span>
                                </div>
                                <div class="bar-container"><div class="bar-fill ${{getBarColor(ramPct)}}" style="width:${{ramPct}}%"></div></div>
                                <div class="metric-row" style="margin-top:6px;">
                                    <span class="metric-label">💾 Flash Storage</span>
                                    <span class="metric-val">${{storUsed}} / ${{p.storage?.total_gb || 0}} GB (${{storPct}}%)</span>
                                </div>
                                <div class="bar-container"><div class="bar-fill ${{getBarColor(storPct)}}" style="width:${{storPct}}%"></div></div>
                                <a href="https://phone-whisper-server.pages.dev" target="_blank" class="tunnel-link">
                                    🌐 https://phone-whisper-server.pages.dev
                                </a>
                            </div>`;
                        }}
                    }} catch (err) {{
                        console.warn('Peer node telemetry offline:', err);
                    }}

                    if (cardsHtml) {{
                        dashboardEl.innerHTML = cardsHtml;
                    }}
                }}

                fetchAllTelemetry();
                setInterval(fetchAllTelemetry, 3000);

                // Upload test handler
                document.getElementById('uploadForm').addEventListener('submit', async (e) => {{
                    e.preventDefault();
                    const formData = new FormData(e.target);
                    const resultDiv = document.getElementById('result');
                    resultDiv.innerHTML = '<span style="color:var(--cyan)">Transferring streamed payload to sovereign media cluster...</span>';
                    try {{
                        const res = await fetch('/upload', {{ method: 'POST', body: formData }});
                        const data = await res.json();
                        if (res.ok) {{
                            const fullUrl = window.location.origin + data.fileUrl;
                            resultDiv.innerHTML = '<span style="color:var(--emerald)">✅ Upload Succeeded!</span><br>Live Stream URL: <a href="' + data.fileUrl + '" target="_blank" style="color:var(--cyan);text-decoration:underline;">' + fullUrl + '</a>';
                            // Immediately refresh telemetry to show disk usage increase
                            setTimeout(fetchAllTelemetry, 500);
                        }} else {{
                            resultDiv.innerHTML = '<span style="color:var(--rose)">❌ Upload Failed: ' + (data.error || 'Server error') + '</span>';
                        }}
                    }} catch (err) {{
                        resultDiv.innerHTML = '<span style="color:var(--rose)">❌ Network Error: ' + err.message + '</span>';
                    }}
                }});

                // ── WebSearch API Integration & Management ──
                async function pollSearchStatus() {{
                    const badge = document.getElementById('search-status-badge');
                    try {{
                        const res = await fetch('/api/search_service/status', {{ signal: AbortSignal.timeout(2500) }});
                        if (res.ok) {{
                            const d = await res.json();
                            if (d.status === 'online') {{
                                const cdpActive = d.chromium_cdp && d.chromium_cdp.status === 'active';
                                badge.className = 'badge active';
                                badge.innerHTML = cdpActive ? '● ONLINE (CHROMIUM CDP)' : '● ONLINE (PORT 3001)';
                                badge.style.background = 'rgba(16,185,129,0.15)';
                                badge.style.color = 'var(--emerald)';
                                badge.style.borderColor = 'rgba(16,185,129,0.3)';
                            }} else {{
                                badge.className = 'badge offline';
                                badge.innerHTML = '● SEARCH SERVER STANDBY';
                                badge.style.background = 'rgba(244,63,94,0.15)';
                                badge.style.color = 'var(--rose)';
                                badge.style.borderColor = 'rgba(244,63,94,0.3)';
                            }}
                        }}
                    }} catch (e) {{
                        badge.className = 'badge offline';
                        badge.innerHTML = '● SEARCH OFFLINE';
                        badge.style.background = 'rgba(244,63,94,0.15)';
                        badge.style.color = 'var(--rose)';
                    }}
                }}

                async function fetchActiveKeys() {{
                    const keysListEl = document.getElementById('activeKeysList');
                    const countBadge = document.getElementById('keysCountBadge');
                    try {{
                        const res = await fetch('/api/search_service/keys', {{ signal: AbortSignal.timeout(2500) }});
                        if (res.ok) {{
                            const d = await res.json();
                            const keys = d.keys || [];
                            countBadge.textContent = keys.length + (keys.length === 1 ? ' key' : ' keys');
                            if (keys.length === 0) {{
                                keysListEl.innerHTML = '<div style="font-size:11px; color:var(--text-sub); font-style:italic;">No keys generated yet. (API open or create one above)</div>';
                                return;
                            }}
                            let html = '';
                            keys.forEach(k => {{
                                const createdDate = k.created_at ? k.created_at.split('T')[0] : '';
                                html += `
                                <div style="display:flex; justify-content:space-between; align-items:center; background:rgba(0,0,0,0.3); border:1px solid rgba(255,255,255,0.05); border-radius:6px; padding:6px 10px; font-size:11px;">
                                    <div style="overflow:hidden; text-overflow:ellipsis; white-space:nowrap; margin-right:8px;">
                                        <div style="font-weight:600; color:#fff;">${{k.name || 'Client'}}</div>
                                        <div style="font-family:'JetBrains Mono',monospace; color:var(--cyan); font-size:10px;">${{k.masked_key}} &bull; <span style="color:var(--text-sub);">${{k.requests_total || 0}} reqs</span></div>
                                    </div>
                                    <button onclick="revokeKey('${{k.key_id}}')" style="background:rgba(244,63,94,0.2); color:var(--rose); border:1px solid rgba(244,63,94,0.3); border-radius:4px; padding:3px 8px; font-size:10px; cursor:pointer;">Revoke</button>
                                </div>`;
                            }});
                            keysListEl.innerHTML = html;
                        }}
                    }} catch (e) {{
                        keysListEl.innerHTML = '<div style="font-size:11px; color:var(--rose);">Could not load keys (Search server offline)</div>';
                    }}
                }}

                window.revokeKey = async function(keyId) {{
                    if (!confirm('Are you sure you want to revoke this sovereign API key?')) return;
                    try {{
                        const res = await fetch('/api/search_service/revoke_key', {{
                            method: 'POST',
                            headers: {{ 'Content-Type': 'application/json' }},
                            body: JSON.stringify({{ key_id: keyId }})
                        }});
                        if (res.ok) {{
                            fetchActiveKeys();
                        }} else {{
                            alert('Failed to revoke key');
                        }}
                    }} catch (e) {{
                        alert('Network error: ' + e.message);
                    }}
                }};

                function copyRevealedKey() {{
                    const input = document.getElementById('revealedKeyInput');
                    input.select();
                    navigator.clipboard.writeText(input.value).then(() => {{
                        alert('API Key copied to clipboard! Keep it safe.');
                    }}).catch(() => {{
                        document.execCommand('copy');
                        alert('API Key copied!');
                    }});
                }}

                // Create Key Form Handler
                document.getElementById('createKeyForm').addEventListener('submit', async (e) => {{
                    e.preventDefault();
                    const name = document.getElementById('keyClientName').value.trim();
                    if (!name) return;
                    const alertBox = document.getElementById('newKeyAlert');
                    const keyInput = document.getElementById('revealedKeyInput');
                    
                    try {{
                        const res = await fetch('/api/search_service/create_key', {{
                            method: 'POST',
                            headers: {{ 'Content-Type': 'application/json' }},
                            body: JSON.stringify({{ name: name }})
                        }});
                        const data = await res.json();
                        if (res.ok && data.api_key) {{
                            keyInput.value = data.api_key;
                            alertBox.style.display = 'block';
                            document.getElementById('testApiKey').value = data.api_key;
                            document.getElementById('keyClientName').value = '';
                            fetchActiveKeys();
                        }} else {{
                            alert('Error creating key: ' + (data.error || 'Server error'));
                        }}
                    }} catch (err) {{
                        alert('Network error: ' + err.message);
                    }}
                }});

                // Interactive Live Search Console Handler
                document.getElementById('searchTestForm').addEventListener('submit', async (e) => {{
                    e.preventDefault();
                    const query = document.getElementById('testSearchQuery').value.trim();
                    const engine = document.getElementById('testSearchEngine').value;
                    const apiKey = document.getElementById('testApiKey').value.trim();
                    const resultsBox = document.getElementById('searchTestResults');
                    const submitBtn = document.getElementById('searchSubmitBtn');

                    resultsBox.style.display = 'block';
                    resultsBox.innerHTML = '<span style="color:var(--cyan)">⚡ Dispatching query to phone Chromium CDP sandbox...</span>';
                    submitBtn.disabled = true;
                    submitBtn.style.opacity = '0.6';

                    try {{
                        const res = await fetch('/api/search_service/test_search', {{
                            method: 'POST',
                            headers: {{ 'Content-Type': 'application/json' }},
                            body: JSON.stringify({{ query: query, engine: engine, api_key: apiKey }})
                        }});
                        const data = await res.json();
                        if (res.ok) {{
                            const organic = data.organic_results || [];
                            const images = data.images_results || [];
                            let summary = `<span style="color:var(--emerald)">✅ Query Succeeded! Engine: ${{data.search_metadata?.engine || engine}} (${{organic.length}} results)</span>\\n\\n`;
                            
                            if (organic.length > 0) {{
                                organic.forEach((r, idx) => {{
                                    summary += `<span style="color:var(--cyan);">[${{idx+1}}] ${{r.title}}</span>\\n`;
                                    summary += `<span style="color:var(--text-sub); font-size:10px;">${{r.link}}</span>\\n`;
                                    summary += `${{r.snippet || ''}}\\n\\n`;
                                }});
                            }} else if (images.length > 0) {{
                                summary += `<span style="color:var(--emerald);">Found ${{images.length}} images. First 3:</span>\\n`;
                                images.slice(0, 3).forEach((img, idx) => {{
                                    summary += `[${{idx+1}}] ${{img.title}}\\n${{img.original}}\\n\\n`;
                                }});
                            }} else {{
                                summary += JSON.stringify(data, null, 2);
                            }}
                            resultsBox.innerHTML = summary;
                        }} else {{
                            resultsBox.innerHTML = `<span style="color:var(--rose)">❌ Search Error (${{res.status}}): ${{data.error || JSON.stringify(data)}}</span>`;
                        }}
                    }} catch (err) {{
                        resultsBox.innerHTML = `<span style="color:var(--rose)">❌ Execution Failure: ${{err.message}}</span>`;
                    }} finally {{
                        submitBtn.disabled = false;
                        submitBtn.style.opacity = '1';
                    }}
                }});

                pollSearchStatus();
                fetchActiveKeys();
                setInterval(pollSearchStatus, 5000);
            </script>
        </body>
    </html>
    """

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    file = request.files['file']
    if not file or file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    
    upload_type = request.form.get('type') or request.form.get('folder') or 'chat'
    target_dir = get_folder_path(upload_type)
        
    filename = secure_filename(file.filename)
    unique_name = f"{int(time.time())}_{filename}"
    file_path = os.path.join(target_dir, unique_name)
    temp_path = file_path + ".tmp"
    
    # Save directly in chunks to avoid blowing up RAM
    try:
        with open(temp_path, 'wb') as f:
            file.save(f)
        os.replace(temp_path, file_path)
    except Exception as e:
        if os.path.exists(temp_path):
            try: os.remove(temp_path)
            except Exception: pass
        return jsonify({'error': f'Failed to write file: {str(e)}'}), 500
    
    gc.collect()
    
    file_url = f"/media/{upload_type}/{unique_name}"
    return jsonify({
        'message': 'File uploaded successfully',
        'fileUrl': file_url
    })

def fallback_and_serve(target_dir, folder, filename):
    file_path = os.path.join(target_dir, filename)
    if os.path.exists(file_path):
        return send_from_directory(target_dir, filename)
        
    # Check all other subdirectories inside BASE_DIR
    if os.path.exists(BASE_DIR):
        try:
            for entry in os.scandir(BASE_DIR):
                if entry.is_dir() and entry.path != target_dir:
                    candidate = os.path.join(entry.path, filename)
                    if os.path.exists(candidate):
                        return send_from_directory(entry.path, filename)
        except Exception:
            pass
            
    # Check negative cache before performing expensive network lookups
    cache_key = f"{folder}/{filename}"
    if is_negative_cached(cache_key):
        return send_from_directory(target_dir, filename) # will return 404

    # P2P Fallback to Counterpart Node (Redmi 9i Sovereign Micro-Datacenter)
    try:
        device_id = ""
        if os.path.exists('.device_id'):
            with open('.device_id', 'r') as f:
                device_id = f.read().strip()
                
        peer_urls = ["https://phone-whisper-server.pages.dev"]
        try:
            req = urllib.request.Request(SYNC_URL)
            with urllib.request.urlopen(req, timeout=2.5) as response:
                data = json.loads(response.read().decode())
                for key, value in data.get('fields', {}).items():
                    if key.startswith('peer_url_') and key != f'peer_url_{device_id}':
                        p_val = value.get('stringValue')
                        if p_val and p_val.startswith('https://') and p_val not in peer_urls:
                            peer_urls.append(p_val.rstrip('/'))
        except Exception:
            pass
                
        candidate_paths = [
            f"/v1/storage/objects/{folder}/{filename}",
            f"/media/{folder}/{filename}",
            f"/v1/storage/objects/media/{filename}"
        ]

        for peer in peer_urls:
            for c_path in candidate_paths:
                try:
                    peer_file_url = f"{peer}{c_path}"
                    dl_req = urllib.request.Request(peer_file_url, headers={"User-Agent": "NTA-MediaServer/MeshSync"})
                    with urllib.request.urlopen(dl_req, timeout=3) as dl_res:
                        if dl_res.status == 200:
                            os.makedirs(target_dir, exist_ok=True)
                            tmp_file = file_path + ".tmp"
                            with open(tmp_file, 'wb') as out_f:
                                shutil.copyfileobj(dl_res, out_f, length=65536)
                            os.replace(tmp_file, file_path)
                            print(f"[+] Downloaded {filename} from peer {peer} ({c_path})")
                            return send_from_directory(target_dir, filename)
                except Exception:
                    continue
    except Exception as e:
        print(f"P2P fallback warning: {e}")
        
    set_negative_cache(cache_key)
    return send_from_directory(target_dir, filename)

@app.route('/media/<folder>/<filename>')
def serve_media(folder, filename):
    target_dir = get_folder_path(folder)
    return fallback_and_serve(target_dir, folder, filename)

@app.route('/v1/storage/objects/<folder>/<filename>', methods=['PUT', 'OPTIONS'])
def rest_upload(folder, filename):
    if request.method == 'OPTIONS':
        return '', 204
        
    target_dir = get_folder_path(folder)
    filename = secure_filename(filename)
    file_path = os.path.join(target_dir, filename)
    temp_path = file_path + ".tmp"
    
    # Stream body directly to disk in 64KB chunks — zero memory accumulation!
    try:
        with open(temp_path, 'wb') as f:
            while True:
                chunk = request.stream.read(65536)
                if not chunk:
                    break
                f.write(chunk)
        os.replace(temp_path, file_path)
    except Exception as e:
        if os.path.exists(temp_path):
            try: os.remove(temp_path)
            except Exception: pass
        return jsonify({"error": f"Upload write failed: {str(e)}"}), 500
        
    gc.collect()
    return jsonify({"success": True, "url": f"/v1/storage/objects/{folder}/{filename}"}), 200

@app.route('/v1/storage/objects/<folder>/<filename>', methods=['GET', 'OPTIONS'])
def rest_serve(folder, filename):
    target_dir = get_folder_path(folder)
    return fallback_and_serve(target_dir, folder, filename)

def propagate_delete(folder, filename, path_prefix):
    if request.args.get('propagate', 'true') != 'true':
        return
    try:
        device_id = ""
        if os.path.exists('.device_id'):
            with open('.device_id', 'r') as f:
                device_id = f.read().strip()
                
        req = urllib.request.Request(SYNC_URL)
        with urllib.request.urlopen(req, timeout=3) as response:
            data = json.loads(response.read().decode())
            
        peer_urls = []
        for key, value in data.get('fields', {}).items():
            if key.startswith('peer_url_') and key != f'peer_url_{device_id}':
                peer_urls.append(value.get('stringValue'))
                
        for peer in peer_urls:
            try:
                peer_file_url = f"{peer}{path_prefix}/{folder}/{filename}?propagate=false"
                dl_req = urllib.request.Request(peer_file_url, method='DELETE')
                urllib.request.urlopen(dl_req, timeout=3)
            except Exception:
                pass
    except Exception:
        pass

@app.route('/media/<folder>/<filename>', methods=['DELETE'])
def delete_media(folder, filename):
    target_dir = get_folder_path(folder)
    filename = secure_filename(filename)
    file_path = os.path.join(target_dir, filename)
    
    deleted = False
    if os.path.exists(file_path):
        try:
            os.remove(file_path)
            deleted = True
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    propagate_delete(folder, filename, "/media")

    if deleted:
        return jsonify({'message': 'File deleted successfully'}), 200
    else:
        return jsonify({'message': 'File not found locally, but delete broadcasted'}), 404

@app.route('/v1/storage/objects/<folder>/<filename>', methods=['DELETE', 'OPTIONS'])
def rest_delete(folder, filename):
    if request.method == 'OPTIONS':
        return '', 204
        
    target_dir = get_folder_path(folder)
    filename = secure_filename(filename)
    file_path = os.path.join(target_dir, filename)
    
    deleted = False
    if os.path.exists(file_path):
        try:
            os.remove(file_path)
            deleted = True
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    propagate_delete(folder, filename, "/v1/storage/objects")

    if deleted:
        return jsonify({'success': True, 'message': 'File deleted successfully'}), 200
    else:
        return jsonify({'success': True, 'message': 'File not found locally, but delete broadcasted'}), 404

@app.route('/api/sync/list')
def sync_list():
    files_info = {}
    if os.path.exists(BASE_DIR):
        try:
            for entry in os.scandir(BASE_DIR):
                if entry.is_dir():
                    folder_name = entry.name
                    files_info[folder_name] = {}
                    for f in os.scandir(entry.path):
                        if f.is_file():
                            files_info[folder_name][f.name] = f.stat().st_size
        except Exception as e:
            print(f"Sync list scan warning: {e}")
    return jsonify(files_info)

# ==============================================================================
# 🛰️ AUTONOMOUS INTERNAL COMMUNICATOR & REMOTE MANAGEMENT RPC
# ==============================================================================
INTERNAL_SECRETS = {"ntamedia_tunnel_key", "mobile_ai_nuclear_key", "nta_sovereign_internal_comm_2026"}

def check_internal_auth():
    auth_header = request.headers.get("X-Internal-Secret") or request.headers.get("Authorization", "")
    token = auth_header.replace("Bearer ", "").strip() if auth_header else ""
    if not token:
        token = request.args.get("secret", "").strip()
    return token in INTERNAL_SECRETS

@app.route('/api/internal/status', methods=['GET'])
def internal_status():
    if not check_internal_auth():
        return jsonify({"error": "Unauthorized", "message": "Invalid or missing X-Internal-Secret"}), 401
    
    repo_dir = os.path.dirname(os.path.abspath(__file__))
    git_sha = "unknown"
    git_branch = "main"
    if shutil.which("git"):
        try:
            git_sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=repo_dir, capture_output=True, text=True, timeout=2).stdout.strip()
            git_branch = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_dir, capture_output=True, text=True, timeout=2).stdout.strip()
        except Exception:
            pass
    
    stor = telemetry.get_storage_info()
    device_id = ""
    if os.path.exists('.device_id'):
        try:
            with open('.device_id', 'r') as f:
                device_id = f.read().strip()
        except Exception:
            pass
            
    return jsonify({
        "status": "ONLINE",
        "node": "ntamediaserver",
        "device_id": device_id,
        "git_commit": git_sha,
        "git_branch": git_branch,
        "free_gb": stor.get("free_gb", 0.0),
        "total_gb": stor.get("total_gb", 0.0),
        "timestamp": time.time(),
        "storage_root": BASE_DIR
    }), 200

@app.route('/api/internal/exec', methods=['POST'])
def internal_exec():
    if not check_internal_auth():
        return jsonify({"error": "Unauthorized"}), 401
    
    data = request.get_json(force=True, silent=True) or {}
    cmd = data.get("cmd")
    if not cmd:
        return jsonify({"error": "Missing cmd parameter"}), 400
    
    repo_dir = os.path.dirname(os.path.abspath(__file__))
    try:
        res = subprocess.run(cmd, shell=True, cwd=repo_dir, capture_output=True, text=True, timeout=30)
        return jsonify({
            "returncode": res.returncode,
            "stdout": res.stdout,
            "stderr": res.stderr
        }), 200
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Command timed out after 30 seconds"}), 408
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/internal/update', methods=['POST'])
def internal_update():
    if not check_internal_auth():
        return jsonify({"error": "Unauthorized"}), 401
    
    repo_dir = os.path.dirname(os.path.abspath(__file__))
    if not shutil.which("git"):
        return jsonify({"error": "Git not installed on device"}), 400

    try:
        pull_res = subprocess.run(["git", "pull", "--rebase", "origin", "main"], cwd=repo_dir, capture_output=True, text=True, timeout=35)
        def restart_worker():
            time.sleep(1.5)
            subprocess.run(["pkill", "-f", "server.py"])
            time.sleep(1)
            subprocess.Popen([sys.executable, os.path.join(repo_dir, "server.py")], cwd=repo_dir)
        import threading
        threading.Thread(target=restart_worker, daemon=True).start()
        
        return jsonify({
            "success": pull_res.returncode == 0,
            "stdout": pull_res.stdout,
            "stderr": pull_res.stderr,
            "message": "Update pulled. Server restarting in 1.5s."
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/internal/logs', methods=['GET'])
def internal_logs():
    if not check_internal_auth():
        return jsonify({"error": "Unauthorized"}), 401
    
    log_type = request.args.get("type", "server")
    repo_dir = os.path.dirname(os.path.abspath(__file__))
    log_file = os.path.join(repo_dir, "server.log" if log_type == "server" else "tunnel.log")
    
    lines_count = int(request.args.get("lines", 100))
    if os.path.exists(log_file):
        try:
            with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                all_lines = f.readlines()
                return jsonify({
                    "log_type": log_type,
                    "lines": len(all_lines),
                    "content": "".join(all_lines[-lines_count:])
                }), 200
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    return jsonify({"error": "Log file not found", "path": log_file}), 404

# ==============================================================================
# 🔍 SOVEREIGN WEBSEARCH API PROXY ROUTES (Parallel Cluster Port 3001)
# ==============================================================================

@app.route('/api/search_service/status', methods=['GET'])
def search_service_status():
    """Polls the local WebSearch API on port 3001 and Chromium CDP on port 9222."""
    search_online = False
    search_info = {}
    try:
        req = urllib.request.Request("http://127.0.0.1:3001/health", headers={"User-Agent": "NTA-MediaServer-Proxy/1.0"})
        with urllib.request.urlopen(req, timeout=1.5) as res:
            if res.status == 200:
                search_online = True
                search_info = json.loads(res.read().decode('utf-8'))
    except Exception:
        pass

    cdp_online = False
    cdp_browser = ""
    try:
        req = urllib.request.Request("http://127.0.0.1:9222/json/version", headers={"User-Agent": "NTA-MediaServer-Proxy/1.0"})
        with urllib.request.urlopen(req, timeout=1.5) as res:
            if res.status == 200:
                cdp_online = True
                cdp_data = json.loads(res.read().decode('utf-8'))
                cdp_browser = cdp_data.get("Browser", "Headless Chromium")
    except Exception:
        pass

    return jsonify({
        "status": "online" if search_online else "offline",
        "port": 3001,
        "gateway": "https://ntawebsearch.pages.dev",
        "chromium_cdp": {
            "status": "active" if cdp_online else "inactive",
            "port": 9222,
            "browser": cdp_browser or ("Chromium Sandbox" if search_online else "Standby")
        },
        "details": search_info
    }), 200

@app.route('/api/search_service/create_key', methods=['POST'])
def proxy_create_search_key():
    """Proxies key generation to the sovereign search server (Port 3001). One-time plaintext reveal."""
    data = request.get_json(silent=True) or {}
    name = data.get("name") or request.form.get("name") or "NeTuArk Sovereign Client"
    try:
        payload = json.dumps({"name": name}).encode('utf-8')
        req = urllib.request.Request(
            "http://127.0.0.1:3001/createapi",
            data=payload,
            headers={"Content-Type": "application/json", "User-Agent": "NTA-MediaServer-Proxy/1.0"}
        )
        with urllib.request.urlopen(req, timeout=3.5) as res:
            return res.read().decode('utf-8'), res.status, {'Content-Type': 'application/json'}
    except Exception as e:
        return jsonify({"error": f"Search server unreachable on port 3001: {str(e)}"}), 502

@app.route('/api/search_service/keys', methods=['GET'])
def proxy_list_search_keys():
    """Fetches masked active keys from search server."""
    try:
        req = urllib.request.Request("http://127.0.0.1:3001/api/keys", headers={"User-Agent": "NTA-MediaServer-Proxy/1.0"})
        with urllib.request.urlopen(req, timeout=2.5) as res:
            return res.read().decode('utf-8'), res.status, {'Content-Type': 'application/json'}
    except Exception as e:
        return jsonify({"success": False, "keys": [], "error": str(e)}), 200

@app.route('/api/search_service/revoke_key', methods=['POST'])
def proxy_revoke_search_key():
    """Revokes an API key on the search server."""
    data = request.get_json(silent=True) or {}
    try:
        payload = json.dumps(data).encode('utf-8')
        req = urllib.request.Request(
            "http://127.0.0.1:3001/api/keys/revoke",
            data=payload,
            headers={"Content-Type": "application/json", "User-Agent": "NTA-MediaServer-Proxy/1.0"}
        )
        with urllib.request.urlopen(req, timeout=2.5) as res:
            return res.read().decode('utf-8'), res.status, {'Content-Type': 'application/json'}
    except Exception as e:
        return jsonify({"error": str(e)}), 502

@app.route('/api/search_service/test_search', methods=['POST'])
def proxy_test_search():
    """Proxies interactive test search query to port 3001."""
    body = request.get_json(silent=True) or {}
    query = (body.get("query") or "").strip()
    if not query:
        return jsonify({"error": "Query cannot be empty"}), 400
    engine = body.get("engine", "google")
    api_key = (body.get("api_key") or "").strip()
    
    encoded_q = urllib.parse.quote_plus(query)
    target_url = f"http://127.0.0.1:3001/search?q={encoded_q}&engine={urllib.parse.quote_plus(engine)}"
    if api_key:
        target_url += f"&api_key={urllib.parse.quote_plus(api_key)}"
    
    try:
        req = urllib.request.Request(target_url, headers={"User-Agent": "NTA-MediaServer-Tester/1.0"})
        with urllib.request.urlopen(req, timeout=20.0) as res:
            return res.read().decode('utf-8'), res.status, {'Content-Type': 'application/json'}
    except urllib.error.HTTPError as he:
        err_body = he.read().decode('utf-8') if he.fp else str(he)
        return err_body, he.code, {'Content-Type': 'application/json'}
    except Exception as e:
        return jsonify({"error": f"Search failed or timed out: {str(e)}"}), 502

def standalone_network_watchdog():
    """Fallback watchdog for when server.py runs standalone without auto_tunnel.py coordinator."""
    time.sleep(10)
    was_offline = False
    offline_start = 0
    while True:
        try:
            # Check if auto_tunnel is actively running (which handles coordinator restart)
            is_tunnel_running = telemetry.is_process_running("auto_tunnel.py")
                
            if is_tunnel_running:
                # auto_tunnel supervisor handles network recovery and server restart
                time.sleep(10)
                continue

            if not telemetry.is_network_online(timeout=1.5):
                if not was_offline:
                    was_offline = True
                    offline_start = time.time()
                    print("\n[SERVER-WATCHDOG] ⚠️ Network disconnected! Pinging continuously...", flush=True)
                time.sleep(2)
                continue

            if was_offline:
                downtime = int(time.time() - offline_start)
                was_offline = False
                print(f"\n[SERVER-WATCHDOG] 🚀 Network restored after {downtime}s! Restarting server.py...", flush=True)
                time.sleep(1)
                repo_dir = os.path.dirname(os.path.abspath(__file__))
                subprocess.Popen([sys.executable, os.path.join(repo_dir, "server.py")], cwd=repo_dir)
                os._exit(0)
        except Exception:
            pass
        time.sleep(5)

import threading
threading.Thread(target=standalone_network_watchdog, daemon=True).start()

if __name__ == '__main__':
    # Run universally on the local network and internally
    app.run(host='0.0.0.0', port=3000)
