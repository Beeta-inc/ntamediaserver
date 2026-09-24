pkg update -y
pkg install resolv-conf python -y
pip install flask
mkdir -p ~/ntamediaserver/uploads/feed ~/ntamediaserver/uploads/chat
cp /sdcard/server.py ~/ntamediaserver/server.py
cd ~/ntamediaserver
pkill -f server.py
python server.py &
sleep 2
echo "Starting Cloudflare Tunnels with fixed DNS..."
cloudflared tunnel --url http://localhost:3000
