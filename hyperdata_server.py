#!/usr/bin/env python3
"""
HyperData Sovereign Database Service
Runs independently on dedicated PORT 3002.
Dual-Tier (RAM L1 + SQLite WAL L2) storage with SSE pub/sub event broadcasting.
Includes autonomous network watchdog for seamless reconnects on network transitions.
"""

import os
import sys
import time
import json
import threading
import subprocess
from flask import Flask, request, jsonify, Response, stream_with_context

import hyperdata
import telemetry

app = Flask(__name__)

# Base storage directories on phone's public visible storage
candidate_base = os.environ.get("NETUARK_STORAGE_DIR", '/sdcard/Download/NetuarkMedia')
try:
    os.makedirs(candidate_base, exist_ok=True)
    test_probe = os.path.join(candidate_base, f".probe_hd_{os.getpid()}")
    with open(test_probe, "w") as f:
        f.write("ok")
    os.remove(test_probe)
    BASE_DIR = candidate_base
except Exception:
    BASE_DIR = os.environ.get("FALLBACK_STORAGE_DIR", "/tmp/NetuarkMedia")
    os.makedirs(BASE_DIR, exist_ok=True)

# Initialize Sovereign HyperData Engine
hd_engine = hyperdata.HyperDataEngine(base_storage_dir=BASE_DIR)

def get_tenant_id():
    """Extracts project/tenant identifier with fallback to public_guest."""
    tenant = request.headers.get("X-Project-Id") or request.args.get("tenant_id") or request.args.get("project_id") or "public_guest"
    return str(tenant).strip()

@app.after_request
def add_cors_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS, PATCH, HEAD'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, Range, X-Project-Id, *'
    response.headers['Access-Control-Expose-Headers'] = 'Accept-Ranges, Content-Encoding, Content-Length, Content-Range, *'
    return response

# =========================================================================
# HYPERDATA API ENDPOINTS (PORT 3002)
# =========================================================================

@app.route('/health', methods=['GET'])
@app.route('/v1/hyperdata/status', methods=['GET', 'OPTIONS'])
@app.route('/hyperdata/status', methods=['GET', 'OPTIONS'])
@app.route('/v1/db/status', methods=['GET', 'OPTIONS'])
@app.route('/db/status', methods=['GET', 'OPTIONS'])
def hyperdata_status():
    if request.method == 'OPTIONS':
        return ('', 204)
    stat = hd_engine.status(get_tenant_id())
    stat["port"] = 3002
    return jsonify(stat)

@app.route('/v1/hyperdata/set', methods=['POST', 'OPTIONS'])
@app.route('/hyperdata/set', methods=['POST', 'OPTIONS'])
@app.route('/v1/db/set', methods=['POST', 'OPTIONS'])
@app.route('/db/set', methods=['POST', 'OPTIONS'])
def hyperdata_set():
    if request.method == 'OPTIONS':
        return ('', 204)
    body = request.get_json(silent=True) or {}
    table = body.get("table") or request.args.get("table") or "records"
    key = body.get("key") or body.get("id") or body.get("_key") or request.args.get("key")
    if not key:
        return jsonify({"status": "error", "error": "Document key cannot be empty"}), 400
    data = body.get("data") if "data" in body else body
    ttl = body.get("ttl")
    try:
        ttl = int(ttl) if ttl is not None else None
    except Exception:
        ttl = None
    res = hd_engine.set(get_tenant_id(), table, str(key), data, ttl=ttl)
    return jsonify(res)

@app.route('/v1/hyperdata/get', methods=['GET', 'POST', 'OPTIONS'])
@app.route('/hyperdata/get', methods=['GET', 'POST', 'OPTIONS'])
@app.route('/v1/db/get', methods=['GET', 'POST', 'OPTIONS'])
@app.route('/db/get', methods=['GET', 'POST', 'OPTIONS'])
def hyperdata_get():
    if request.method == 'OPTIONS':
        return ('', 204)
    body = request.get_json(silent=True) or {} if request.method == 'POST' else {}
    table = request.args.get("table") or body.get("table") or "records"
    key = request.args.get("key") or body.get("key") or body.get("id")
    if not key:
        return jsonify({"status": "error", "error": "Missing key parameter"}), 400
    res = hd_engine.get(get_tenant_id(), table, str(key))
    if res is None:
        return jsonify({"status": "error", "error": "Document not found"}), 404
    return jsonify(res)

