#!/bin/bash
# ==============================================================================
# 🛰️ NETUARK SOVEREIGN DUAL-CLUSTER SUPERVISOR
# Orchestrates:
#   1. Sovereign Media Server (Port 3000) + Cloudflare Tunnel A (ntamediaserver.pages.dev)
#   2. Headless Chromium Sandbox (Port 9222 CDP)
#   3. Sovereign WebSearch API (Port 3001) + Cloudflare Tunnel B (ntawebsearch.pages.dev)
# Designed for Termux aarch64 on Lenovo L38012 (4GB RAM)
# ==============================================================================

termux-wake-lock 2>/dev/null || true
pkill -9 -f termux-api 2>/dev/null || true

# Clean existing instances
pkill -f server.py 2>/dev/null || true
pkill -f auto_tunnel.py 2>/dev/null || true
pkill -f search_server.py 2>/dev/null || true
pkill -f search_tunnel.py 2>/dev/null || true
pkill -f 'chromium.*remote-debugging-port' 2>/dev/null || true
pkill -f cloudflared 2>/dev/null || true
sleep 1

# Resolve directories
MEDIA_DIR=""
SEARCH_DIR=""

if [ -d "$HOME/ntamediaserver" ]; then
    MEDIA_DIR="$HOME/ntamediaserver"
elif [ -d "/sdcard/Download/ntamediaserver" ]; then
    MEDIA_DIR="/sdcard/Download/ntamediaserver"
fi

if [ -d "$HOME/ntawebsearchapi" ]; then
    SEARCH_DIR="$HOME/ntawebsearchapi"
elif [ -d "/sdcard/Download/ntawebsearchapi" ]; then
    SEARCH_DIR="/sdcard/Download/ntawebsearchapi"
fi

echo "=========================================================="
echo "    🚀 NETUARK SOVEREIGN DUAL-CLUSTER SUPERVISOR"
echo "=========================================================="
echo "  [Node] Hardware Host: $(uname -m 2>/dev/null || echo 'aarch64')"
echo "  [Media Dir]  ${MEDIA_DIR:-Not Found}"
echo "  [Search Dir] ${SEARCH_DIR:-Not Found}"
echo "=========================================================="

# ──────────────────────────────────────────────────────────────
# 1. Start Sovereign Media Server (Port 3000)
# ──────────────────────────────────────────────────────────────
if [ -n "$MEDIA_DIR" ]; then
    cd "$MEDIA_DIR"
    echo "[1/4] Starting Sovereign Media Server (server.py)..."
    nohup python3 server.py > server.log 2>&1 &
    SERVER_PID=$!

    SERVER_UP=0
    for i in 1 2 3 4 5 6 7 8 9 10; do
        sleep 1
        if (echo > /dev/tcp/127.0.0.1/3000) 2>/dev/null || curl -s http://127.0.0.1:3000/api/telemetry >/dev/null 2>&1; then
            SERVER_UP=1
            break
        fi
    done

    if [ "$SERVER_UP" -eq 1 ]; then
        echo "  [OK] Media Server is LIVE on port 3000 (PID: $SERVER_PID)"
    else
        echo "  [WARN] Media Server starting slower than expected. Recent server.log:"
        tail -n 5 server.log
    fi

    # Start Media Tunnel
    echo "[2/4] Starting Media Server Cloudflare Tunnel..."
    nohup python3 auto_tunnel.py > tunnel.log 2>&1 &
    MEDIA_TUNNEL_PID=$!
else
    echo "  [SKIP] Media server directory not found."
fi

# ──────────────────────────────────────────────────────────────
# 2. Start Headless Chromium Sandbox (Port 9222 CDP)
# ──────────────────────────────────────────────────────────────
CHROMIUM_BIN=$(command -v chromium 2>/dev/null || command -v chromium-browser 2>/dev/null || echo "")
if [ -n "$CHROMIUM_BIN" ]; then
    echo "[3/4] Launching Headless Chromium Sandbox on CDP Port 9222..."
    nohup "$CHROMIUM_BIN" \
        --headless=new \
        --no-sandbox \
        --disable-dev-shm-usage \
        --disable-gpu \
        --disable-software-rasterizer \
        --disable-background-networking \
        --disable-default-apps \
        --disable-extensions \
        --disable-sync \
        --remote-debugging-port=9222 \
        --remote-debugging-address=127.0.0.1 \
        --user-data-dir="$HOME/.config/nta-chromium-sandbox" \
        about:blank > chromium_cdp.log 2>&1 &
    CHROMIUM_PID=$!

    CDP_UP=0
    for i in 1 2 3 4 5; do
        sleep 1
        if curl -s http://127.0.0.1:9222/json/version >/dev/null 2>&1; then
            CDP_UP=1
            break
        fi
    done

    if [ "$CDP_UP" -eq 1 ]; then
        echo "  [OK] Chromium Sandbox CDP active on port 9222 (PID: $CHROMIUM_PID)"
    else
        echo "  [INFO] Chromium CDP initializing in background."
    fi
