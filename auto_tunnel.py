import subprocess
import re
import time
import urllib.request
import json
import uuid
import sys
import os
from datetime import datetime
import concurrent.futures

# ---------------- CONFIGURATION ----------------
# The MAIN Firebase that your app reads the URL from
MAIN_FIRESTORE_URL = "https://firestore.googleapis.com/v1/projects/ntaf-754e1/databases/(default)/documents/mobileSignins/mediaServerConfig"

# The SECONDARY Firebase used just for these two devices to talk to each other
SYNC_FIRESTORE_URL = "https://firestore.googleapis.com/v1/projects/ntamedia-1f03d/databases/(default)/documents/serverSync/coordinator"

# Unique ID for this device (generated randomly on first run, or you can hardcode 'Device_A' and 'Device_B')
if not os.path.exists('.device_id'):
    with open('.device_id', 'w') as f:
        f.write(str(uuid.uuid4())[:8])
with open('.device_id', 'r') as f:
    DEVICE_ID = f.read().strip()

HEARTBEAT_INTERVAL = 10  # Seconds between heartbeats
TIMEOUT_THRESHOLD = 30   # Seconds before a master is considered "dead"
# -----------------------------------------------

current_process = None
current_url = None

def get_sync_state():
    try:
        req = urllib.request.Request(SYNC_FIRESTORE_URL)
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode())
            fields = data.get('fields', {})
            return {
                'master_id': fields.get('master_id', {}).get('stringValue', ''),
                'last_updated': fields.get('last_updated', {}).get('timestampValue', '1970-01-01T00:00:00Z')
            }
    except Exception as e:
        print(f"[!] Warning: Could not read sync state from secondary Firebase: {e}")
        return None

def get_telemetry():
    telemetry = {'battery': 'Unknown', 'network': 'Unknown', 'ram': 'Unknown', 'storage': 'Unknown'}
    try:
        bat_out = subprocess.check_output(['termux-battery-status'], text=True, stderr=subprocess.DEVNULL, timeout=2)
        bat = json.loads(bat_out)
        telemetry['battery'] = f"{bat.get('percentage', 0)}% ({bat.get('status', 'Unknown')})"
    except: pass
    
    try:
        wifi_out = subprocess.check_output(['termux-wifi-connectioninfo'], text=True, stderr=subprocess.DEVNULL, timeout=2)
        wifi = json.loads(wifi_out)
        if wifi.get('supplicant_state') == 'COMPLETED':
            telemetry['network'] = f"{wifi.get('ssid', 'Connected')} ({wifi.get('rssi', 0)} dBm, {wifi.get('link_speed_mbps', 0)} Mbps)"
        else:
            telemetry['network'] = 'Disconnected'
    except: pass
    
    try:
        free_out = subprocess.check_output(['free', '-m'], text=True, stderr=subprocess.DEVNULL, timeout=2)
        lines = free_out.strip().split('\n')
        if len(lines) > 1:
            parts = lines[1].split()
            if len(parts) >= 3:
                telemetry['ram'] = f"{parts[2]}MB / {parts[1]}MB Used"
    except: pass
    
    try:
        # Get storage for the main partition where /sdcard lives, usually /data
        df_out = subprocess.check_output(['df', '-h', '/data'], text=True, stderr=subprocess.DEVNULL, timeout=2)
        lines = df_out.strip().split('\n')
        if len(lines) > 1:
            parts = lines[1].split()
            if len(parts) >= 4:
                telemetry['storage'] = f"{parts[2]} / {parts[1]} Used ({parts[4]})"
    except: pass
    
    return json.dumps(telemetry)

def update_sync_state(role):
    telemetry_json = get_telemetry()
    telemetry_field = f"telemetry_{DEVICE_ID}"
    
    data = {
        "fields": {
            "master_id": {"stringValue": DEVICE_ID},
            "last_updated": {"timestampValue": datetime.utcnow().isoformat() + "Z"},
            telemetry_field: {"stringValue": telemetry_json}
        }
    }
    
    url = SYNC_FIRESTORE_URL + f"?updateMask.fieldPaths=master_id&updateMask.fieldPaths=last_updated&updateMask.fieldPaths={telemetry_field}"
    try:
        req = urllib.request.Request(url, data=json.dumps(data).encode('utf-8'), method='PATCH')
        req.add_header('Content-Type', 'application/json')
        urllib.request.urlopen(req, timeout=5)
    except Exception as e:
        print(f"[!] Warning: Failed to update secondary Firebase: {e}")

def update_main_firebase(url):
    data = {
        "fields": {
            "url": {"stringValue": url},
            "updatedAt": {"timestampValue": datetime.utcnow().isoformat() + "Z"}
        }
    }
    patch_url = MAIN_FIRESTORE_URL + "?updateMask.fieldPaths=url&updateMask.fieldPaths=updatedAt"
    try:
        req = urllib.request.Request(patch_url, data=json.dumps(data).encode('utf-8'), method='PATCH')
        req.add_header('Content-Type', 'application/json')
        urllib.request.urlopen(req, timeout=5)
        print(f"\n[+] Successfully updated MAIN Firebase with new URL: {url}\n")
    except Exception as e:
        print(f"\n[-] Failed to update MAIN Firebase: {e}\n")

import threading

def read_cloudflared_output(process):
    global current_url
    for line in iter(process.stdout.readline, ''):
        print(line, end='', flush=True)
        if current_url is None:
            match = re.search(r'(https://[a-zA-Z0-9-]+\.trycloudflare\.com)', line)
            if match:
                current_url = match.group(1)
                update_main_firebase(current_url)

