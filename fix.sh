#!/bin/bash
echo "Upgrading packages to fix linker error..."
pkg upgrade -y
echo "Reinstalling nodejs..."
pkg reinstall nodejs -y
echo "Starting server..."
cd ~/ntamediaserver
npm install
npm start &
echo "Starting cloudflared..."
cloudflared tunnel --url http://localhost:3000