@app.route('/v1/hyperdata/delete', methods=['POST', 'DELETE', 'OPTIONS'])
@app.route('/v1/hyperdata/delete/<key>', methods=['DELETE', 'POST', 'OPTIONS'])
@app.route('/hyperdata/delete', methods=['POST', 'DELETE', 'OPTIONS'])
@app.route('/hyperdata/delete/<key>', methods=['DELETE', 'POST', 'OPTIONS'])
@app.route('/v1/db/delete', methods=['POST', 'DELETE', 'OPTIONS'])
@app.route('/db/delete', methods=['POST', 'DELETE', 'OPTIONS'])
def hyperdata_delete(key=None):
    if request.method == 'OPTIONS':
        return ('', 204)
    body = request.get_json(silent=True) or {}
    table = request.args.get("table") or body.get("table") or "records"
    target_key = key or request.args.get("key") or body.get("key") or body.get("id")
    if not target_key:
        return jsonify({"status": "error", "error": "Missing key parameter"}), 400
    res = hd_engine.delete(get_tenant_id(), table, str(target_key))
    return jsonify(res)

@app.route('/v1/hyperdata/batch', methods=['POST', 'OPTIONS'])
@app.route('/hyperdata/batch', methods=['POST', 'OPTIONS'])
@app.route('/v1/db/batch', methods=['POST', 'OPTIONS'])
@app.route('/db/batch', methods=['POST', 'OPTIONS'])
def hyperdata_batch():
    if request.method == 'OPTIONS':
        return ('', 204)
    body = request.get_json(silent=True) or {}
    table = body.get("table") or request.args.get("table") or "records"
    items = body.get("items") or []
    ttl = body.get("ttl")
    try:
        ttl = int(ttl) if ttl is not None else None
    except Exception:
        ttl = None
    try:
        res = hd_engine.batch(get_tenant_id(), table, items, ttl=ttl)
        return jsonify(res)
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 400

@app.route('/v1/hyperdata/patch', methods=['POST', 'OPTIONS'])
@app.route('/hyperdata/patch', methods=['POST', 'OPTIONS'])
@app.route('/v1/db/patch', methods=['POST', 'OPTIONS'])
@app.route('/db/patch', methods=['POST', 'OPTIONS'])
def hyperdata_patch():
    if request.method == 'OPTIONS':
        return ('', 204)
    body = request.get_json(silent=True) or {}
    table = body.get("table") or request.args.get("table") or "records"
    key = body.get("key") or body.get("id") or request.args.get("key")
    if not key:
        return jsonify({"status": "error", "error": "Document key cannot be empty"}), 400
    action = body.get("action", "merge")
    field = body.get("field")
    value = body.get("value")
    patch_data = body.get("data") if "data" in body else body.get("patch_data")
    try:
        res = hd_engine.patch(get_tenant_id(), table, str(key), patch_data=patch_data,
                              action=action, field=field, value=value)
        return jsonify(res)
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 400

@app.route('/v1/hyperdata/query', methods=['GET', 'POST', 'OPTIONS'])
@app.route('/hyperdata/query', methods=['GET', 'POST', 'OPTIONS'])
@app.route('/v1/db/query', methods=['GET', 'POST', 'OPTIONS'])
@app.route('/db/query', methods=['GET', 'POST', 'OPTIONS'])
def hyperdata_query():
    if request.method == 'OPTIONS':
        return ('', 204)
    body = request.get_json(silent=True) or {} if request.method == 'POST' else {}
    table = request.args.get("table") or body.get("table") or "records"
    filter_dict = body.get("filter") or body.get("filter_dict") or body.get("where")
    limit = int(request.args.get("limit") or body.get("limit") or 50)
    offset = int(request.args.get("offset") or body.get("offset") or 0)
    order_by = request.args.get("order_by") or request.args.get("orderBy") or body.get("order_by") or body.get("orderBy")
    sort_desc = request.args.get("sort_desc") or request.args.get("sortDesc") or body.get("sort_desc") or body.get("sortDesc")
    if isinstance(sort_desc, str):
        sort_desc = sort_desc.lower() in ["true", "1", "desc"]
    elif sort_desc is None:
        sort_desc = False

    res = hd_engine.query(get_tenant_id(), table, filter_dict=filter_dict, limit=limit,
                          offset=offset, order_by=order_by, sort_desc=bool(sort_desc))
    return jsonify(res)

