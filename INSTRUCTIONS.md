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

## Step 5: Expose the Server to the Internet (High Availability)
The `auto_tunnel.py` script automatically manages Cloudflare Tunnels and coordinates between two phones to provide High Availability.

1. **Create a Secondary Firebase Project:** Go to Firebase and create a new project just for server synchronization. Create a Firestore database.
2. **Get Document URL:** Create a document (e.g. `serverSync/coordinator`) and copy its REST API URL.
3. **Configure the Script:** Open `auto_tunnel.py` and replace `YOUR_SECOND_PROJECT` in the `SYNC_FIRESTORE_URL` variable with your actual URL.
4. **Run the Script:**
```bash
python auto_tunnel.py
```
If this is the first phone running it, it will become the **MASTER** and start the tunnel. If you run this on a second phone, it will detect the master and stand by as **BACKUP**. If the master goes offline, the backup instantly takes over!

## Step 6: Setup Storage Synchronization (Syncthing)
Since you are running this on two devices, they need to share the same files.
1. Install **Syncthing** from the Google Play Store or F-Droid on both Android devices.
2. Open Syncthing on Phone A, tap the "+" to add a folder, and select `/sdcard/Download/NetuarkMedia`.
3. Open Syncthing on Phone B, go to "Devices" and add Phone A's Device ID to link them.
4. Accept the folder share on Phone B, pointing it to `/sdcard/Download/NetuarkMedia`.
Now, whenever a file is uploaded to Phone A, it instantly copies to Phone B over the internet.

## Step 7: Update the Netuark App / Frontend
In your Netuark app (`glowing-carnival` / `nta-apk-try1`), the app will automatically read the active Cloudflare URL from your MAIN Firebase database `mobileSignins/mediaServerConfig`. No manual updates needed!
