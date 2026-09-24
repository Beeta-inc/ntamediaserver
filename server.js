const express = require('express');
const multer = require('multer');
const cors = require('cors');
const path = require('path');
const fs = require('fs');
const { execSync } = require('child_process');

const app = express();
const PORT = process.env.PORT || 3000;
const DEVICE_ID = 'INWWI7LVRSHEUCVS';

// PC Temp Storage
const TEMP_DIR = path.join(__dirname, 'temp_uploads');
if (!fs.existsSync(TEMP_DIR)) fs.mkdirSync(TEMP_DIR, { recursive: true });

// Setup multer for temp file uploads on PC
const storage = multer.diskStorage({
    destination: function (req, file, cb) {
        cb(null, TEMP_DIR);
    },
    filename: function (req, file, cb) {
        const uniqueSuffix = Date.now() + '-' + Math.round(Math.random() * 1E9);
        const ext = path.extname(file.originalname);
        cb(null, file.fieldname + '-' + uniqueSuffix + ext);
    }
});

const upload = multer({ storage: storage });

app.use(cors());
app.use(express.json());

// Ensure the phone directories exist
try {
    execSync(\`adb -s \${DEVICE_ID} shell "mkdir -p /sdcard/ntamediaserver/uploads/feed"\`);
    execSync(\`adb -s \${DEVICE_ID} shell "mkdir -p /sdcard/ntamediaserver/uploads/chat"\`);
    console.log("Verified phone storage directories via ADB.");
} catch (e) {
    console.error("Failed to initialize phone directories. Is the phone connected?");
}

// Provide a basic UI for testing uploads
app.get('/', (req, res) => {
    res.send(\`
        <html>
            <head>
                <title>Netuark Media Server (ADB Backend)</title>
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
                    <h1>Netuark Media Server (Phone Storage)</h1>
                    <p>Upload files directly to the Android phone storage.</p>
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
                        <button type="submit">Upload to Phone</button>
                    </form>
                    <div id="result"></div>
                </div>
                <script>
                    document.getElementById('uploadForm').addEventListener('submit', async (e) => {
                        e.preventDefault();
                        const formData = new FormData(e.target);
                        const resultDiv = document.getElementById('result');
                        resultDiv.innerHTML = 'Uploading to phone...';
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
    \`);
});

// API Endpoint for file upload
app.post('/upload', upload.single('file'), (req, res) => {
    if (!req.file) {
        return res.status(400).json({ error: 'No file uploaded' });
    }
    
    const type = req.body.type === 'feed' ? 'feed' : 'chat';
    const phonePath = \`/sdcard/ntamediaserver/uploads/\${type}/\${req.file.filename}\`;
    
    try {
        // Push the temp file to the Android phone
        execSync(\`adb -s \${DEVICE_ID} push "\${req.file.path}" "\${phonePath}"\`);
        
        // Delete the temp file from PC to save space
        fs.unlinkSync(req.file.path);
        
        const fileUrl = \`/media/\${type}/\${req.file.filename}\`;
        res.json({
            message: 'File successfully pushed to Android storage',
            type: type,
            filename: req.file.filename,
            fileUrl: fileUrl,
            size: req.file.size
        });
    } catch (e) {
        console.error(e);
        res.status(500).json({ error: 'Failed to push file to phone storage via ADB' });
    }
});

// Endpoint to fetch media directly from the phone
app.get('/media/:type/:filename', (req, res) => {
    const { type, filename } = req.params;
    
    if (type !== 'feed' && type !== 'chat') {
        return res.status(400).send("Invalid type");
    }

    const phonePath = \`/sdcard/ntamediaserver/uploads/\${type}/\${filename}\`;
    const tempFilePath = path.join(TEMP_DIR, filename);

    try {
        // Pull the file from the phone
        execSync(\`adb -s \${DEVICE_ID} pull "\${phonePath}" "\${tempFilePath}"\`);
        
        // Serve the file
        res.sendFile(tempFilePath, (err) => {
            // Delete the temp file after serving
            if (fs.existsSync(tempFilePath)) {
                fs.unlinkSync(tempFilePath);
            }
        });
    } catch (e) {
        console.error(e);
        res.status(404).send("File not found on phone storage");
    }
});

app.listen(PORT, () => {
    console.log(\`Netuark ADB Media Server is running on port \${PORT}\`);
    console.log(\`The server is using the connected Android phone as the primary storage.\`);
});
