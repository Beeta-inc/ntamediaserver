import os
from flask import Flask, request, jsonify, send_from_directory, render_template_string
from werkzeug.utils import secure_filename
import time
import urllib.request
import json
import sys
import subprocess
import shutil

# Attempt to load the sync URL from the tunnel script
try:
    import auto_tunnel
    SYNC_URL = auto_tunnel.SYNC_FIRESTORE_URL
except Exception as e:
    SYNC_URL = ""

app = Flask(__name__)

# Base storage directories on the phone's PUBLIC visible storage
# This saves properly to the hardware's main storage, not hidden inside Termux
BASE_DIR = '/sdcard/Download/NetuarkMedia'
FEED_DIR = os.path.join(BASE_DIR, 'feed')
CHAT_DIR = os.path.join(BASE_DIR, 'chat')
VIDEO_DIR = os.path.join(BASE_DIR, 'videos')
DOC_DIR = os.path.join(BASE_DIR, 'docs')

# Ensure they exist
for directory in [FEED_DIR, CHAT_DIR, VIDEO_DIR, DOC_DIR]:
    os.makedirs(directory, exist_ok=True)

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
                    --text-main: #f8fafc;
                    --text-sub: #94a3b8;
                }}
                * {{ box-sizing: border-box; margin: 0; padding: 0; }}
                body {{
                    font-family: 'Plus Jakarta Sans', -apple-system, sans-serif;
                    background: var(--bg-dark);
                    color: var(--text-main);
                    padding: 24px 16px;
                    max-width: 960px;
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
                    grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
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
                .node-card.master {{ border-color: rgba(16, 185, 129, 0.4); }}
                .node-card.phone {{ border-color: rgba(0, 243, 255, 0.4); }}
                .node-card.offline {{ opacity: 0.7; border-color: rgba(244, 63, 94, 0.3); }}
                
                .card-header {{
                    display: flex;
                    justify-content: space-between;
                    align-items: flex-start;
                    margin-bottom: 14px;
                }}
                .node-title {{
                    font-size: 14px;
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
                    font-size: 12px;
                    padding: 6px 0;
                    border-top: 1px solid rgba(255,255,255,0.05);
                }}
                .metric-label {{ color: var(--text-sub); }}
                .metric-val {{ font-family: 'JetBrains Mono', monospace; color: #fff; text-align: right; }}
                
                .bar-container {{
                    background: rgba(255,255,255,0.06);
                    height: 5px;
                    border-radius: 3px;
                    overflow: hidden;
                    margin-top: 4px;
                }}
                .bar-fill {{
                    height: 100%;
                    border-radius: 3px;
                    background: var(--blue);
                }}
                .bar-fill.green {{ background: var(--emerald); }}
                .bar-fill.amber {{ background: var(--amber); }}
                .bar-fill.rose {{ background: var(--rose); }}
                
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
                    <span class="brand-badge">HA v2.0</span>
                </div>
                <a href="/docs" class="docs-btn">📖 API Docs & SDKs</a>
            </div>

            <div class="summary-banner">
                <div class="summary-item">
                    <span class="summary-label">Cluster Status</span>
                    <span class="summary-value" id="cluster-status-text">
                        <span class="pulse-dot"></span> Active-Active Redundant Mesh
                    </span>
                </div>
                <div class="summary-item">
                    <span class="summary-label">Production Edge Gateway</span>
                    <span class="summary-value" style="font-family:'JetBrains Mono', monospace; font-size:13px; color:var(--cyan);">
                        https://ntamediaserver.pages.dev
                    </span>
                </div>
                <div class="summary-item">
                    <span class="summary-label">Telemetry Coordinator</span>
                    <span class="summary-value" id="nodes-online-count" style="font-family:'JetBrains Mono', monospace; font-size:13px;">
                        Scanning nodes...
                    </span>
                </div>
            </div>

            <div class="section-header">
                <div class="section-title">Cluster Nodes & Live Hardware Vitals</div>
                <div class="sync-timer" id="sync-timer">Auto-refresh: 5s</div>
            </div>

            <div class="dashboard-grid" id="telemetry-dashboard">
                <div class="node-card">
                    <p style="color:var(--text-sub); font-size:13px;">Connecting to telemetry coordinator and phone micro-nodes...</p>
                </div>
            </div>

            <div class="upload-container">
                <div class="section-title">Ingestion Test Console</div>
                <p style="color:var(--text-sub); font-size:12px; margin-top:2px;">
                    Uploaded assets are automatically mirrored across both cluster datacenters.
                </p>
                <form id="uploadForm" class="upload-form">
                    <div>
                        <label style="display:block; font-size:11px; font-family:'JetBrains Mono', monospace; color:var(--text-sub); margin-bottom:6px;">Target Folder / Media Type</label>
                        <select name="type" class="form-control">
                            <option value="chat">Chat (Images / Audio / Attachments)</option>
                            <option value="feed">Feed (Images / Banners)</option>
                            <option value="videos">Videos (Chunked Streaming)</option>
                            <option value="docs">Documents (PDF / Archive / Text)</option>
                        </select>
                    </div>
                    <div>
                        <label style="display:block; font-size:11px; font-family:'JetBrains Mono', monospace; color:var(--text-sub); margin-bottom:6px;">Choose File</label>
                        <input type="file" name="file" class="form-control" required />
                    </div>
                    <button type="submit" class="btn-submit">Upload to Media Cluster</button>
                </form>
                <div id="result"></div>
            </div>

            <script>
                const SYNC_URL = "{SYNC_URL}" || "https://firestore.googleapis.com/v1/projects/ntamedia-1f03d/databases/(default)/documents/serverSync/coordinator";
                const PHONE_NODE_URL = "https://phone-whisper-server.pages.dev/telemetry";

                function formatAgo(timestampStr) {{
                    if (!timestampStr) return "Never";
                    const diff = Math.floor((Date.now() - new Date(timestampStr).getTime()) / 1000);
                    if (diff < 5) return "Just now";
                    if (diff < 60) return diff + "s ago";
                    if (diff < 3600) return Math.floor(diff / 60) + "m ago";
                    return Math.floor(diff / 3600) + "h ago";
                }}

                function parsePct(usedStr, totalStr) {{
                    const u = parseFloat(usedStr) || 0;
                    const t = parseFloat(totalStr) || 1;
                    return Math.min(100, Math.round((u / t) * 100));
                }}

                async function fetchAllTelemetry() {{
                    const dashboardEl = document.getElementById('telemetry-dashboard');
                    let cardsHtml = '';
                    let onlineCount = 0;

                    // ── 1. Fetch Sovereign Phone AI Datacenter (Redmi 9i ARM64 micro-node) ──
                    try {{
                        const phoneRes = await fetch(PHONE_NODE_URL, {{ signal: AbortSignal.timeout(4000) }});
                        if (phoneRes.ok) {{
                            const p = await phoneRes.json();
                            onlineCount++;
                            const ramPct = parsePct(p.memory?.used_mb, p.memory?.total_mb);
                            const storUsed = (p.storage?.total_gb - p.storage?.free_gb).toFixed(1);
                            const storPct = parsePct(storUsed, p.storage?.total_gb);
                            const ramColor = ramPct > 85 ? 'rose' : (ramPct > 70 ? 'amber' : 'green');
                            const storColor = storPct > 85 ? 'rose' : (storPct > 70 ? 'amber' : 'green');

                            cardsHtml += `
                            <div class="node-card phone">
                                <div class="card-header">
                                    <div>
                                        <div class="node-title">${{p.device?.model || 'Redmi 9i (Phone Node)'}}</div>
                                        <div class="node-sub">${{p.device?.arch || 'ARM64 Cortex-A53'}} &bull; Node 1</div>
                                    </div>
                                    <span class="badge active">● ONLINE</span>
                                </div>
                                <div class="metric-row">
                                    <span class="metric-label">Role</span>
                                    <span class="metric-val" style="color:var(--cyan)">Sovereign Phone AI & Storage</span>
                                </div>
                                <div class="metric-row">
                                    <span class="metric-label">Battery</span>
                                    <span class="metric-val">${{p.battery?.level || 0}}% (${{p.battery?.status || 'Active'}}, ${{p.battery?.temperature || 32}}°C)</span>
                                </div>
                                <div class="metric-row">
                                    <span class="metric-label">CPU / Cores</span>
                                    <span class="metric-val">${{p.cpu?.usage_percent || 0}}% (${{p.cpu?.cores || 8}} Cores)</span>
                                </div>
                                <div class="metric-row">
                                    <span class="metric-label">RAM Usage</span>
                                    <span class="metric-val">${{p.memory?.used_mb || 0}} / ${{p.memory?.total_mb || 0}} MB (${{ramPct}}%)</span>
                                </div>
                                <div class="bar-container"><div class="bar-fill ${{ramColor}}" style="width:${{ramPct}}%"></div></div>
                                <div class="metric-row" style="margin-top:6px;">
                                    <span class="metric-label">Internal Flash</span>
                                    <span class="metric-val">${{storUsed}} / ${{p.storage?.total_gb || 0}} GB (${{storPct}}%)</span>
                                </div>
                                <div class="bar-container"><div class="bar-fill ${{storColor}}" style="width:${{storPct}}%"></div></div>
                                <a href="https://phone-whisper-server.pages.dev" target="_blank" class="tunnel-link">
                                    🌐 https://phone-whisper-server.pages.dev
                                </a>
                            </div>`;
                        }}
                    }} catch (err) {{
                        console.warn('Phone node telemetry offline or slow:', err);
                    }}

                    // ── 2. Fetch Coordinator (NTA Master & Backup Nodes) ──
                    try {{
                        const coordRes = await fetch(SYNC_URL, {{ signal: AbortSignal.timeout(4000) }});
                        if (coordRes.ok) {{
                            const coordData = await coordRes.json();
                            const fields = coordData.fields || {{}};
                            const masterId = fields.master_id ? fields.master_id.stringValue : '';
                            const lastMasterUpdate = fields.last_updated ? fields.last_updated.timestampValue : null;

                            for (const key in fields) {{
                                if (key.startsWith('telemetry_')) {{
                                    const devId = key.replace('telemetry_', '');
                                    const isMaster = (devId === masterId);
                                    let tel = {{}};
                                    try {{ tel = JSON.parse(fields[key].stringValue); }} catch(_) {{}}

                                    const backupKey = `backup_updated_${{devId}}`;
                                    const devUpdateStr = isMaster ? lastMasterUpdate : (fields[backupKey] ? fields[backupKey].timestampValue : null);
                                    const peerKey = `peer_url_${{devId}}`;
                                    const peerUrl = fields[peerKey] ? fields[peerKey].stringValue : '';

                                    // Determine health
                                    let isAlive = false;
                                    let ageSec = Infinity;
                                    if (devUpdateStr) {{
                                        ageSec = (Date.now() - new Date(devUpdateStr).getTime()) / 1000;
                                        isAlive = (ageSec < 45);
                                    }}
                                    // Automatically prune stale ghost replica nodes offline for > 1 hour
                                    if (!isMaster && !isAlive && ageSec > 3600) {{
                                        continue;
                                    }}
                                    if (isAlive) onlineCount++;

                                    const badgeClass = isAlive ? (isMaster ? 'active' : 'standby') : 'offline';
                                    const badgeText = isAlive ? (isMaster ? '● MASTER' : '● STANDBY') : '● OFFLINE';

                                    // Parse RAM & Storage strings like "1278MB / 1794MB Used"
                                    const ramMatches = (tel.ram || '').match(/(\\d+)\\s*MB\\s*\\/\\s*(\\d+)\\s*MB/i);
                                    const ramPct = ramMatches ? parsePct(ramMatches[1], ramMatches[2]) : 50;
                                    const storMatches = (tel.storage || '').match(/(\\d+)\\s*G\\s*\\/\\s*(\\d+)\\s*G/i);
                                    const storPct = storMatches ? parsePct(storMatches[1], storMatches[2]) : 50;

                                    cardsHtml += `
                                    <div class="node-card ${{isMaster ? 'master' : (isAlive ? '' : 'offline')}}">
                                        <div class="card-header">
                                            <div>
                                                <div class="node-title">Cluster Device: ${{devId}}</div>
                                                <div class="node-sub">${{isMaster ? 'Master Ingestion Node' : 'Backup Sync Replica'}}</div>
                                            </div>
                                            <span class="badge ${{badgeClass}}">${{badgeText}}</span>
                                        </div>
                                        <div class="metric-row">
                                            <span class="metric-label">Heartbeat</span>
                                            <span class="metric-val">${{formatAgo(devUpdateStr)}}</span>
                                        </div>
                                        <div class="metric-row">
                                            <span class="metric-label">RAM Condition</span>
                                            <span class="metric-val">${{tel.ram || 'Available'}}</span>
                                        </div>
                                        <div class="bar-container"><div class="bar-fill green" style="width:${{ramPct}}%"></div></div>
                                        <div class="metric-row" style="margin-top:6px;">
                                            <span class="metric-label">Storage Condition</span>
                                            <span class="metric-val">${{tel.storage || 'Mounted'}}</span>
                                        </div>
                                        <div class="bar-container"><div class="bar-fill blue" style="width:${{storPct}}%"></div></div>
                                        ${{peerUrl ? `<a href="${{peerUrl}}" target="_blank" class="tunnel-link">⚡ ${{peerUrl}}</a>` : ''}}
                                    </div>`;
                                }}
                            }}
                        }}
                    }} catch (cErr) {{
                        console.warn('Coordinator telemetry offline:', cErr);
                    }}

                    if (cardsHtml === '') {{
                        cardsHtml = '<div class="node-card"><p style="color:var(--rose)">Unable to connect to telemetry endpoints. Retrying automatically...</p></div>';
                    }}

                    dashboardEl.innerHTML = cardsHtml;
                    const onlineCountEl = document.getElementById('nodes-online-count');
                    if (onlineCountEl) {{
                        onlineCountEl.innerHTML = `<span style="color:var(--emerald)">${{onlineCount}} Nodes Active</span>`;
                    }}
                }}

                fetchAllTelemetry();
                setInterval(fetchAllTelemetry, 5000);

                // Upload test handler
                document.getElementById('uploadForm').addEventListener('submit', async (e) => {{
                    e.preventDefault();
                    const formData = new FormData(e.target);
                    const resultDiv = document.getElementById('result');
                    resultDiv.innerHTML = '<span style="color:var(--cyan)">Transferring to media cluster...</span>';
                    try {{
                        const res = await fetch('/upload', {{ method: 'POST', body: formData }});
                        const data = await res.json();
                        if (res.ok) {{
                            const fullUrl = window.location.origin + data.fileUrl;
                            resultDiv.innerHTML = '<span style="color:var(--emerald)">✅ Upload Succeeded!</span><br>Live CDN URL: <a href="' + data.fileUrl + '" target="_blank" style="color:var(--cyan);text-decoration:underline;">' + fullUrl + '</a>';
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
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    
    upload_type = request.form.get('type', 'chat')
    
    if upload_type == 'feed':
        target_dir = FEED_DIR
    elif upload_type == 'videos':
        target_dir = VIDEO_DIR
    elif upload_type == 'docs':
        target_dir = DOC_DIR
    else:
        target_dir = CHAT_DIR
        upload_type = 'chat'
        
    filename = secure_filename(file.filename)
    unique_name = f"{int(time.time())}_{filename}"
    file_path = os.path.join(target_dir, unique_name)
    
    file.save(file_path)
    
    file_url = f"/media/{upload_type}/{unique_name}"
    return jsonify({
        'message': 'File uploaded successfully',
        'fileUrl': file_url
    })

def _is_corrupt_zstd_media(fpath, fname):
    """Detects if an image/media file on disk is incorrectly stored as raw zstd compressed bytes"""
    if not os.path.exists(fpath):
        return False
    if any(fname.lower().endswith(ext) for ext in [".png", ".jpg", ".jpeg", ".webp", ".gif", ".webm", ".mp4", ".mp3", ".ogg"]):
        try:
            with open(fpath, "rb") as f:
                header = f.read(4)
            if header == b"\x28\xb5\x2f\xfd":
                try:
                    os.remove(fpath)
                    print(f"[!] Purged corrupt zstd file from disk: {fpath}")
                except Exception:
                    pass
                return True
        except Exception:
            pass
    return False

def fallback_and_serve(target_dir, folder, filename):
    file_path = os.path.join(target_dir, filename)
    if os.path.exists(file_path):
        if not _is_corrupt_zstd_media(file_path, filename):
            return send_from_directory(target_dir, filename)
        
    for fallback_dir in [CHAT_DIR, FEED_DIR, DOC_DIR, VIDEO_DIR]:
        cand_path = os.path.join(fallback_dir, filename)
        if os.path.exists(cand_path):
            if not _is_corrupt_zstd_media(cand_path, filename):
                return send_from_directory(fallback_dir, filename)
            
    # P2P Fallback to Counterpart Node (Redmi 9i Sovereign Micro-Datacenter)
    try:
        device_id = ""
        if os.path.exists('.device_id'):
            with open('.device_id', 'r') as f:
                device_id = f.read().strip()
                
        peer_urls = ["https://phone-whisper-server.pages.dev"]
        try:
            req = urllib.request.Request("https://firestore.googleapis.com/v1/projects/ntamedia-1f03d/databases/(default)/documents/serverSync/coordinator")
            with urllib.request.urlopen(req, timeout=3) as response:
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
            f"/v1/storage/objects/media/{filename}",
            f"/v1/storage/objects/avatars/{filename}",
            f"/v1/storage/objects/stickers/{filename}",
            f"/media/{folder}/{filename}",
            f"/media/videos/{filename}",
            f"/media/chat/{filename}",
            f"/media/feed/{filename}",
            f"/media/docs/{filename}",
            f"/s/public/{filename}"
        ]

        for peer in peer_urls:
            for c_path in candidate_paths:
                try:
                    peer_file_url = f"{peer}{c_path}"
                    dl_req = urllib.request.Request(peer_file_url, headers={"User-Agent": "NTA-MediaServer/MeshSync"})
                    with urllib.request.urlopen(dl_req, timeout=8) as dl_res:
                        if dl_res.status == 200:
                            data = dl_res.read()
                            # Reject if peer sent zstd compressed bytes for media
                            if any(filename.lower().endswith(ext) for ext in [".png", ".jpg", ".jpeg", ".webp", ".gif"]) and data[:4] == b"\x28\xb5\x2f\xfd":
                                print(f"[-] Refusing corrupt zstd payload from peer {peer} for {filename}")
                                continue
                            os.makedirs(target_dir, exist_ok=True)
                            tmp_file = file_path + ".tmp"
                            with open(tmp_file, 'wb') as out_f:
                                out_f.write(data)
                            os.replace(tmp_file, file_path)
                            print(f"[+] Successfully downloaded {filename} from peer {peer} ({c_path})!")
                            return send_from_directory(target_dir, filename)
                except Exception:
                    continue
    except Exception as e:
        print(f"Failed in P2P fallback: {e}")
            
    # If all fails, let Flask return a standard 404
    return send_from_directory(target_dir, filename)

@app.route('/media/<folder>/<filename>')
def serve_media(folder, filename):
    if folder == 'feed':
        target_dir = FEED_DIR
    elif folder == 'videos':
        target_dir = VIDEO_DIR
    elif folder == 'docs':
        target_dir = DOC_DIR
    else:
        target_dir = CHAT_DIR
        
    return fallback_and_serve(target_dir, folder, filename)

@app.route('/v1/storage/objects/<folder>/<filename>', methods=['PUT', 'OPTIONS'])
def rest_upload(folder, filename):
    if request.method == 'OPTIONS':
        return '', 204
        
    if folder == 'avatars' or folder == 'banners':
        target_dir = DOC_DIR
    elif folder == 'stickers':
        target_dir = FEED_DIR 
    else:
        target_dir = CHAT_DIR
        
    filename = secure_filename(filename)
    file_path = os.path.join(target_dir, filename)
    
    with open(file_path, 'wb') as f:
        f.write(request.data)
        
    return jsonify({"success": True, "url": f"/v1/storage/objects/{folder}/{filename}"}), 200

@app.route('/v1/storage/objects/<folder>/<filename>', methods=['GET', 'OPTIONS'])
def rest_serve(folder, filename):
    if folder == 'avatars' or folder == 'banners':
        target_dir = DOC_DIR
    elif folder == 'stickers':
        target_dir = FEED_DIR 
    else:
        target_dir = CHAT_DIR
        
    return fallback_and_serve(target_dir, folder, filename)

def propagate_delete(folder, filename, path_prefix):
    if request.args.get('propagate', 'true') != 'true':
        return
    try:
        device_id = ""
        if os.path.exists('.device_id'):
            with open('.device_id', 'r') as f:
                device_id = f.read().strip()
                
        req = urllib.request.Request("https://firestore.googleapis.com/v1/projects/ntamedia-1f03d/databases/(default)/documents/serverSync/coordinator")
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode())
            
        peer_urls = []
        for key, value in data.get('fields', {}).items():
            if key.startswith('peer_url_') and key != f'peer_url_{device_id}':
                peer_urls.append(value.get('stringValue'))
                
        for peer in peer_urls:
            try:
                peer_file_url = f"{peer}{path_prefix}/{folder}/{filename}?propagate=false"
                print(f"[*] Propagating delete to {peer}")
                dl_req = urllib.request.Request(peer_file_url, method='DELETE')
                urllib.request.urlopen(dl_req, timeout=5)
            except Exception as e:
                print(f"[-] Peer delete failed for {peer}: {e}")
    except Exception as e:
        print(f"Failed to propagate delete: {e}")

@app.route('/media/<folder>/<filename>', methods=['DELETE'])
def delete_media(folder, filename):
    if folder == 'feed':
        target_dir = FEED_DIR
    elif folder == 'videos':
        target_dir = VIDEO_DIR
    elif folder == 'docs':
        target_dir = DOC_DIR
    else:
        target_dir = CHAT_DIR
        
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
        
    if folder == 'avatars' or folder == 'banners':
        target_dir = DOC_DIR
    elif folder == 'stickers':
        target_dir = FEED_DIR 
    else:
        target_dir = CHAT_DIR
        
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
    for folder, path in [('feed', FEED_DIR), ('chat', CHAT_DIR), ('videos', VIDEO_DIR), ('docs', DOC_DIR)]:
        files_info[folder] = {}
        if os.path.exists(path):
            for f in os.listdir(path):
                full_path = os.path.join(path, f)
                if os.path.isfile(full_path):
                    files_info[folder][f] = os.path.getsize(full_path)
    return jsonify(files_info)

# ==============================================================================
# 🛰️ AUTONOMOUS INTERNAL COMMUNICATOR & REMOTE MANAGEMENT RPC
# Allows remote cluster management, auto-updates, diagnostics, and control
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
    git_sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=repo_dir, capture_output=True, text=True).stdout.strip()
    git_branch = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_dir, capture_output=True, text=True).stdout.strip()
    
    free_gb = 0.0
    try:
        stat = os.statvfs(BASE_DIR)
        free_gb = round((stat.f_bavail * stat.f_frsize) / (1024**3), 2)
    except Exception:
        pass
        
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
        "free_gb": free_gb,
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
    try:
        pull_res = subprocess.run(["git", "pull", "--rebase", "origin", "main"], cwd=repo_dir, capture_output=True, text=True, timeout=35)
        # Schedule reload in a background thread
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

if __name__ == '__main__':
    # Run universally on the local network and internally
    app.run(host='0.0.0.0', port=3000)
