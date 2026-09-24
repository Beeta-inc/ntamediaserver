# Netuark Mobile Media Server Setup

This server is designed to run on your Android mobile device using Termux, and be exposed to the internet via Cloudflare Tunnels (completely free). It will serve media files for the **feed** and **chat** features.

## Step 1: Install Required Apps on Android
1. Install **Termux** from F-Droid (do not use the Google Play Store version as it's deprecated).
2. Open Termux on your Android device.

## Step 2: Prepare Termux Environment
Run these commands inside Termux to set up the necessary tools:
```bash
# Update packages
pkg update && pkg upgrade -y

# Install Node.js, git, and Cloudflared
pkg install nodejs git cloudflared -y

# Give Termux access to your phone's storage
termux-setup-storage
```

## Step 3: Transfer the Server to your Phone
Since you're connected via ADB, we can push this `ntamediaserver` directory directly to your phone's storage. On your PC, run:
```bash
adb push /home/noywrit/ntamediaserver /sdcard/
```

Then, in Termux on your phone, copy it to the internal Termux home directory so it can be executed properly:
```bash
cp -r /sdcard/ntamediaserver ~/
cd ~/ntamediaserver

# Install the Node.js modules
npm install
```

## Step 4: Run the Media Server
Still inside Termux, start the Node.js server:
```bash
npm start
```
The server will now run on port 3000 (`http://localhost:3000`).

## Step 5: Expose the Server to the Internet via Cloudflare Tunnels
Open a **new session** in Termux (swipe from the left edge of the screen and tap "New session").
Run Cloudflare Tunnels to securely expose the local port 3000 to the internet for free:
```bash
cloudflared tunnel --url http://localhost:3000
```

Cloudflare will provide you with a `.trycloudflare.com` URL in the output (e.g., `https://random-words.trycloudflare.com`).

## Step 6: Update the Netuark App / Frontend
In your Netuark app (`glowing-carnival` / `nta-apk-try1`), you can now configure the media URL to point to the Cloudflare link provided in Step 5.
- The base URL is your Cloudflare URL.
- Feed images are accessible at `<CLOUDFLARE_URL>/media/feed/filename.ext`
- Chat images are accessible at `<CLOUDFLARE_URL>/media/chat/filename.ext`
- You can test uploading directly by opening the Cloudflare URL in your browser.

## Important Note
For production use, instead of using the temporary `--url` flag, you can set up a permanent Cloudflare Tunnel using your own domain through the Cloudflare Zero Trust dashboard.
