import os
import time
import json
import glob
import shutil
import socket
import subprocess
import threading
from datetime import datetime, timezone

BASE_DIR = '/sdcard/Download/NetuarkMedia'

_folder_stats_cache = {}
_folder_stats_time = 0

def get_folder_stats():
    global _folder_stats_cache, _folder_stats_time
    now = time.time()
    if now - _folder_stats_time < 10 and _folder_stats_cache:
        return _folder_stats_cache

    stats = {}
    if os.path.exists(BASE_DIR):
        try:
            for entry in os.scandir(BASE_DIR):
                if entry.is_dir():
                    count = 0
                    total_bytes = 0
                    for f in os.scandir(entry.path):
                        if f.is_file():
                            count += 1
                            total_bytes += f.stat().st_size
                    stats[entry.name] = {
                        "count": count,
                        "size_mb": round(total_bytes / (1024 * 1024), 2)
                    }
        except Exception:
            pass
    _folder_stats_cache = stats
    _folder_stats_time = now
    return stats

def get_battery_info():
    info = {
        "level": 100,
        "status": "Active (USB)",
        "temperature_c": 33.0,
        "voltage_mv": 4200,
        "health": "Good",
        "is_charging": True
    }
    
    # 1. Read /sdcard/Download/battery.txt (from dumpsys battery)
    bat_file = "/sdcard/Download/battery.txt"
    if os.path.exists(bat_file):
        try:
            with open(bat_file, "r") as f:
                content = f.read()
            for line in content.splitlines():
                line = line.strip()
                if line.startswith("level:"):
                    info["level"] = int(line.split(":")[1].strip())
                elif line.startswith("temperature:"):
                    raw_t = int(line.split(":")[1].strip())
                    info["temperature_c"] = round(raw_t / 10.0, 1)
                elif line.startswith("voltage:"):
                    info["voltage_mv"] = int(line.split(":")[1].strip())
                elif line.startswith("status:"):
                    st = int(line.split(":")[1].strip())
                    st_map = {1: "Unknown", 2: "Charging", 3: "Discharging", 4: "Not Charging", 5: "Full"}
                    info["status"] = st_map.get(st, "Active")
                elif "USB powered: true" in line or "AC powered: true" in line:
                    info["is_charging"] = True
                    if info["status"] not in ["Full", "Charging"]:
                        info["status"] = "Charging (USB)"
        except Exception:
            pass

    # 2. Check thermal zone for battery temp if needed
    if info["temperature_c"] == 33.0:
        for p in glob.glob('/sys/class/thermal/thermal_zone*/type'):
            try:
                t_type = open(p).read().strip().lower()
                if 'batt' in t_type or 'bms' in t_type:
                    temp_p = p.replace('type', 'temp')
                    raw_val = int(open(temp_p).read().strip())
                    c = raw_val / 1000.0 if raw_val > 1000 else (raw_val / 10.0 if raw_val > 100 else float(raw_val))
                    info["temperature_c"] = round(c, 1)
                    break
            except Exception:
                pass

    return info

_cpu_usage_lock = threading.Lock()
_current_cpu_usage = 0.0
_last_sample_time = 0.0
_prev_proc_ticks = {}
_clk_tck = 100
try:
    _clk_tck = os.sysconf(os.sysconf_names.get('SC_CLK_TCK', 100)) or 100
except Exception:
    _clk_tck = 100

def _read_proc_ticks():
    """Reads utime + stime from /proc/[pid]/stat for all accessible processes."""
    ticks_map = {}
    try:
        for pid in os.listdir('/proc'):
            if pid.isdigit():
                try:
                    with open(f'/proc/{pid}/stat', 'r') as f:
                        parts = f.read().split()
                        if len(parts) >= 15:
                            ticks_map[pid] = int(parts[13]) + int(parts[14])
                except (FileNotFoundError, PermissionError, ProcessLookupError, IndexError, ValueError):
                    continue
    except Exception:
        pass
    return ticks_map

def _sample_cpu_percent():
    """Calculates true CPU percent across cluster processes over elapsed delta window."""
    global _current_cpu_usage, _last_sample_time, _prev_proc_ticks
    now = time.time()
    curr_ticks = _read_proc_ticks()
    
    if _prev_proc_ticks and _last_sample_time > 0:
        dt = now - _last_sample_time
        if dt > 0.3:
            total_delta = 0
            for pid, ticks in curr_ticks.items():
                if pid in _prev_proc_ticks:
                    d = ticks - _prev_proc_ticks[pid]
                    if d > 0:
                        total_delta += d
                else:
                    total_delta += ticks
            
            cores = os.cpu_count() or 8
            cpu_seconds = total_delta / _clk_tck
            usage_pct = (cpu_seconds / (dt * cores)) * 100.0
            
            with _cpu_usage_lock:
                _current_cpu_usage = round(max(0.5, min(100.0, usage_pct)), 1)
                _last_sample_time = now
                _prev_proc_ticks = curr_ticks
            return _current_cpu_usage
            
    with _cpu_usage_lock:
        _last_sample_time = now
        _prev_proc_ticks = curr_ticks
        if _current_cpu_usage == 0.0:
            _current_cpu_usage = 1.8  # Initial active baseline before 2s delta
    return _current_cpu_usage

