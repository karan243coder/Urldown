<p align="center">
 <h1 align="center">🚀 BIMBO URL Uploader Bot v4.0 — ULTIMATE EDITION</h1>
 <p align="center">Advanced Pyrogram-based Telegram bot for downloading from 1000+ sites, processing videos, and uploading to Telegram or cloud.</p>
</p>

---

## ✨ Features (v4.0 Ultimate)

### 📥 Download Sources
- ✅ YouTube / YouTube Music / Playlists
- ✅ **Instagram Reels/Posts/IGTV** (cookie supported)
- ✅ **TikTok, Facebook, Twitter/X** (via yt-dlp)
- ✅ **Terabox** (dedicated engine)
- ✅ **xHamster** (dedicated engine)
- ✅ **Pixeldrain, Gofile, Doodstream, Streamtape**
- ✅ **M3U8 / MPD** (HLS/DASH streams)
- ✅ **Direct HTTP/HTTPS/FTP links** (aria2 multi-thread)
- ✅ **Torrent/Magnet** (if libtorrent installed on host)
- ✅ Torrent search (1337x + YTS) via `/ts`

### 🎬 Media Tools (FFmpeg)
- ✅ **Screenshots** — `/ss [n]` (1–10 screenshots)
- ✅ **Sample Video** — `/sample [secs]`
- ✅ **Trim/Cut** — `/trim start end`
- ✅ **Compress** — `/compress [low|med|high]`
- ✅ **Watermark** — `/wm "text" [pos]` (video + image)
- ✅ **Extract Audio/MP3** — `/mp3`
- ✅ **Zip/Unzip** — `/zip`, `/unzip`
- ✅ **Rename** — `/rename newname.ext`
- ✅ Custom Thumbnail, Auto-Gen Thumbnail

### ☁️ Cloud Upload
- ✅ **Gofile.io** — free stream link, no creds needed (`/gofile`)
- ✅ **Mega.nz** (`/mega`) — needs `MEGA_EMAIL` + `MEGA_PASSWORD`
- ✅ **Google Drive** (`/gdrive`) — needs service account JSON
- ✅ Telegram file upload (4 GB parts auto-split)

### 👥 User System
- ✅ Force Subscribe channel
- ✅ **Ban/Unban** with reason log
- ✅ **Premium system** (daily/weekly/monthly plans)
- ✅ **Referral system** (3 refs = 1 day free premium)
- ✅ **Coupon codes** (admin generates, users redeem)
- ✅ Rate limiting / anti-spam
- ✅ User quota tracking
- ✅ Multi-language placeholder (Hindi/English)
- ✅ URL shortener / token verification (optional)

### 👑 Admin Features
- ✅ Admin Panel (`/admin`) with live stats
- ✅ Broadcast (text/photo/video/doc) to all users
- ✅ Grant/Revoke premium
- ✅ Ban list, stats, DB backup (JSON export)
- ✅ Maintenance mode toggle
- ✅ Manual cache clear (`/clearcache`)
- ✅ Auto-cleanup of old downloads (disk protection)

### ⚡ Performance (Optimized for Koyeb/Heroku/VPS)
- ✅ **aria2c** external downloader (16 connections) for 5-10x HTTP speed
- ✅ **yt-dlp concurrent fragments** (10 parallel) for HLS
- ✅ Pyrogram workers tuned (`max_concurrent_transmissions=8`)
- ✅ aiohttp TCP tuning (DNS cache, keep-alive)
- ✅ Disk cache + `/tmp` fast I/O
- ✅ Auto-cleanup thread (default 2h)
- ✅ `/speed` test command
- ✅ `/tuning` live tuning info + CPU/RAM/Disk

---

## 🚀 Deploy on Koyeb (recommended)

