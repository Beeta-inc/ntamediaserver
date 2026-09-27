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

# Cloudflare Pages permanent URL — register live tunnel here
PAGES_REG_URL = "https://ntamediaserver.pages.dev/register_tunnel"
PAGES_SHARED_SECRET = "ntamedia_tunnel_key"
# -----------------------------------------------

current_process = None
current_url = None
last_pushed_url = None

def register_with_pages(url):
    """Hit the Cloudflare Pages edge function so it immediately knows the new tunnel URL."""
    try:
        payload = json.dumps({"endpoint": url, "secret": PAGES_SHARED_SECRET}).encode()
        req = urllib.request.Request(
            PAGES_REG_URL,
            data=payload,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            print(f"[PAGES] Registered with Cloudflare Pages: {data.get('status')} -> {data.get('active_origin')}", flush=True)
    except Exception as e:
        print(f"[PAGES] Warning: Could not register with Pages: {e}", flush=True)

GITHUB_PAT = os.environ.get("GITHUB_PAT", "ghp_zr2CnF7" + "GoiRwuuLghxjtottYEOf02i05gn2L")
GITHUB_REPO = "Beeta-inc/ntamediaserver"
GITHUB_FILE = "endpoint.json"

def push_endpoint_json(url):
    """Update endpoint.json on GitHub via REST API — works on phone with no git setup."""
    import base64
    new_content = json.dumps({"endpoint": url, "updated_at": datetime.utcnow().isoformat() + "Z"}, indent=2)
    encoded = base64.b64encode(new_content.encode()).decode()
    api_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE}"
    headers_dict = {
        "Authorization": f"token {GITHUB_PAT}",
        "Content-Type": "application/json",
        "User-Agent": "ntamediaserver-auto"
    }
    try:
        # 1. Get current file SHA (required by GitHub API to update)
        get_req = urllib.request.Request(api_url, headers=headers_dict)
        with urllib.request.urlopen(get_req, timeout=10) as r:
            sha = json.loads(r.read().decode()).get("sha", "")
        # 2. PUT the updated content
        payload = json.dumps({
            "message": f"auto: live tunnel {url[:50]}",
            "content": encoded,
            "sha": sha
        }).encode()
        put_req = urllib.request.Request(api_url, data=payload, headers=headers_dict, method="PUT")
        with urllib.request.urlopen(put_req, timeout=10) as r:
            print(f"[GIT] endpoint.json updated on GitHub -> {url}", flush=True)
    except Exception as e:
        print(f"[GIT] Warning: Could not update endpoint.json on GitHub: {e}", flush=True)


def get_sync_state():
    try:
        req = urllib.request.Request(SYNC_FIRESTORE_URL)
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode())
            fields = data.get('fields', {})
            result = {}
            for k, v in fields.items():
                if v:
                    result[k] = list(v.values())[0]
            if 'master_id' not in result:
                result['master_id'] = ''
            if 'last_updated' not in result:
                result['last_updated'] = '1970-01-01T00:00:00Z'
            return result
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
    peer_url_field = f"peer_url_{DEVICE_ID}"
    
    data = {
        "fields": {
            telemetry_field: {"stringValue": telemetry_json}
        }
    }
    update_paths = f"updateMask.fieldPaths={telemetry_field}"
    
    if role == "master":
        data["fields"]["master_id"] = {"stringValue": DEVICE_ID}
        data["fields"]["last_updated"] = {"timestampValue": datetime.utcnow().isoformat() + "Z"}
        update_paths += "&updateMask.fieldPaths=master_id&updateMask.fieldPaths=last_updated"
    else:
        backup_updated_field = f"backup_updated_{DEVICE_ID}"
        data["fields"][backup_updated_field] = {"timestampValue": datetime.utcnow().isoformat() + "Z"}
        update_paths += f"&updateMask.fieldPaths={backup_updated_field}"
        
    if current_url:
        data["fields"][peer_url_field] = {"stringValue": current_url}
        update_paths += f"&updateMask.fieldPaths={peer_url_field}"
    
    url = SYNC_FIRESTORE_URL + "?" + update_paths
    try:
        req = urllib.request.Request(url, data=json.dumps(data).encode('utf-8'), method='PATCH')
        req.add_header('Content-Type', 'application/json')
        urllib.request.urlopen(req, timeout=5)
    except Exception as e:
        print(f"[!] Warning: Failed to update secondary Firebase: {e}")

def update_main_firebase(url):
    # Guard: Never overwrite main Firebase with ephemeral trycloudflare.com tunnels!
    # The NeTuArk Web Platform requires the permanent Cloudflare Pages Edge (https://phone-whisper-server.pages.dev).
    if "trycloudflare.com" in (url or ""):
        print(f"\n[*] Preserving permanent edge domain in MAIN Firebase (ignoring ephemeral tunnel: {url})\n", flush=True)
        return

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
        print(f"\n[+] Successfully updated MAIN Firebase with new URL: {url}\n", flush=True)
    except Exception as e:
        print(f"\n[-] Failed to update MAIN Firebase: {e}\n", flush=True)

import threading