def _cpu_monitor_daemon():
    """Background sampling daemon that updates CPU usage every 2 seconds without blocking requests."""
    _sample_cpu_percent()
    while True:
        try:
            time.sleep(2.0)
            _sample_cpu_percent()
        except Exception:
            time.sleep(2.0)

_cpu_thread = threading.Thread(target=_cpu_monitor_daemon, daemon=True)
_cpu_thread.start()

def get_cpu_info():
    cores = os.cpu_count() or 8
    
    # 1. Read precomputed accurate CPU usage from background sampler
    with _cpu_usage_lock:
        usage = _current_cpu_usage
        
    # If daemon hasn't completed a cycle or is 0.0, compute immediately
    if usage <= 0.0:
        usage = _sample_cpu_percent()
        
    # Secondary fallback: if ticks couldn't be read from /proc, parse ps -eo pcpu
    if usage <= 0.0:
        try:
            res = subprocess.run(["ps", "-eo", "pcpu"], capture_output=True, text=True, timeout=1)
            if res.returncode == 0:
                vals = []
                for line in res.stdout.splitlines()[1:]:
                    try:
                        v = float(line.strip())
                        if 0 <= v <= 100:
                            vals.append(v)
                    except ValueError:
                        pass
                if vals:
                    usage = round(max(0.8, min(100.0, sum(vals) / cores)), 1)
        except Exception:
            pass

    if usage <= 0.0:
        usage = 1.5

    info = {
        "usage_percent": round(usage, 1),
        "cores": cores,
        "temperature_c": 35.0
    }

    # Read CPU thermal zone temperature
    temps = []
    for p in glob.glob('/sys/class/thermal/thermal_zone*/type'):
        try:
            t_type = open(p).read().strip().lower()
            if any(k in t_type for k in ['cpu', 'tsens', 'soc']):
                temp_p = p.replace('type', 'temp')
                raw_val = int(open(temp_p).read().strip())
                c = raw_val / 1000.0 if raw_val > 1000 else (raw_val / 10.0 if raw_val > 100 else float(raw_val))
                temps.append(c)
        except Exception:
            pass
    if temps:
        info["temperature_c"] = round(sum(temps) / len(temps), 1)

    return info

def get_memory_info():
    info = {
        "total_mb": 3545,
        "used_mb": 0,
        "free_mb": 3545,
        "used_percent": 0.0,
        "buffers_cached_mb": 0
    }
    try:
        mem = {}
        with open("/proc/meminfo", "r") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 2:
                    mem[parts[0].rstrip(":")] = int(parts[1])
        total_kb = mem.get("MemTotal", 0)
        free_kb = mem.get("MemFree", 0)
        buffers_kb = mem.get("Buffers", 0)
        cached_kb = mem.get("Cached", 0)
        avail_kb = mem.get("MemAvailable", free_kb + buffers_kb + cached_kb)
        
        total_mb = total_kb // 1024
        avail_mb = avail_kb // 1024
        used_mb = max(0, total_mb - avail_mb)
        
        info["total_mb"] = total_mb
        info["used_mb"] = used_mb
        info["free_mb"] = avail_mb
        info["buffers_cached_mb"] = (buffers_kb + cached_kb) // 1024
        info["used_percent"] = round((used_mb / total_mb) * 100, 1) if total_mb > 0 else 0.0
    except Exception:
        pass
    return info

def get_storage_info():
    info = {
        "total_gb": 0.0,
        "used_gb": 0.0,
        "free_gb": 0.0,
        "used_percent": 0.0,
        "folders": get_folder_stats()
    }
    try:
        check_path = BASE_DIR if os.path.exists(BASE_DIR) else "/sdcard"
        stat = os.statvfs(check_path)
        total = (stat.f_blocks * stat.f_frsize) / (1024**3)
        free = (stat.f_bavail * stat.f_frsize) / (1024**3)
        used = total - free
        info["total_gb"] = round(total, 1)
        info["free_gb"] = round(free, 1)
        info["used_gb"] = round(used, 1)
        info["used_percent"] = round((used / total) * 100, 1) if total > 0 else 0.0
    except Exception:
        pass
    return info

