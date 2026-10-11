#!/bin/bash
termux-wake-lock 2>/dev/null || true
pkill -9 -f termux-api 2>/dev/null || true
pkill -f server.py 2>/dev/null || true
pkill -f auto_tunnel.py 2>/dev/null || true
pkill -f cloudflared 2>/dev/null || true
sleep 1

# Navigate to project directory
if [ -d "$HOME/ntamediaserver" ]; then
    cd "$HOME/ntamediaserver"
elif [ -d "/sdcard/Download/ntamediaserver" ]; then
    cd "/sdcard/Download/ntamediaserver"
fi

echo "================================================="
echo "   NTA Media Server - Sovereign Cluster Starter"
echo "================================================="

# 1. Start server.py
echo "[1/3] Starting server.py..."
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
    echo "  [OK] server.py is live on port 3000 (PID: $SERVER_PID)"
else
    echo "  [WARN] server.py did not respond on port 3000 yet. Recent server.log:"
    tail -n 8 server.log
fi

# 2. Start auto_tunnel.py
echo "[2/3] Starting auto_tunnel.py & Cloudflare Tunnel..."
nohup python3 auto_tunnel.py > tunnel.log 2>&1 &
TUNNEL_PID=$!

# Wait for tunnel URL
echo "[3/3] Waiting for live tunnel connection..."
TUNNEL_URL=""
for i in $(seq 1 15); do
    sleep 1
    TUNNEL_URL=$(grep -o 'https://[a-zA-Z0-9-]*\.trycloudflare\.com' tunnel.log 2>/dev/null | tail -n 1)
    if [ -n "$TUNNEL_URL" ]; then
        break
    fi
done

echo ""
echo "================================================="
if [ -n "$TUNNEL_URL" ]; then
    echo "  STATUS: ONLINE"
    echo "  Live Tunnel:  $TUNNEL_URL"
    echo "  Edge Gateway: https://ntamediaserver.pages.dev"
    echo "  Telemetry:    https://ntamediaserver.pages.dev/api/telemetry"
else
    echo "  STATUS: TUNNEL INITIALIZING"
    echo "  Process PID:  $TUNNEL_PID"
    echo "  Check log:    tail -f tunnel.log"
fi
echo "================================================="