### 1. Required Environment Variables
| Variable | Required | Description |
|---|---|---|
| `BIMBO_API_ID` | ✅ | from my.telegram.org |
| `BIMBO_API_HASH` | ✅ | from my.telegram.org |
| `BIMBO_BOT_TOKEN` | ✅ | from @BotFather |
| `BIMBO_BOT_USERNAME` | ✅ | bot username without @ |
| `BIMBO_OWNER_ID` | ✅ | your Telegram ID |
| `BIMBO_DATABASE_URL` | ✅ | MongoDB URI (free from MongoDB Atlas) |
| `BIMBO_LOG_CHANNEL` | ⚪ | Channel ID (-100…) for logs |
| `BIMBO_UPDATES_CHANNEL` | ⚪ | Channel ID for force-sub |
| `BIMBO_START_PIC` | ⚪ | Start image URL (telegra.ph) |
| `BIMBO_START_MSG` | ⚪ | Custom start message HTML |
| `PORT` | ✅ (Koyeb auto) | `8080` |

### 2. Optional Variables (speed/features)
| Variable | Default | Purpose |
|---|---|---|
| `BIMBO_WORKERS` | 8 | Pyrogram workers |
| `BIMBO_MAX_CONCURRENT_TASKS` | 2 | Legacy routes fallback limit |
| `BIMBO_MAX_CONCURRENT_DOWNLOADS` | 2 | Global fair download-stage slots |
| `BIMBO_MAX_CONCURRENT_UPLOADS` | 2 | Global Telegram upload-stage slots |
| `YTDLP_CONCURRENT_FRAGMENTS` | 10 | Parallel fragments for generic HLS |
| `XHAMSTER_CONCURRENT_FRAGMENTS` | 1 | Conservative fragments inside one xHamster HLS stream |
| `XHAMSTER_MAX_CONCURRENT_DOWNLOADS` | 1 | One heavy xHamster stream per bot/IP; extra tasks queue safely |
| `XHAMSTER_STALL_TIMEOUT` | 600 | Stop a frozen xHamster subprocess after 10 min without progress |
| `XH_MIN_REQUEST_INTERVAL` | 1.25 | Seconds between xHamster metadata requests |
| `XH_429_COOLDOWN` | 120 | Per-host cooldown after HTTP 429 |
| `BIMBO_HTTP_PROXY` | — | Optional owner-authorized HTTP(S) proxy for shared-host IP limits |
| `XHAMSTER_USE_COOKIES` | false | Opt-in private `cookies.txt` for login/age-gated videos only |
| `YTDLP_USE_ARIA2C` | true | aria2 for HTTP downloads |
| `BIMBO_AUTO_CLEANUP_HOURS` | 2 | Auto-delete old files |
| `BIMBO_USE_TMP` | true | Use /tmp for fast I/O |
| `BIMBO_SPLIT_SIZE` | 1900MB | Split threshold |
| `MEGA_EMAIL` / `MEGA_PASSWORD` | — | Mega.nz credentials |
| `BIMBO_GDRIVE_CREDENTIALS` | — | Path to service-account.json |
| `BIMBO_GDRIVE_FOLDER_ID` | — | GDrive target folder |
| `GOFILE_TOKEN` | — | Optional Gofile account token |
| `BIMBO_INSTAGRAM_COOKIE` | — | Instagram cookie file for login |
| `BIMBO` / `BIMBO_URL` / `BIMBO_API` / `BIMBO_TUTORIAL` | — | URL shortener/token verify |
| `MAINTENANCE_MODE` | false | Start in maintenance |
| `RATE_LIMIT_SECONDS` | 15 | Free-user cooldown |

### 3. Steps
1. GitHub par ye repo push karo.
2. Koyeb → **New Service → GitHub** → repo select.
3. **Builder: Dockerfile** select karo (important!).
4. Saare env vars fill karo.
5. Port expose karo: `8080` (HTTP health check).
6. Deploy karo, boot logs me dekhna:
   ```
   ✅ Health server listening on port 8080
   ✅ Aria2 RPC ready — dir=/tmp/bimbo_downloads ...
   🚀 BIMBO v4.0 starting up...
   ```

