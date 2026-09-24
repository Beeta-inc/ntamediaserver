pkg update -y
pkg install python openssh -y
pip install flask
mkdir -p ~/ntamediaserver/uploads/feed ~/ntamediaserver/uploads/chat
cp /sdcard/server.py ~/ntamediaserver/server.py
cd ~/ntamediaserver
pkill -f server.py
python server.py &
sleep 2
echo "Starting SSH Tunnel (localtunnel alternative)..."
ssh -o StrictHostKeyChecking=no -R 80:localhost:3000 nokey@localhost.run
