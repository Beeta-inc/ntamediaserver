import os
import time
import urllib.request
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
                <a href="/docs" class="docs-btn">📖 API Docs & SDKs</a>
            </div>

            <div class="summary-banner">
                <div class="summary-item">
                    <span class="summary-label">Cluster Status</span>
                    <span class="summary-value" id="cluster-status-text">
                        <span class="pulse-dot"></span> Active Sovereign Mesh
                    </span>
                </div>
                <div class="summary-item">
                    <span class="summary-label">Production Edge Gateway</span>
                    <span class="summary-value" style="font-family:'JetBrains Mono', monospace; font-size:13px; color:var(--cyan);">
                        https://ntamediaserver.pages.dev
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
