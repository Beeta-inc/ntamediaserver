#!/bin/bash
termux-wake-lock 2>/dev/null || true
pkill -9 -f termux-api 2>/dev/null || true
pkill -f server.py 2>/dev/null || true
pkill -f auto_tunnel.py 2>/dev/null || true
sleep 1
cd ~/ntamediaserver
nohup python3 server.py > server.log 2>&1 &
nohup python3 auto_tunnel.py > tunnel.log 2>&1 &
echo "Started sovereign cluster. Logs: server.log / tunnel.log"