def read_cloudflared_output(process):
    global current_url
    for line in iter(process.stdout.readline, ''):
        print(line, end='', flush=True)
        if current_url is None:
            match = re.search(r'(https://[a-zA-Z0-9-]+\.trycloudflare\.com)', line)
            if match:
                current_url = match.group(1)
                print(f"\n[+] LIVE TUNNEL: {current_url}\n", flush=True)
                # Register with Cloudflare Pages (permanent URL) immediately
                threading.Thread(target=register_with_pages, args=(current_url,), daemon=True).start()
                # Push endpoint.json to GitHub so Pages cold-starts can find the URL
                threading.Thread(target=push_endpoint_json, args=(current_url,), daemon=True).start()

def start_tunnel():
    global current_process, current_url
    if current_process is not None:
        return # Already running
        
    print("[*] Starting Cloudflare Tunnel...")
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

def _download_sync_file(peer_url, folder, f, local_path):
    print(f"[*] Built-in Sync: Downloading missing file {folder}/{f} from {peer_url}")
    candidate_urls = [
        f"{peer_url}/v1/storage/objects/{folder}/{f}",
        f"{peer_url}/media/{folder}/{f}",
        f"{peer_url}/v1/storage/objects/media/{f}"
    ]
    for dl_url in candidate_urls:
        try:
            dl_req = urllib.request.Request(dl_url, headers={"User-Agent": "NTA-Sync/2.0"})
            with urllib.request.urlopen(dl_req, timeout=30) as dl_res:
                if dl_res.status == 200:
                    tmp_p = local_path + ".tmp"
                    with open(tmp_p, 'wb') as out_f:
                        out_f.write(dl_res.read())
                    os.replace(tmp_p, local_path)
                    print(f"[+] Built-in Sync: Successfully saved {folder}/{f}")
                    return
        except Exception:
            continue

def sync_files_loop():
    BASE_DIR = '/sdcard/Download/NetuarkMedia'
    while True:
        try:
            state = get_sync_state() or {}
            
            # Symmetrical Mesh: Check both permanent peer and dynamic coordinator peers
            peer_candidates = ["https://phone-whisper-server.pages.dev"]
            for k, val in state.items():
                if k.startswith('peer_url_') and k != f'peer_url_{DEVICE_ID}':
                    if val and val.startswith('https://') and val not in peer_candidates:
                        peer_candidates.append(val.rstrip('/'))
                        
            for peer_url in peer_candidates:
                try:
                    list_req = urllib.request.Request(f"{peer_url}/api/sync/list", headers={"User-Agent": "NTA-Sync/2.0"})
                    with urllib.request.urlopen(list_req, timeout=10) as list_res:
                        peer_files = json.loads(list_res.read().decode())
                        
                    download_tasks = []
                    for folder, files in peer_files.items():
                        if not isinstance(files, dict):
                            continue
                        local_dir = os.path.join(BASE_DIR, folder)
                        os.makedirs(local_dir, exist_ok=True)
                        for f, size in files.items():
                            local_path = os.path.join(local_dir, f)
                            if not os.path.exists(local_path) or os.path.getsize(local_path) != size:
                                download_tasks.append((peer_url, folder, f, local_path))
                    
                    if download_tasks:
                        print(f"[*] Built-in Sync: Found {len(download_tasks)} missing files from {peer_url}. Downloading batch...")
                        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
                            futures = [executor.submit(_download_sync_file, *task) for task in download_tasks[:10]]
                            concurrent.futures.wait(futures)
                        print("[*] Built-in Sync: Batch download complete.")
                except Exception as peer_err:
                    pass
        except Exception as e:
            pass
        time.sleep(20)

def run_coordinator():
    global current_process, last_pushed_url
    print(f"Starting HA Tunnel Coordinator. Device ID: {DEVICE_ID}")
    
    # Start our own P2P tunnel unconditionally!
    start_tunnel()
    
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
            else:
                # I am already the Master. Let's check on the backups!
                for key, val in state.items():
                    if key.startswith('backup_updated_'):
                        backup_id = key.replace('backup_updated_', '')
                        backup_last_str = val.replace('Z', '')
                        if '.' in backup_last_str:
                            backup_last = datetime.strptime(backup_last_str, "%Y-%m-%dT%H:%M:%S.%f")
                        else:
                            backup_last = datetime.strptime(backup_last_str, "%Y-%m-%dT%H:%M:%S")
                        
                        backup_age = (now - backup_last).total_seconds()
                        if backup_age > TIMEOUT_THRESHOLD * 2:
                            print(f"[!] WARNING: Backup Server {backup_id} is OFFLINE! (No heartbeat for {int(backup_age)}s). Please start it!")
                        else:
                            print(f"[+] Backup Server {backup_id} is ONLINE (Ping: {int(backup_age)}s ago).")
            
            update_sync_state("master")
            if current_url and current_url != last_pushed_url:
                update_main_firebase(current_url)
                last_pushed_url = current_url
            
            # If process died unexpectedly, restart it
            if current_process and current_process.poll() is not None:
                print("Tunnel crashed. Restarting...")
                current_process = None
                start_tunnel()
                
        else:
            # I am backup
            print(f"[-] Standing by as BACKUP. Master {state['master_id']} is alive (Ping: {int(age_seconds)}s ago).")
            update_sync_state("backup")
            
            if current_process and current_process.poll() is not None:
                print("Backup Tunnel crashed. Restarting...")
                current_process = None
                start_tunnel()
            
        time.sleep(HEARTBEAT_INTERVAL)

if __name__ == "__main__":
    try:
        run_coordinator()
    except KeyboardInterrupt:
        print("\nExiting...")
        if current_process:
            current_process.terminate()
            subprocess.run(["pkill", "-f", "cloudflared"])
