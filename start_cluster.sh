#!/bin/bash
pkill -f python
cp -r /sdcard/ntamediaserver ~/
cd ~/ntamediaserver
nohup python server.py > server.log 2>&1 &
nohup python auto_tunnel.py > tunnel.log 2>&1 &
echo "Cluster Started successfully!"
