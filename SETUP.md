# 🚀 BIMBO Bot - Quick Setup Guide

## ⚡ Fast Setup (5 Minutes)

### Step 1: Install System Dependencies
```bash
# Ubuntu/Debian
sudo apt-get update
sudo apt-get install -y python3 python3-pip ffmpeg aria2 libtorrent-dev

# CentOS/RHEL
sudo yum install -y python3 python3-pip ffmpeg aria2 libtorrent-rasterbar-devel

# macOS
brew install python ffmpeg aria2 libtorrent-rasterbar
```

### Step 2: Clone & Install
```bash
cd /home/user
git clone <your-repo-url> BIMBO
cd BIMBO
pip install -r requirements.txt
```

### Step 3: Configure Bot
```bash
# Create .env file
cat > .env << 'ENVEOF'
# Telegram (Get from https://my.telegram.org)
API_ID=123456
API_HASH=your_api_hash_here
BOT_TOKEN=123456:ABC-DEF_your_bot_token_here

# Database (MongoDB - Free from mongodb.com)
MONGO_URI=mongodb+srv://username:password@cluster.mongodb.net/
DB_NAME=bimbo_bot

# Admin
ADMIN_IDS=123456789,987654321

# Aria2 (Optional - For faster downloads)
ARIA2_ENABLED=true
ARIA2_RPC_PORT=6800
ARIA2_SECRET=your_secret_here

# Torrent (Optional - Premium only)
TORRENT_ENABLED=true
TORRENT_PORT=6881
TORRENT_DOWNLOAD_PATH=./downloads

# Limits
MAX_CONCURRENT_DOWNLOADS=2
DEFAULT_DAILY_DOWNLOADS=10
DEFAULT_DAILY_DATA_MB=2048

# Premium Limits
PREMIUM_DAILY_DOWNLOADS=100
PREMIUM_DAILY_DATA_MB=51200
ENVEOF
```

### Step 4: Start Bot
```bash
python bot.py
```

### Step 5: Test
Open Telegram and send:
```
/start - Start bot
/status - Check system status
/help - See all commands
```

---

## 🔧 Detailed Setup

### Get Telegram API Credentials
1. Go to https://my.telegram.org
2. Login with your phone number
3. Click "API development tools"
4. Create new app
5. Copy `API_ID` and `API_HASH`

### Get Bot Token
1. Open Telegram, search `@BotFather`
2. Send `/newbot`
3. Follow instructions
4. Copy the bot token

### Setup MongoDB (Free)
1. Go to https://mongodb.com
2. Create free account
3. Create free cluster (M0)
4. Get connection string
5. Add to `.env` file

### Install Aria2 (Optional - For faster downloads)
```bash
# Ubuntu/Debian
sudo apt-get install aria2

# Start Aria2 RPC server
aria2c --enable-rpc --rpc-listen-all --rpc-secret=your_secret
```

### Install FFmpeg (Required for video features)
```bash
# Ubuntu/Debian
sudo apt-get install ffmpeg

# Verify
ffmpeg -version
```

---

## 📋 Environment Variables

### Required:
```bash
API_ID=123456                    # Telegram API ID
API_HASH=your_hash               # Telegram API Hash
BOT_TOKEN=123:ABC                # Bot token from BotFather
MONGO_URI=mongodb://...          # MongoDB connection string
DB_NAME=bimbo_bot                # Database name
ADMIN_IDS=123456789              # Your Telegram user ID
```

### Optional:
```bash
# Aria2 (Faster downloads)
ARIA2_ENABLED=true
ARIA2_RPC_PORT=6800
ARIA2_SECRET=your_secret

# Torrent (Premium feature)
TORRENT_ENABLED=true
TORRENT_PORT=6881
TORRENT_DOWNLOAD_PATH=./downloads

# Limits
MAX_CONCURRENT_DOWNLOADS=2
DEFAULT_DAILY_DOWNLOADS=10
DEFAULT_DAILY_DATA_MB=2048

# Premium
PREMIUM_DAILY_DOWNLOADS=100
PREMIUM_DAILY_DATA_MB=51200
VIP_DAILY_DOWNLOADS=-1           # -1 = unlimited
VIP_DAILY_DATA_MB=-1

# Logging
LOG_LEVEL=INFO
LOG_FILE=bot.log
```

---

## 🎯 First Run Checklist

- [ ] Install Python 3.8+
- [ ] Install FFmpeg
- [ ] Install Aria2 (optional)
- [ ] Get Telegram API credentials
- [ ] Get Bot token from BotFather
- [ ] Setup MongoDB (free)
- [ ] Create `.env` file
- [ ] Install dependencies: `pip install -r requirements.txt`
- [ ] Start bot: `python bot.py`
- [ ] Test `/start` command
- [ ] Test `/status` command
- [ ] Add yourself as premium: `/addpremium YOUR_ID 365`

---

## 🔐 Add Premium User (Yourself)