def start_tunnel():
    global current_process, current_url
    if current_process is not None:
        return # Already running
        
    print("[*] Starting Cloudflare Tunnel as MASTER...")
    current_url = None
    current_process = subprocess.Popen(
        ["cloudflared", "tunnel", "--url", "http://localhost:3000"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True
    )
    
    # Read output in a background thread so we don't block the coordinator loop!
    t = threading.Thread(target=read_cloudflared_output, args=(current_process,))
    t.daemon = True
    t.start()

def stop_tunnel():
    global current_process, current_url
    if current_process:
        print("[*] Stopping Cloudflare Tunnel (Returning to BACKUP mode)...")
        current_process.terminate()
        current_process = None
        current_url = None
        # Make sure cloudflared is totally dead
        subprocess.run(["pkill", "-f", "cloudflared"])

def _download_sync_file(master_url, folder, f, local_path):
    print(f"[*] Built-in Sync: Downloading missing file {folder}/{f}")
    try:
        dl_req = urllib.request.Request(f"{master_url}/media/{folder}/{f}")
        with urllib.request.urlopen(dl_req, timeout=60) as dl_res:
            with open(local_path, 'wb') as out_f:
                out_f.write(dl_res.read())
    except Exception as e:
        print(f"[-] Sync error for {f}: {e}")

def sync_files_loop():
    BASE_DIR = '/sdcard/Download/NetuarkMedia'
    while True:
        try:
            # Only sync if we are BACKUP (tunnel is not running)
            if current_process is None:
                req = urllib.request.Request(MAIN_FIRESTORE_URL)
                with urllib.request.urlopen(req, timeout=5) as response:
                    data = json.loads(response.read().decode())
                    master_url = data.get('fields', {}).get('url', {}).get('stringValue')
                
                if master_url:
                    list_req = urllib.request.Request(f"{master_url}/api/sync/list")
                    with urllib.request.urlopen(list_req, timeout=10) as list_res:
                        master_files = json.loads(list_res.read().decode())
                        
                    download_tasks = []
                    for folder, files in master_files.items():
                        local_dir = os.path.join(BASE_DIR, folder)
                        os.makedirs(local_dir, exist_ok=True)
                        for f, size in files.items():
                            local_path = os.path.join(local_dir, f)
                            if not os.path.exists(local_path) or os.path.getsize(local_path) != size:
                                download_tasks.append((master_url, folder, f, local_path))
                    
                    if download_tasks:
                        print(f"[*] Built-in Sync: Found {len(download_tasks)} missing files. Downloading concurrently...")
                        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                            futures = [executor.submit(_download_sync_file, *task) for task in download_tasks]
                            concurrent.futures.wait(futures)
                        print("[*] Built-in Sync: Download batch complete.")
        except Exception as e:
            pass
        # Reduced sleep from 30s to 5s for much faster syncing while idle
        time.sleep(5)

def run_coordinator():
    global current_process
    print(f"Starting HA Tunnel Coordinator. Device ID: {DEVICE_ID}")
    
    # Start the built-in background file synchronizer
    sync_thread = threading.Thread(target=sync_files_loop)
    sync_thread.daemon = True
    sync_thread.start()
    
    failed_attempts = 0
    
    while True:
        state = get_sync_state()
        now = datetime.utcnow()
        
        if state is None:
            failed_attempts += 1
            print(f"[-] Could not reach Sync DB (Attempt {failed_attempts}).")
            
            # If we fail too many times, just assume Master role to keep the server alive!
            if failed_attempts >= 3:
                print("[!] Sync DB unreachable for too long. Assuming MASTER role to keep server online.")
                start_tunnel()
                if current_process and current_process.poll() is not None:
                    current_process = None
                    start_tunnel()
                
            time.sleep(HEARTBEAT_INTERVAL)
            continue
            
        # Reset failed attempts on success
        failed_attempts = 0
        
        last_updated_str = state['last_updated'].replace('Z', '')
        # Handle microsecond parsing
        if '.' in last_updated_str:
            last_updated = datetime.strptime(last_updated_str, "%Y-%m-%dT%H:%M:%S.%f")
        else:
            last_updated = datetime.strptime(last_updated_str, "%Y-%m-%dT%H:%M:%S")
            
        age_seconds = (now - last_updated).total_seconds()
        
        # Check if we should be master
        is_master_dead = age_seconds > TIMEOUT_THRESHOLD
        am_i_master = (state['master_id'] == DEVICE_ID)
        
        if is_master_dead or am_i_master:
            # I am the master, or taking over!
            if not am_i_master:
                print(f"[!] Master died! Taking over as new MASTER. (Age: {age_seconds}s)")
            
            update_sync_state("master")
            start_tunnel()
            
            # If process died unexpectedly, restart it
            if current_process and current_process.poll() is not None:
                print("Tunnel crashed. Restarting...")
                current_process = None
                start_tunnel()
                
        else:
            # I am backup
            print(f"[-] Standing by as BACKUP. Master {state['master_id']} is alive (Ping: {int(age_seconds)}s ago).")
            stop_tunnel()
            
        time.sleep(HEARTBEAT_INTERVAL)

if __name__ == "__main__":
    try:
        run_coordinator()
    except KeyboardInterrupt:
        print("\nExiting...")
        stop_tunnel()