> **Cookie security:** Real `cookies.txt` GitHub par commit mat karo. Public xHamster
> links no-cookie-first mode me chalte hain. Agar private/login-gated link ke liye
> cookie zaroori ho, xHamster-only current cookie file privately mount karo aur
> `XHAMSTER_USE_COOKIES=true` set karo. Pehle commit ki gayi browser cookies ko
> revoke/rotate karna zaroori hai; `.gitignore` sirf future commits ko rokta hai.

---

## 📋 Commands

### General
| Command | Kaam |
|---|---|
| `/start` | Start bot |
| `/help` | Full command list |
| `/about` | About bot |
| `/status` | Bot status |
| `/speed` | Speed test |
| `/tuning` | Live tuning + CPU/RAM |
| `/cancel` | Cancel task |
| `/queue` | Download queue |

### Download (Shortcuts)
| Command | Kaam |
|---|---|
| `/yt <url>` | YouTube |
| `/ig <url>` | Instagram |
| `/tt <url>` | TikTok |
| `/fb <url>` | Facebook |
| `/tw <url>` | Twitter/X |
| `/m3u8 <url>` | HLS stream |
| `/tera <url>` | Terabox |
| `/pd <url>` | Pixeldrain |
| `/ts <query>` | Torrent search (1337x/YTS) |

> **Note:** Bina command ke direct link bhejo bhi toh bot auto-detect karke download karega.

### Media Tools
| Command | Kaam |
|---|---|
| `/ss [count]` | Screenshots (reply to video) |
| `/sample [secs]` | Sample video |
| `/trim s e` | Trim/cut |
| `/compress [low/med/high]` | Compress |
| `/wm "text" [pos]` | Watermark |
| `/mp3` | Extract audio |
| `/zip`, `/unzip` | Zip/extract |
| `/rename new.ext` | Rename & re-upload |
| Photo bhejo | Custom thumbnail set |
| `/delthumbnail` | Thumbnail remove |

### Cloud
| Command | Kaam |
|---|---|
| `/gofile` | Upload → Gofile stream link |
| `/mega` | Upload → Mega.nz |
| `/gdrive` | Upload → Google Drive |

### User
| Command | Kaam |
|---|---|
| `/plan` or `/premium` | Plans info |
| `/myplan` or `/quota` | Your plan/quota |
| `/redeem CODE` | Coupon redeem |
| `/language` | Language toggle |

### Admin/Owner
| Command | Kaam |
|---|---|
| `/admin` | Admin panel |
| `/stats` | Bot stats |
| `/broadcast` | Broadcast (reply to msg) |
| `/ban id [reason]` | Ban user |
| `/unban id` | Unban |
| `/banlist` | Banned users |
| `/addpremium id days` | Grant premium |
| `/delpremium id` | Revoke premium |
| `/createcoupon days [n]` | Generate coupons |
| `/maintenance on/off` | Maintenance mode |
| `/backup` | DB JSON backup |
| `/clearcache` | Clear downloads folder |

---

## 🛠️ Local Run
```bash
git clone <repo> && cd bimbobot
cp .env.example .env  # fill vars
pip install -r requirements.txt
apt-get install -y ffmpeg aria2 fonts-dejavu-core
python3 -m bot
```

---

## ⚠️ Notes for Koyeb Free Tier
- Free tier ~0.5 vCPU / 512MB RAM hai → `BIMBO_MAX_CONCURRENT_TASKS=2` rakho.
- Disk ephemeral hai (restart pe downloads chali jayengi) — auto-cleanup chalu rakho.
- Files >1.5 GB thode slow ho sakte hain; paid Koyeb/VPS behtar rahega.
- libtorrent Koyeb Docker build me available nahi hai isliye torrent download via engine off hoga — but magnet links search se nikal ke client pe daal sakte ho.

---

## ❤️ Credits
- Based on original URL-Uploader by Clinton Abraham
- Customized & upgraded to v4.0 by BIMBO (@Bimbo69)
- Powered by [Pyrogram](https://docs.pyrogram.org/), [yt-dlp](https://github.com/yt-dlp/yt-dlp), [aria2](https://aria2.github.io/), [FFmpeg](https://ffmpeg.org/)
