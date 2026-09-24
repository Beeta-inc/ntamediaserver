import subprocess
import re
import time
import urllib.request
import json
from datetime import datetime

FIRESTORE_URL = "https://firestore.googleapis.com/v1/projects/ntaf-754e1/databases/(default)/documents/mobileSignins/mediaServerConfig"

def update_firestore(url):
    data = {
        "fields": {
            "url": {"stringValue": url},
            "updatedAt": {"timestampValue": datetime.utcnow().isoformat() + "Z"}
        }
    }
    
    # We use ?updateMask.fieldPaths=url&updateMask.fieldPaths=updatedAt to ensure we PATCH correctly
    patch_url = FIRESTORE_URL + "?updateMask.fieldPaths=url&updateMask.fieldPaths=updatedAt"
    
    req = urllib.request.Request(patch_url, data=json.dumps(data).encode('utf-8'), method='PATCH')
    req.add_header('Content-Type', 'application/json')
    try:
        response = urllib.request.urlopen(req)
        print(f"\n[+] Successfully updated Firebase with new URL: {url}\n")
    except Exception as e:
        print(f"\n[-] Failed to update Firebase: {e}\n")

def run_tunnel():
    while True:
        print("Starting Cloudflare Tunnel...")
        process = subprocess.Popen(
            ["cloudflared", "tunnel", "--url", "http://localhost:3000"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True
        )
        
        for line in iter(process.stdout.readline, ''):
            print(line, end='')
            match = re.search(r'(https://[a-zA-Z0-9-]+\.trycloudflare\.com)', line)
            if match:
                url = match.group(1)
                update_firestore(url)
                
        process.wait()
        print("Tunnel closed or crashed. Restarting in 5 seconds...")
        time.sleep(5)

if __name__ == "__main__":
    run_tunnel()