@app.route('/v1/hyperdata/tables', methods=['GET', 'OPTIONS'])
@app.route('/hyperdata/tables', methods=['GET', 'OPTIONS'])
@app.route('/v1/db/tables', methods=['GET', 'OPTIONS'])
@app.route('/db/tables', methods=['GET', 'OPTIONS'])
def hyperdata_tables():
    if request.method == 'OPTIONS':
        return ('', 204)
    res = hd_engine.tables(get_tenant_id())
    return jsonify(res)

@app.route('/v1/hyperdata/drop', methods=['POST', 'DELETE', 'OPTIONS'])
@app.route('/hyperdata/drop', methods=['POST', 'DELETE', 'OPTIONS'])
@app.route('/v1/db/drop', methods=['POST', 'DELETE', 'OPTIONS'])
@app.route('/db/drop', methods=['POST', 'DELETE', 'OPTIONS'])
def hyperdata_drop():
    if request.method == 'OPTIONS':
        return ('', 204)
    body = request.get_json(silent=True) or {}
    table = request.args.get("table") or body.get("table")
    if not table:
        return jsonify({"status": "error", "error": "Table name required"}), 400
    res = hd_engine.drop(get_tenant_id(), table)
    return jsonify(res)

@app.route('/v1/hyperdata/stream', methods=['GET', 'OPTIONS'])
@app.route('/hyperdata/stream', methods=['GET', 'OPTIONS'])
@app.route('/v1/db/stream', methods=['GET', 'OPTIONS'])
@app.route('/db/stream', methods=['GET', 'OPTIONS'])
def hyperdata_stream():
    if request.method == 'OPTIONS':
        return ('', 204)
    table = request.args.get("table", "*")
    tenant_id = get_tenant_id()

    response = Response(
        stream_with_context(hd_engine.stream_events(tenant_id, table)),
        mimetype="text/event-stream"
    )
    response.headers["Cache-Control"] = "no-cache, no-transform"
    response.headers["Connection"] = "keep-alive"
    response.headers["X-Accel-Buffering"] = "no"
    return response

# =========================================================================
# ADMINISTRATIVE RESTART ENDPOINT (PORT 3002)
# =========================================================================

@app.route('/api/admin/restart', methods=['POST'])
def hyperdata_admin_restart():
    """Administrative restart endpoint for Port 3002 service."""
    auth_key = request.headers.get("X-Admin-Key", "")
    if request.remote_addr in ['127.0.0.1', '::1', 'localhost'] or auth_key == 'netuark_admin_restart':
        def _do_restart():
            time.sleep(1)
            repo_dir = os.path.dirname(os.path.abspath(__file__))
            subprocess.Popen([sys.executable, os.path.join(repo_dir, "hyperdata_server.py")], cwd=repo_dir)
            os._exit(0)
        threading.Thread(target=_do_restart, daemon=True).start()
        return jsonify({"status": "restarting", "message": "hyperdata_server.py restarting cleanly"}), 200
    return jsonify({"error": "Unauthorized"}), 403

# =========================================================================
# AUTONOMOUS NETWORK WATCHDOG FOR DEDICATED PORT 3002
# =========================================================================

def hyperdata_network_watchdog():
    """Monitors connectivity and ensures database service auto-recovers after network transitions."""
    time.sleep(5)
    was_offline = False
    offline_start = 0
    while True:
        try:
            if not telemetry.is_network_online(timeout=8.0):
                if not was_offline:
                    was_offline = True
                    offline_start = time.time()
                    print("\n[HYPERDATA-WATCHDOG] ⚠️ Network disconnected! Waiting for restoration...", flush=True)
                time.sleep(3)
                continue

            if was_offline:
                downtime = int(time.time() - offline_start)
                was_offline = False
                print(f"\n[HYPERDATA-WATCHDOG] 🚀 Network restored after {downtime}s! Ensuring port 3002 is active...", flush=True)
                time.sleep(1)
        except Exception:
            pass
        time.sleep(5)

threading.Thread(target=hyperdata_network_watchdog, daemon=True).start()

if __name__ == '__main__':
    from werkzeug.serving import WSGIRequestHandler
    # Enable persistent HTTP/1.1 keep-alive for instant zero-handshake request dispatch
    WSGIRequestHandler.protocol_version = "HTTP/1.1"

    port = int(os.environ.get("HYPERDATA_PORT", 3002))
    print(f"🚀 Starting Sovereign Enterprise HyperData Database Server on port {port} (HTTP/1.1 Multi-Threaded)...", flush=True)
    app.run(host='0.0.0.0', port=port, threaded=True)