After starting the bot, make yourself premium:

```bash
# In Telegram, send to your bot:
/addpremium YOUR_TELEGRAM_ID 365

# Example:
/addpremium 123456789 365
```

This gives you:
- Unlimited downloads
- Torrent support
- Video conversion
- Screenshot generation
- Priority queue

---

## 🐛 Troubleshooting

### Bot not starting?
```bash
# Check Python version
python3 --version  # Should be 3.8+

# Check dependencies
pip list | grep -E "pyrogram|aiohttp|motor"

# Check logs
tail -f bot.log
```

### FFmpeg not found?
```bash
# Ubuntu/Debian
sudo apt-get install ffmpeg

# Verify
which ffmpeg
ffmpeg -version
```

### Aria2 not connecting?
```bash
# Start Aria2 RPC
aria2c --enable-rpc --rpc-listen-all --rpc-secret=your_secret

# Or use systemd service
sudo systemctl start aria2
```

### MongoDB connection error?
```bash
# Check connection string
echo $MONGO_URI

# Test connection
python3 -c "from pymongo import MongoClient; c = MongoClient('YOUR_URI'); print(c.server_info())"
```

### Torrent not working?
```bash
# Check libtorrent
python3 -c "import libtorrent; print(libtorrent.version)"

# Enable in .env
TORRENT_ENABLED=true

# Premium only - add yourself as premium first
```

---

## 📊 Verify Installation

Run this to check everything:
```bash
python3 << 'PYEOF'
import sys
print(f"Python: {sys.version}")

try:
    import pyrogram
    print(f"✓ Pyrogram: {pyrogram.__version__}")
except:
    print("✗ Pyrogram not installed")

try:
    import aiohttp
    print(f"✓ aiohttp: {aiohttp.__version__}")
except:
    print("✗ aiohttp not installed")

try:
    import motor
    print(f"✓ Motor: {motor.__version__}")
except:
    print("✗ Motor not installed")

try:
    import libtorrent
    print(f"✓ libtorrent: {libtorrent.version}")
except:
    print("✗ libtorrent not installed")

try:
    import psutil
    print(f"✓ psutil: {psutil.__version__}")
except:
    print("✗ psutil not installed")

import subprocess
result = subprocess.run(['ffmpeg', '-version'], capture_output=True)
if result.returncode == 0:
    print("✓ FFmpeg: installed")
else:
    print("✗ FFmpeg not installed")

result = subprocess.run(['aria2c', '--version'], capture_output=True)
if result.returncode == 0:
    print("✓ Aria2: installed")
else:
    print("⚠ Aria2 not installed (optional)")
PYEOF
```

---

## 🚀 Deploy to Koyeb (Free)

### Step 1: Push to GitHub
```bash
cd /home/user/BIMBO
git init
git add .
git commit -m "Initial commit with all features"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/BIMBO.git
git push -u origin main
```

### Step 2: Deploy on Koyeb
1. Go to https://koyeb.com
2. Create free account
3. Click "Create App"
4. Connect GitHub repository
5. Select `BIMBO` repository
6. Add environment variables from `.env`
7. Click "Deploy"

### Step 3: Monitor
```bash
# View logs on Koyeb dashboard
# Or use CLI
koyeb apps logs bimbo-bot
```

---

## 📱 Bot Commands

### User Commands:
```
/start - Start bot
/help - Show help
/language - Change language (English/Hindi)
/status - System status (REAL stats!)
/quota - Show your quota
/premium - Premium info
/queue - Show download queue
/cancel - Cancel download

/download <url> - Download file
/aria2 <url> - Download with Aria2 (faster)
/torrent <magnet> - Add torrent (premium only)
/convert - Convert video (premium, reply to video)
/screenshot - Screenshot (premium, reply to video)
```

### Admin Commands:
```
/admin - Admin panel
/stats - Bot statistics
/broadcast - Send broadcast
/addpremium <user_id> <days> - Add premium
/removepremium <user_id> - Remove premium
/setquota <user_id> <downloads> <data_mb> - Set quota
/resetquota <user_id> - Reset quota
/ban <user_id> - Ban user
/unban <user_id> - Unban user
```

---

## 🎉 You're Done!

Your BIMBO bot is now ready with:
- ✅ Advanced Progress UI (REAL stats)
- ✅ Aria2 Integration (5-10x faster)
- ✅ Download Queue System
- ✅ Multi-language (English + Hindi)
- ✅ User Quota System
- ✅ Premium System (Free/Premium/VIP)
- ✅ Video Conversion
- ✅ Screenshot Generation
- ✅ Torrent Support
- ✅ Real-time System Status
- ✅ Admin Panel

**Enjoy your professional Telegram bot!** 🚀

---

## 📞 Support

If you face any issues:
1. Check logs: `tail -f bot.log`
2. Read FEATURES.md for details
3. Check environment variables
4. Verify all dependencies installed

**Happy Botting!** 💪
