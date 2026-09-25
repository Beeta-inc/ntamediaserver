import os
from flask import Flask, request, jsonify, send_from_directory, render_template_string
from werkzeug.utils import secure_filename
import time
import sys

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
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
    return response

@app.route('/')
def index():
    return f"""
    <html>
        <head>
            <title>Netuark HA Media Server</title>
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <style>
                body {{ font-family: sans-serif; padding: 20px; max-width: 800px; margin: 0 auto; background: #f4f4f9; }}
                .container {{ background: #fff; padding: 20px; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); margin-bottom: 20px; }}
                h1, h2 {{ color: #333; }}
                .form-group {{ margin-bottom: 15px; }}
                label {{ display: block; margin-bottom: 5px; font-weight: bold; }}
                input, select, button {{ width: 100%; padding: 10px; box-sizing: border-box; border-radius: 4px; border: 1px solid #ccc; }}
                button {{ background: #007bff; color: white; border: none; cursor: pointer; margin-top: 10px; font-weight: bold; }}
                button:hover {{ background: #0056b3; }}
                #result {{ margin-top: 15px; word-wrap: break-word; }}
                a {{ color: #007bff; text-decoration: none; }}
                
                .dashboard {{ display: flex; gap: 20px; flex-wrap: wrap; }}
                .device-card {{ flex: 1; min-width: 300px; background: #fafafa; border: 1px solid #ddd; border-radius: 8px; padding: 15px; }}
                .device-card h3 {{ margin-top: 0; display: flex; justify-content: space-between; }}
                .badge {{ padding: 4px 8px; border-radius: 12px; font-size: 12px; color: white; }}
                .badge.master {{ background: #28a745; }}
                .badge.backup {{ background: #6c757d; }}
                .badge.offline {{ background: #dc3545; }}
                .stat-row {{ display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid #eee; }}
                .stat-row:last-child {{ border-bottom: none; }}
                .stat-label {{ font-weight: bold; color: #555; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h2>Cluster Dashboard</h2>
                <div class="dashboard" id="telemetry-dashboard">
                    <p>Loading telemetry...</p>
                </div>
            </div>
            
            <div class="container">
                <h2>Upload Media</h2>
                <p>Files are mirrored automatically to all cluster nodes.</p>
                <form id="uploadForm">
                    <div class="form-group">
                        <label>Target Folder / File Type</label>
                        <select name="type">
                            <option value="chat">Chat (Images/Audio)</option>
                            <option value="feed">Feed (Images)</option>
                            <option value="videos">Videos</option>
                            <option value="docs">Documents (PDF, ZIP, etc)</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label>File</label>
                        <input type="file" name="file" required />
                    </div>
                    <button type="submit">Upload</button>
                </form>
                <div id="result"></div>
            </div>
            
            <script>
                const SYNC_URL = "{SYNC_URL}";
                
                async function fetchTelemetry() {{
                    if (!SYNC_URL) {{
                        document.getElementById('telemetry-dashboard').innerHTML = '<p style="color:red">SYNC_FIRESTORE_URL is not configured in auto_tunnel.py</p>';
                        return;
                    }}
                    
                    try {{
                        const res = await fetch(SYNC_URL);
                        const data = await res.json();
                        const fields = data.fields || {{}};
                        const masterId = fields.master_id ? fields.master_id.stringValue : 'Unknown';
                        
                        let html = '';
                        
                        // Look for all telemetry fields (telemetry_DEVICEID)
                        for (const key in fields) {{
                            if (key.startsWith('telemetry_')) {{
                                const deviceId = key.replace('telemetry_', '');
                                let tel = {{}};
                                try {{
                                    tel = JSON.parse(fields[key].stringValue);
                                }} catch(e) {{}}
                                
                                const isMaster = (deviceId === masterId);
                                const badgeClass = isMaster ? 'master' : 'backup';
                                const badgeText = isMaster ? 'MASTER (Active)' : 'BACKUP (Standby)';
                                
                                html += `
                                <div class="device-card">
                                    <h3>Device: ${{deviceId}} <span class="badge ${{badgeClass}}">${{badgeText}}</span></h3>
                                    <div class="stat-row"><span class="stat-label">Battery</span><span>${{tel.battery || 'N/A'}}</span></div>
                                    <div class="stat-row"><span class="stat-label">Network</span><span>${{tel.network || 'N/A'}}</span></div>
                                    <div class="stat-row"><span class="stat-label">RAM</span><span>${{tel.ram || 'N/A'}}</span></div>
                                    <div class="stat-row"><span class="stat-label">Storage</span><span>${{tel.storage || 'N/A'}}</span></div>
                                </div>
                                `;
                            }}
                        }}
                        
                        if (html === '') html = '<p>No telemetry data found yet. Make sure auto_tunnel.py is running on the phones.</p>';
                        document.getElementById('telemetry-dashboard').innerHTML = html;
                        
                    }} catch (e) {{
                        console.error(e);
                    }}
                }}
                
                // Fetch immediately and then every 15 seconds
                fetchTelemetry();
                setInterval(fetchTelemetry, 15000);

                document.getElementById('uploadForm').addEventListener('submit', async (e) => {{
                    e.preventDefault();
                    const formData = new FormData(e.target);
                    const resultDiv = document.getElementById('result');
                    resultDiv.innerHTML = 'Uploading...';
                    try {{
                        const res = await fetch('/upload', {{ method: 'POST', body: formData }});
                        const data = await res.json();
                        if (res.ok) {{
                            resultDiv.innerHTML = '<span style="color:green;">Success!</span><br>File URL: <a href="' + data.fileUrl + '" target="_blank">' + data.fileUrl + '</a>';
                        }} else {{
                            resultDiv.innerHTML = '<span style="color:red;">Error: ' + (data.error || 'Upload failed') + '</span>';
                        }}
                    }} catch (err) {{
                        resultDiv.innerHTML = '<span style="color:red;">Error: ' + err.message + '</span>';
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
        
    return send_from_directory(target_dir, filename)

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

@app.route('/v1/storage/objects/<folder>/<filename>', methods=['GET'])
def rest_serve(folder, filename):
    if folder == 'avatars' or folder == 'banners':
        target_dir = DOC_DIR
    elif folder == 'stickers':
        target_dir = FEED_DIR 
    else:
        target_dir = CHAT_DIR
        
    return send_from_directory(target_dir, filename)

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

if __name__ == '__main__':
    # Run universally on the local network and internally
    app.run(host='0.0.0.0', port=3000)
