import os
import time
import json
import glob
import shutil
import socket
import subprocess
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

def get_cpu_info():
    cores = os.cpu_count() or 8
    info = {
        "usage_percent": 0.0,
        "cores": cores,
        "temperature_c": 35.0
    }
    
    # Read CPU usage from top -n 1 -b (fast and reliable on Android/Termux)
    try:
        res = subprocess.run(["top", "-n", "1", "-b"], capture_output=True, text=True, timeout=2)
        if res.returncode == 0:
            for line in res.stdout.splitlines():
                if "cpu" in line.lower() and "idle" in line.lower():
                    import re
                    m_cpu = re.search(r'(\d+)%cpu', line)
                    m_idle = re.search(r'(\d+)%idle', line)
                    if m_cpu and m_idle:
                        total_cpu = int(m_cpu.group(1))
                        idle = int(m_idle.group(1))
                        used = total_cpu - idle
                        pct = round((used / total_cpu) * 100, 1) if total_cpu > 0 else 0.0
                        info["usage_percent"] = max(0.0, min(100.0, pct))
                        break
    except Exception:
        pass

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

def is_network_online(timeout=1.5):
    for host in [("1.1.1.1", 53), ("8.8.8.8", 53), ("1.0.0.1", 53)]:
        try:
            s = socket.create_connection(host, timeout=timeout)
            s.close()
            return True
        except Exception:
            continue
    try:
        res = subprocess.run(["ping", "-c", "1", "-W", "1", "1.1.1.1"], capture_output=True, timeout=2)
        return res.returncode == 0
    except Exception:
        pass
    return False

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