else
    echo "  [INFO] Chromium binary not installed yet (Search API will use TLS multi-engine fallback)."
fi

# ──────────────────────────────────────────────────────────────
# 3. Start Sovereign WebSearch API (Port 3001)
# ──────────────────────────────────────────────────────────────
SEARCH_TUNNEL_PID=""
if [ -n "$SEARCH_DIR" ]; then
    cd "$SEARCH_DIR"
    echo "[4/4] Starting Sovereign WebSearch API (Port 3001)..."
    nohup python3 search_server.py > search_server.log 2>&1 &
    SEARCH_PID=$!

    SEARCH_UP=0
    for i in 1 2 3 4 5 6 7; do
        sleep 1
        if (echo > /dev/tcp/127.0.0.1/3001) 2>/dev/null || curl -s http://127.0.0.1:3001/health >/dev/null 2>&1; then
            SEARCH_UP=1
            break
        fi
    done

    if [ "$SEARCH_UP" -eq 1 ]; then
        echo "  [OK] WebSearch API is LIVE on port 3001 (PID: $SEARCH_PID)"
    else
        echo "  [WARN] WebSearch API starting up. Recent search_server.log:"
        tail -n 5 search_server.log 2>/dev/null || true
    fi

    # Start Search Tunnel B
    nohup python3 search_tunnel.py > search_tunnel.log 2>&1 &
    SEARCH_TUNNEL_PID=$!
else
    echo "  [SKIP] WebSearch API directory not found at $HOME/ntawebsearchapi."
fi

# ──────────────────────────────────────────────────────────────
# 4. Resolve Live Tunnel URLs & Display Sovereign Status
# ──────────────────────────────────────────────────────────────
echo ""
echo "Waiting for live Cloudflare tunnels to establish..."
MEDIA_TUNNEL_URL=""
SEARCH_TUNNEL_URL=""

for i in $(seq 1 12); do
    sleep 1
    if [ -z "$MEDIA_TUNNEL_URL" ] && [ -f "$MEDIA_DIR/tunnel.log" ]; then
        MEDIA_TUNNEL_URL=$(grep -o 'https://[a-zA-Z0-9-]*\.trycloudflare\.com' "$MEDIA_DIR/tunnel.log" 2>/dev/null | tail -n 1)
    fi
    if [ -z "$SEARCH_TUNNEL_URL" ] && [ -n "$SEARCH_DIR" ] && [ -f "$SEARCH_DIR/search_tunnel.log" ]; then
        SEARCH_TUNNEL_URL=$(grep -o 'https://[a-zA-Z0-9-]*\.trycloudflare\.com' "$SEARCH_DIR/search_tunnel.log" 2>/dev/null | tail -n 1)
    fi
    if [ -n "$MEDIA_TUNNEL_URL" ] && [ -n "$SEARCH_TUNNEL_URL" ]; then
        break
    fi
done

echo ""
echo "=========================================================="
echo "       🎉 NETUARK SOVEREIGN CLUSTER IS OPERATIONAL"
echo "=========================================================="
echo "  [CLUSTER 1: Sovereign Media Server]"
echo "    Local Port:     http://127.0.0.1:3000"
echo "    Production Hub: https://ntamediaserver.pages.dev"
echo "    Live Tunnel:    ${MEDIA_TUNNEL_URL:-Establishing (check tunnel.log)}"
echo "    Media Docs:     https://ntamediaserver.pages.dev/docs"
echo ""
echo "  [CLUSTER 2: Sovereign WebSearch API & Chromium CDP]"
echo "    Local Port:     http://127.0.0.1:3001"
echo "    CDP Sandbox:    http://127.0.0.1:9222 (Chromium)"
echo "    Production Hub: https://ntawebsearch.pages.dev"
echo "    Live Tunnel:    ${SEARCH_TUNNEL_URL:-Establishing (check search_tunnel.log)}"
echo "    Search Docs:    https://ntawebsearch.pages.dev/docs"
echo "    Dashboard Hub:  https://ntamediaserver.pages.dev"
echo "=========================================================="
echo "  Supervision Active: termux-wake-lock held."
echo "=========================================================="
