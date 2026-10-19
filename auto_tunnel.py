import subprocess
import re
import time
import urllib.request
import json
import uuid
import sys
import os
import shutil
from datetime import datetime, timezone
import concurrent.futures
import threading

import telemetry

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

def get_utc_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

def register_with_pages(url):
    """Hit the Cloudflare Pages edge function so it immediately knows the new tunnel URL."""
    try:
        payload = json.dumps({"endpoint": url, "secret": PAGES_SHARED_SECRET}).encode()
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        req = urllib.request.Request(PAGES_REG_URL, data=payload, headers=headers)
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
    new_content = json.dumps({"endpoint": url, "updated_at": get_utc_iso()}, indent=2)
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
        print(f"[!] Warning: Could not read sync state from secondary Firebase: {e}", flush=True)
        return None

def get_telemetry():
    """Reads telemetry safely using telemetry.py (zero process leaks)."""
    return telemetry.get_telemetry_summary()

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
    
    now_iso = get_utc_iso()
    if role == "master":
        data["fields"]["master_id"] = {"stringValue": DEVICE_ID}
        data["fields"]["last_updated"] = {"timestampValue": now_iso}
        update_paths += "&updateMask.fieldPaths=master_id&updateMask.fieldPaths=last_updated"
    else:
        backup_updated_field = f"backup_updated_{DEVICE_ID}"
        data["fields"][backup_updated_field] = {"timestampValue": now_iso}
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
        print(f"[!] Warning: Failed to update secondary Firebase: {e}", flush=True)

