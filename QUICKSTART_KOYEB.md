# 🚀 BIMBO v4.0 — Koyeb Deploy 5-Minute Guide

## 1. Pehle ye cheezein le lo (free)
- **API ID / Hash** → https://my.telegram.org
- **Bot Token** → @BotFather se
- **Owner ID** → @userinfobot se apna ID le lo
- **MongoDB URI (free)** → https://mongodb.com/atlas (512 MB free)
  - Cluster banao → Connect → Drivers → connection string copy (`mongodb+srv://...`)

## 2. GitHub pe repo upload
1. Zip ko extract karo (`bimbobot_v4.zip`).
2. Naya repo banao GitHub pe, ex: `karan243coder/bimbobot-v4`.
3. Extracted folder ke andar ye chalao:
   ```bash
   git init
   git add .
   git commit -m "BIMBO v4.0 Ultimate"
   git branch -M main
   git remote add origin https://github.com/karan243coder/bimbobot-v4.git
   git push -u origin main
   ```

## 3. Koyeb pe deploy
1. https://app.koyeb.com/ pe login (GitHub se).
2. **Create App → Web Service → GitHub** → apna repo select.
3. **Builder**: `Dockerfile` (⚠️ must!)
4. **Instance**: Free (Nano) ya paid chaho to.
5. **Environment variables** fill karo (saare required `.env.example` me diye hain):
   ```
   BIMBO_API_ID=
   BIMBO_API_HASH=
   BIMBO_BOT_TOKEN=
   BIMBO_BOT_USERNAME=
   BIMBO_OWNER_ID=
   BIMBO_DATABASE_URL=
   PORT=8080
   ```
   Optional (speed ke liye defaults already sane hain):
   ```
   BIMBO_WORKERS=8
   BIMBO_MAX_CONCURRENT_TASKS=2
   BIMBO_MAX_CONCURRENT_DOWNLOADS=2
   BIMBO_MAX_CONCURRENT_UPLOADS=2
   YTDLP_USE_ARIA2C=true
   YTDLP_CONCURRENT_FRAGMENTS=10
   XHAMSTER_CONCURRENT_FRAGMENTS=1
   XHAMSTER_MAX_CONCURRENT_DOWNLOADS=1
   XHAMSTER_STALL_TIMEOUT=600
   XH_MIN_REQUEST_INTERVAL=1.25
   XH_429_COOLDOWN=120
   BIMBO_AUTO_CLEANUP_HOURS=2
   ```
6. **Port**: `8080`
7. **Health check**: `/`
8. **Deploy** dabao — build 2-3 min me ho jayega.

## 4. Test
- Bot pe `/start` bhejo.
- Agar start menu aaya → chal gaya! 🎉
- Pehle `/speed` bhej ke VPS speed check karo.
- Phir koi YouTube link bhejo — format selection buttons aane chahiye.

## 5. Agar error aaye
- Koyeb **Logs** tab me dekh kya error hai.
- Common issues:
  - **Invalid token** → BIMBO_BOT_TOKEN sahi se daala?
  - **API ID/Hash wrong** → my.telegram.org se dobara le lo.
  - **MongoDB network access** → Atlas me IP 0.0.0.0/0 allow karo.
  - **Build fail** → Dockerfile builder select kiya?
  - **Port issues** → PORT=8080 set hai?

## 6. First admin setup
- Owner tu hai (BIMBO_OWNER_ID).
- Bot me `/admin` bhejo — admin panel khulega.
- `/addpremium 123456 30` se kisi ko premium do.
- `/createcoupon 30 5` → 5 coupon codes generate honge (30 days each).
- `/maintenance on` → maintenance mode chalu.
- `/broadcast` (kisi msg pe reply) → sab users ko broadcast.

## 📌 Important Notes
- Free tier pe 2 concurrent downloads hi rakho (already default).
- 4 GB se bade files Telegram bot se nahi jaate — split feature automatic hai.
- Torrent download (libtorrent) free tier Docker pe nahi chalta; magnet links /ts se search karke user ko mil jate hain.
- Google Drive/Mega use karne ke liye alag se credentials chahiye (optional).
- Instagram/TikTok/Twitter bina cookie ke kaam karte hain; agar login required ho to cookie daalo.
- xHamster public links ke liye `cookies.txt` mat commit karo. Repeated HTTP 429 on Koyeb usually shared egress-IP limit hota hai; pehle cooldown do, aur persistent case me sirf apna authorized `BIMBO_HTTP_PROXY` use karo.

Enjoy! Bimbo69 💙
