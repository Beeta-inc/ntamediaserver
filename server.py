import os
from flask import Flask, request, jsonify, send_from_directory
from werkzeug.utils import secure_filename
import time

app = Flask(__name__)

# Base storage directories on the phone
BASE_DIR = os.path.expanduser('~/ntamediaserver/uploads')
FEED_DIR = os.path.join(BASE_DIR, 'feed')
CHAT_DIR = os.path.join(BASE_DIR, 'chat')

# Ensure they exist
os.makedirs(FEED_DIR, exist_ok=True)
os.makedirs(CHAT_DIR, exist_ok=True)

@app.route('/')
def index():
    return """
    <html>
        <head>
            <title>Netuark Media Server (Python/Phone)</title>
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <style>
                body { font-family: sans-serif; padding: 20px; max-width: 600px; margin: 0 auto; background: #f4f4f9; }
                .container { background: #fff; padding: 20px; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }
                h1 { color: #333; }
                .form-group { margin-bottom: 15px; }
                label { display: block; margin-bottom: 5px; font-weight: bold; }
                input, select, button { width: 100%; padding: 10px; box-sizing: border-box; border-radius: 4px; border: 1px solid #ccc; }
                button { background: #007bff; color: white; border: none; cursor: pointer; margin-top: 10px; font-weight: bold; }
                button:hover { background: #0056b3; }
                #result { margin-top: 15px; word-wrap: break-word; }
                a { color: #007bff; text-decoration: none; }
            </style>
        </head>
        <body>
            <div class="container">
                <h1>Netuark Media Server (Phone)</h1>
                <form id="uploadForm">
                    <div class="form-group">
                        <label>Target Folder</label>
                        <select name="type">
                            <option value="chat">Chat</option>
                            <option value="feed">Feed</option>
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
                document.getElementById('uploadForm').addEventListener('submit', async (e) => {
                    e.preventDefault();
                    const formData = new FormData(e.target);
                    const resultDiv = document.getElementById('result');
                    resultDiv.innerHTML = 'Uploading...';
                    try {
                        const res = await fetch('/upload', { method: 'POST', body: formData });
                        const data = await res.json();
                        if (res.ok) {
                            resultDiv.innerHTML = '<span style="color:green;">Success!</span><br>File URL: <a href="' + data.fileUrl + '" target="_blank">' + data.fileUrl + '</a>';
                        } else {
                            resultDiv.innerHTML = '<span style="color:red;">Error: ' + (data.error || 'Upload failed') + '</span>';
                        }
                    } catch (err) {
                        resultDiv.innerHTML = '<span style="color:red;">Error: ' + err.message + '</span>';
                    }
                });
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
    if upload_type not in ['feed', 'chat']:
        upload_type = 'chat'
        
    target_dir = FEED_DIR if upload_type == 'feed' else CHAT_DIR
    
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
    target_dir = FEED_DIR if folder == 'feed' else CHAT_DIR
    return send_from_directory(target_dir, filename)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=3000)