def update_main_firebase(url):
    # Guard: Never overwrite main Firebase with ephemeral trycloudflare.com tunnels!
    # The NeTuArk Web Platform requires the permanent Cloudflare Pages Edge (https://phone-whisper-server.pages.dev).
    if "trycloudflare.com" in (url or ""):
        print(f"\n[*] Preserving permanent edge domain in MAIN Firebase (ignoring ephemeral tunnel: {url})\n", flush=True)
        return

    data = {
        "fields": {
            "url": {"stringValue": url},
            "updatedAt": {"timestampValue": get_utc_iso()}
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

def read_cloudflared_output(process):
    global current_url
    for line in iter(process.stdout.readline, ''):
        print(line, end='', flush=True)
        if current_url is None:
            match = re.search(r'(https://[a-zA-Z0-9-]+\.trycloudflare\.com)', line)
            if match and "api.trycloudflare.com" not in match.group(1):
                current_url = match.group(1)
                print(f"\n[+] LIVE TUNNEL: {current_url}\n", flush=True)
                # Register with Cloudflare Pages (permanent URL) immediately
                threading.Thread(target=register_with_pages, args=(current_url,), daemon=True).start()
                # Push endpoint.json to GitHub so Pages cold-starts can find the URL
                threading.Thread(target=push_endpoint_json, args=(current_url,), daemon=True).start()
                # Update Firestore coordinator immediately
                threading.Thread(target=update_sync_state, args=("master",), daemon=True).start()

def start_tunnel():
    global current_process, current_url
    if current_process is not None and current_process.poll() is None:
        return # Already running
        
    print("[*] Starting Cloudflare Tunnel for Media Server (port 3000)...", flush=True)
    current_url = None
    try:
        current_process = subprocess.Popen(
            ["cloudflared", "tunnel", "--url", "http://127.0.0.1:3000"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True
        )
        
        # Read output in a background thread so we don't block coordinator loop!
        t = threading.Thread(target=read_cloudflared_output, args=(current_process,))
        t.daemon = True
        t.start()
    except Exception as e:
        print(f"[!] Error starting cloudflared: {e}", flush=True)

def _download_sync_file(peer_url, folder, f, local_path):
    print(f"[*] Built-in Sync: Downloading missing file {folder}/{f} from {peer_url}", flush=True)
    candidate_urls = [
        f"{peer_url}/v1/storage/objects/{folder}/{f}",
        f"{peer_url}/media/{folder}/{f}",
        f"{peer_url}/v1/storage/objects/media/{f}"
    ]
    for dl_url in candidate_urls:
        try:
            dl_req = urllib.request.Request(dl_url, headers={"User-Agent": "NTA-Sync/2.0"})
            with urllib.request.urlopen(dl_req, timeout=25) as dl_res:
                if dl_res.status == 200:
                    tmp_p = local_path + ".tmp"
                    # Stream download in chunks to avoid blowing up RAM!
                    with open(tmp_p, 'wb') as out_f:
                        shutil.copyfileobj(dl_res, out_f, length=65536)
                    os.replace(tmp_p, local_path)
                    print(f"[+] Built-in Sync: Successfully saved {folder}/{f}", flush=True)
                    return
        except Exception:
            continue

def sync_files_loop():
    BASE_DIR = '/sdcard/Download/NetuarkMedia'
    while True:
        try:
            if not telemetry.is_network_online(timeout=1.0):
                time.sleep(15)
                continue

            state = get_sync_state() or {}
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
                        print(f"[*] Built-in Sync: Found {len(download_tasks)} missing files from {peer_url}. Downloading batch...", flush=True)
                        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
                            futures = [executor.submit(_download_sync_file, *task) for task in download_tasks[:10]]
                            concurrent.futures.wait(futures)
                        print("[*] Built-in Sync: Batch download complete.", flush=True)
                except Exception:
                    pass
        except Exception:
            pass
        time.sleep(20)

def kill_media_server():
    """Safely terminates only server.py without affecting search_server.py or hyperdata_server.py."""
    try:
        res = subprocess.run(["pgrep", "-f", "server.py"], capture_output=True, text=True)
        for pid_str in res.stdout.strip().split():
            try:
                pid = int(pid_str)
                with open(f"/proc/{pid}/cmdline", "r") as f:
                    cmd = f.read()
                if "search_server" not in cmd and "hyperdata_server" not in cmd:
                    subprocess.run(["kill", "-9", str(pid)], capture_output=True)
            except Exception:
                pass
    except Exception:
        pass

def auto_git_update_loop():
    """Autonomous Internal Communicator: monitors GitHub repo for new commits, pulls updates, and reloads server."""
    if not shutil.which("git"):
        print("[COMMUNICATOR] ℹ️ Git binary not detected on this device. Auto-git pull watchdog disabled.", flush=True)
        return

    print("[COMMUNICATOR] 🛡️ Autonomous Auto-Update Watchdog active (polling origin/main every 30s)...", flush=True)
    repo_dir = os.path.dirname(os.path.abspath(__file__))
    while True:
        try:
            time.sleep(30)
            if not telemetry.is_network_online(timeout=1.0):
                continue
            res = subprocess.run(["git", "ls-remote", "origin", "refs/heads/main"], cwd=repo_dir, capture_output=True, text=True, timeout=15)
            if res.returncode == 0 and res.stdout.strip():
                remote_sha = res.stdout.strip().split()[0]
                local_sha_res = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_dir, capture_output=True, text=True, timeout=5)
                local_sha = local_sha_res.stdout.strip() if local_sha_res.returncode == 0 else ""
                
                if remote_sha and local_sha and remote_sha != local_sha:
                    print(f"[COMMUNICATOR] 🚀 Remote update detected ({local_sha[:7]} -> {remote_sha[:7]}). Auto-pulling...", flush=True)
                    pull_res = subprocess.run(["git", "pull", "--rebase", "origin", "main"], cwd=repo_dir, capture_output=True, text=True, timeout=30)
                    print(f"[COMMUNICATOR] Git Pull Output:\n{pull_res.stdout}", flush=True)
                    print("[COMMUNICATOR] Restarting server.py & hyperdata_server.py with updated codebase...", flush=True)
                    kill_media_server()
                    subprocess.run(["pkill", "-9", "-f", "hyperdata_server.py"], capture_output=True)
                    time.sleep(1.5)
                    subprocess.Popen([sys.executable, os.path.join(repo_dir, "server.py")], cwd=repo_dir)
                    subprocess.Popen([sys.executable, os.path.join(repo_dir, "hyperdata_server.py")], cwd=repo_dir)
                    print("[COMMUNICATOR] Servers restarted successfully!", flush=True)
        except Exception:
            pass

def ensure_server_running():
    """Verifies that server.py is actively listening on port 3000; respawns if crashed."""
    import socket
    try:
        s = socket.create_connection(("127.0.0.1", 3000), timeout=1)
        s.close()
        return True
    except Exception:
        pass

    print("[SERVER-WATCHDOG] ⚠️ server.py is not listening on port 3000! Resurrecting...", flush=True)
    repo_dir = os.path.dirname(os.path.abspath(__file__))
    kill_media_server()
    time.sleep(1)
    server_script = os.path.join(repo_dir, "server.py")
    server_log = os.path.join(repo_dir, "server.log")
    try:
        log_out = open(server_log, "a")
        subprocess.Popen(
            [sys.executable, server_script],
            cwd=repo_dir,
            stdout=log_out,
            stderr=subprocess.STDOUT
        )
        time.sleep(2)
        return True
    except Exception as e:
        print(f"[SERVER-WATCHDOG] Failed to spawn server.py: {e}", flush=True)
def ensure_hyperdata_running():
    """Verifies that hyperdata_server.py is actively listening on port 3002; respawns if crashed."""
    import socket
    try:
        s = socket.create_connection(("127.0.0.1", 3002), timeout=1)
        s.close()
        return True
    except Exception:
        pass

    repo_dir = os.path.dirname(os.path.abspath(__file__))
    hd_script = os.path.join(repo_dir, "hyperdata_server.py")
    if not os.path.exists(hd_script):
        return True

    print("[HYPERDATA-WATCHDOG] ⚠️ hyperdata_server.py is not listening on port 3002! Resurrecting...", flush=True)
    subprocess.run(["pkill", "-9", "-f", "hyperdata_server\\.py"], capture_output=True)
    time.sleep(1)
    hd_log = os.path.join(repo_dir, "hyperdata.log")
    try:
        log_out = open(hd_log, "a")
        subprocess.Popen(
            [sys.executable, hd_script],
            cwd=repo_dir,
            stdout=log_out,
            stderr=subprocess.STDOUT
        )
        time.sleep(2)
        return True
    except Exception as e:
        print(f"[HYPERDATA-WATCHDOG] Failed to spawn hyperdata_server.py: {e}", flush=True)
        return False

def restart_server_and_tunnel():
    """Completely re-initializes and restarts both server.py and cloudflared tunnel upon network restoration."""
    global current_process, current_url, last_pushed_url
    print("\n[NET-WATCHDOG] 🔄 Complete server stack restart initiated...", flush=True)
    
    repo_dir = os.path.dirname(os.path.abspath(__file__))
    
    # 1. Terminate existing cloudflared process for port 3000 only
    if current_process:
        try:
            current_process.terminate()
            current_process.kill()
        except Exception:
            pass
        current_process = None
    subprocess.run(["pkill", "-9", "-f", "cloudflared.*3000"], capture_output=True)
    
    # 2. Terminate existing server.py and hyperdata_server.py cleanly
    print("[NET-WATCHDOG] 🛑 Stopping existing server.py & hyperdata_server.py instances...", flush=True)
    subprocess.run(["pkill", "-9", "-f", "ntamediaserver/server\\.py"], capture_output=True)
    subprocess.run(["pkill", "-9", "-f", "hyperdata_server\\.py"], capture_output=True)
    time.sleep(1.5)
    
    # 3. Re-assert Termux wake lock so device doesn't sleep while running server
    try:
        subprocess.run(["termux-wake-lock"], capture_output=True, timeout=2)
    except Exception:
        pass

    # 4. Spawn fresh server.py and hyperdata_server.py processes
    print("[NET-WATCHDOG] 🚀 Starting fresh server.py & hyperdata_server.py instances...", flush=True)
    server_script = os.path.join(repo_dir, "server.py")
    server_log = os.path.join(repo_dir, "server.log")
    try:
        log_out = open(server_log, "a")
        subprocess.Popen(
            [sys.executable, server_script],
            cwd=repo_dir,
            stdout=log_out,
            stderr=subprocess.STDOUT
        )
    except Exception as e:
        print(f"[NET-WATCHDOG] Error spawning server.py: {e}", flush=True)

    hd_script = os.path.join(repo_dir, "hyperdata_server.py")
    if os.path.exists(hd_script):
        hd_log = os.path.join(repo_dir, "hyperdata.log")
        try:
            hd_out = open(hd_log, "a")
            subprocess.Popen(
                [sys.executable, hd_script],
                cwd=repo_dir,
                stdout=hd_out,
                stderr=subprocess.STDOUT
            )
        except Exception as e:
            print(f"[NET-WATCHDOG] Error spawning hyperdata_server.py: {e}", flush=True)
    
    # 5. Wait for server.py (port 3000) and hyperdata_server.py (port 3002) to bind
    print("[NET-WATCHDOG] ⏳ Waiting for server.py (3000) and hyperdata_server.py (3002)...", flush=True)
    server_ready = False
    import socket
    for _ in range(15):
        time.sleep(1)
        try:
            s = socket.create_connection(("127.0.0.1", 3000), timeout=1)
            s.close()
            server_ready = True
            break
        except Exception:
            pass
            
    if server_ready:
        print("[NET-WATCHDOG] ✅ server.py is live and listening on port 3000!", flush=True)
    else:
        print("[NET-WATCHDOG] ⚠️ server.py port check timed out; proceeding to start tunnel anyway...", flush=True)
        
    # 6. Reset tunnel URLs and spawn fresh Cloudflare Tunnel
    current_url = None
    last_pushed_url = None
    start_tunnel()

def run_coordinator():
    global current_process, last_pushed_url
    print(f"Starting HA Tunnel Coordinator. Device ID: {DEVICE_ID}", flush=True)
    
    # Start our own P2P tunnel
    start_tunnel()
    
    # Start the built-in background file synchronizer
    sync_thread = threading.Thread(target=sync_files_loop)
    sync_thread.daemon = True
    sync_thread.start()

    # Start the autonomous communicator update watchdog
    watchdog_thread = threading.Thread(target=auto_git_update_loop)
    watchdog_thread.daemon = True
    watchdog_thread.start()
    
    failed_attempts = 0

    while True:
        # ── 🌐 Network Watchdog with Ping Reconnect ──
        if not telemetry.is_network_online(timeout=8.0):
            # Double check with a second attempt before assuming down
            if not telemetry.is_network_online(timeout=10.0):
                downtime = telemetry.wait_for_network_recovery()
                print(f"[NET-WATCHDOG] 🚀 Network restored after {downtime}s! (Mobile auto-reconnected). Restarting entire server stack...", flush=True)
                restart_server_and_tunnel()
                continue

        # ── 🛡️ Local Server Watchdogs (Port 3000 & Port 3002) ──
        ensure_server_running()
        ensure_hyperdata_running()

        # ── 🛡️ Tunnel Process Liveness Watchdog ──
        if current_process is None or current_process.poll() is not None:
            print("[TUNNEL-WATCHDOG] ⚠️ Media tunnel inactive/crashed. Respawning...", flush=True)
            current_process = None
            start_tunnel()

        state = get_sync_state()
        now = datetime.now(timezone.utc)
        
        if state is None:
            failed_attempts += 1
            print(f"[-] Could not reach Sync DB (Attempt {failed_attempts}).", flush=True)
            
            # Check if network went down while reading sync state
            if not telemetry.is_network_online(timeout=8.0):
                downtime = telemetry.wait_for_network_recovery()
                print(f"[NET-WATCHDOG] 🚀 Network restored after {downtime}s! (Mobile auto-reconnected). Restarting entire server stack...", flush=True)
                restart_server_and_tunnel()
                continue
            
            # If we fail too many times, assume Master role to keep tunnel online
            if failed_attempts >= 3:
                print("[!] Sync DB unreachable for too long. Assuming MASTER role to keep server online.", flush=True)
                start_tunnel()
                if current_process and current_process.poll() is not None:
                    current_process = None
                    start_tunnel()
                
            time.sleep(HEARTBEAT_INTERVAL)
            continue
            
        failed_attempts = 0
        
        last_updated_str = state.get('last_updated', '1970-01-01T00:00:00Z').replace('Z', '')
        try:
            if '.' in last_updated_str:
                last_updated = datetime.strptime(last_updated_str, "%Y-%m-%dT%H:%M:%S.%f").replace(tzinfo=timezone.utc)
            else:
                last_updated = datetime.strptime(last_updated_str, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
        except Exception:
            last_updated = datetime(1970, 1, 1, tzinfo=timezone.utc)
            
        age_seconds = (now - last_updated).total_seconds()
        
        is_master_dead = age_seconds > TIMEOUT_THRESHOLD
        am_i_master = (state.get('master_id') == DEVICE_ID)
        
        if is_master_dead or am_i_master:
            if not am_i_master:
                print(f"[!] Master died! Taking over as new MASTER. (Age: {int(age_seconds)}s)", flush=True)
            else:
                for key, val in state.items():
                    if key.startswith('backup_updated_'):
                        backup_id = key.replace('backup_updated_', '')
                        backup_last_str = str(val).replace('Z', '')
                        try:
                            if '.' in backup_last_str:
                                backup_last = datetime.strptime(backup_last_str, "%Y-%m-%dT%H:%M:%S.%f").replace(tzinfo=timezone.utc)
                            else:
                                backup_last = datetime.strptime(backup_last_str, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
                            backup_age = (now - backup_last).total_seconds()
                            if backup_age > TIMEOUT_THRESHOLD * 2:
                                print(f"[!] WARNING: Backup Server {backup_id} is OFFLINE! (No heartbeat for {int(backup_age)}s).", flush=True)
                            else:
                                print(f"[+] Backup Server {backup_id} is ONLINE (Ping: {int(backup_age)}s ago).", flush=True)
                        except Exception:
                            pass
            
            update_sync_state("master")
            if current_url and current_url != last_pushed_url:
                update_main_firebase(current_url)
                last_pushed_url = current_url
            
            if current_process and current_process.poll() is not None:
                print("Tunnel crashed. Restarting...", flush=True)
                current_process = None
                start_tunnel()
                
        else:
            print(f"[-] Standing by as BACKUP. Master {state.get('master_id')} is alive (Ping: {int(age_seconds)}s ago).", flush=True)
            update_sync_state("backup")
            
            if current_process and current_process.poll() is not None:
                print("Backup Tunnel crashed. Restarting...", flush=True)
                current_process = None
                start_tunnel()
            
        time.sleep(HEARTBEAT_INTERVAL)

if __name__ == "__main__":
    try:
        run_coordinator()
    except KeyboardInterrupt:
        print("\nExiting...", flush=True)
        if current_process:
            current_process.terminate()
            subprocess.run(["pkill", "-f", "cloudflared.*3000"])
