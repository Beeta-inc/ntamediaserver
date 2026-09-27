#!/bin/bash
pkill -f server.py
pkill -f auto_tunnel.py
cd ~/ntamediaserver
# git pull origin main || true
nohup python3 server.py > server.log 2>&1 &
nohup python3 auto_tunnel.py > tunnel.log 2>&1 &
echo "Started. Logs: server.log / tunnel.log"