def is_network_online(timeout=8.0):
    for host in [("1.1.1.1", 53), ("8.8.8.8", 53), ("1.0.0.1", 53), ("8.8.4.4", 53)]:
        try:
            s = socket.create_connection(host, timeout=timeout)
            s.close()
            return True
        except Exception:
            continue
    try:
        res = subprocess.run(["ping", "-c", "1", "-W", "6", "1.1.1.1"], capture_output=True, timeout=8)
        if res.returncode == 0:
            return True
    except Exception:
        pass
    try:
        res = subprocess.run(["ping", "-c", "1", "-W", "6", "8.8.8.8"], capture_output=True, timeout=8)
        return res.returncode == 0
    except Exception:
        pass
    return False

def wait_for_network_recovery():
    """Continuously pings 1.1.1.1 and 8.8.8.8 until internet is confirmed restored."""
    offline_start = time.time()
    ping_cycle = 0
    consecutive_success = 0
    print("\n[NET-WATCHDOG] ⚠️ Network disconnected (Router off / Wi-Fi lost).", flush=True)
    print("[NET-WATCHDOG] ⏳ Starting continuous ping loop (1.1.1.1 / 8.8.8.8) waiting for reconnection...", flush=True)
    
    while consecutive_success < 2:
        ping_cycle += 1
        if is_network_online(timeout=2.0):
            consecutive_success += 1
            time.sleep(1)
        else:
            consecutive_success = 0
            if ping_cycle % 5 == 1:
                duration = int(time.time() - offline_start)
                print(f"[NET-WATCHDOG] ⏳ Pinging continuously... Offline for {duration}s (attempt #{ping_cycle})", flush=True)
            time.sleep(2)
            
    total_downtime = int(time.time() - offline_start)
    print(f"[NET-WATCHDOG] 🚀 NETWORK RESTORED! (Downtime: {total_downtime}s). Internet connection confirmed stable.", flush=True)
    return total_downtime

def get_device_info():
    model = "Lenovo L38012"
    brand = "Lenovo"
    arch = "aarch64"
    try:
        res = subprocess.run(["getprop", "ro.product.model"], capture_output=True, text=True, timeout=1)
        if res.stdout.strip():
            model = res.stdout.strip()
        res_b = subprocess.run(["getprop", "ro.product.brand"], capture_output=True, text=True, timeout=1)
        if res_b.stdout.strip():
            brand = res_b.stdout.strip()
    except Exception:
        pass
    
    uptime_sec = 0
    try:
        with open("/proc/uptime", "r") as f:
            uptime_sec = int(float(f.read().split()[0]))
    except Exception:
        pass

    full_model = model if brand.lower() in model.lower() else f"{brand} {model}"
    return {
        "model": full_model,
        "brand": brand,
        "arch": arch,
        "uptime_sec": uptime_sec
    }

def is_process_running(proc_name):
    """Checks if a process is running without spawning external binaries."""
    try:
        for pid in os.listdir('/proc'):
            if pid.isdigit():
                try:
                    with open(f'/proc/{pid}/cmdline', 'rb') as f:
                        cmd = f.read().replace(b'\x00', b' ').decode('utf-8', errors='ignore')
                        if proc_name in cmd:
                            return True
                except (FileNotFoundError, PermissionError, ProcessLookupError):
                    continue
    except Exception:
        pass
    return False

def get_telemetry_summary():
    """Returns compact JSON string formatted for Firestore coordinator node registry."""
    mem = get_memory_info()
    bat = get_battery_info()
    stor = get_storage_info()
    cpu = get_cpu_info()
    dev = get_device_info()
    return json.dumps({
        "battery": f"{bat['level']}% ({bat['status']}, {bat['temperature_c']}°C)",
        "network": "Online (Active)" if is_network_online(0.8) else "Offline (Pinging)",
        "ram": f"{mem['used_mb']}MB / {mem['total_mb']}MB Used ({mem['used_percent']}%)",
        "storage": f"{stor['used_gb']}G / {stor['total_gb']}G Used ({stor['used_percent']}%)",
        "cpu": f"{cpu['usage_percent']}% ({cpu['cores']} Cores, {cpu['temperature_c']}°C)",
        "device": dev["model"]
    })

def get_full_telemetry(device_id="", current_url=""):
    """Returns complete telemetry dictionary for the /api/telemetry endpoint."""
    return {
        "status": "ONLINE" if is_network_online(0.8) else "RECONNECTING",
        "node": "ntamediaserver",
        "device_id": device_id,
        "timestamp": time.time(),
        "device": get_device_info(),
        "battery": get_battery_info(),
        "cpu": get_cpu_info(),
        "memory": get_memory_info(),
        "storage": get_storage_info(),
        "network": {
            "online": is_network_online(0.8),
            "active_tunnel": current_url or "",
            "edge_gateway": "https://ntamediaserver.pages.dev"
        }
    }
