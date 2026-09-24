cd ~/ntamediaserver
cp /sdcard/auto_tunnel.py .
pkill -f cloudflared
pkill -f server.py
pkill -f auto_tunnel.py
python server.py &
sleep 2
echo "Starting auto_tunnel..."
python auto_tunnel.py
