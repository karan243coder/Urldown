# 🎯 Terabox Integration Guide

## ✅ Successfully Added Terabox Support!

Bhai, tere bot mein ab **Terabox** ka full support add ho gaya hai using the **TeraboxDL** package!

---

## 📋 What's New

### 1. **New File: `plugins/terabox_engine.py`**
- Uses `terabox-downloader` PyPI package
- Extracts file info (name, size, download link, thumbnail)
- Downloads files from Terabox
- Handles errors gracefully

### 2. **Updated: `config.py`**
- Added `BIMBO_TERABOX_COOKIE` environment variable

### 3. **Updated: `plugins/youtube_dl_button.py`**
- Added `terabox_call_back()` function
- Downloads and uploads Terabox files
- Supports Video/File/Audio formats
- Progress tracking and thumbnails

### 4. **Updated: `plugins/youtube_dl_echo.py`**
- Added Terabox URL detection
- Shows file info and download buttons

---

## 🍪 How to Get Terabox Cookie (IMPORTANT!)

### Step 1: Login to Terabox
1. Open browser (Chrome/Firefox/Edge)
2. Go to https://www.terabox.com
3. Login with your account

### Step 2: Open Developer Tools
1. Press `F12` or right-click → Inspect
2. Go to **Application** tab (Chrome) or **Storage** tab (Firefox)

### Step 3: Find Cookies
1. In left sidebar, expand **Cookies**
2. Click on `https://www.terabox.com`
3. Look for these two cookies:
   - `lang` (usually "en")
   - `ndus` (long string like "abc123xyz...")

### Step 4: Copy Cookie Values
1. Click on `lang` → copy the **Value**
2. Click on `ndus` → copy the **Value**

### Step 5: Format Cookie String
Combine them like this:
```
lang=en; ndus=YOUR_NDUS_VALUE_HERE;
```

**Example:**
```
lang=en; ndus=YxK9mP2nQ8rT5vW3jL6hF4gD1sA7cB0e;
```

---

## ⚙️ How to Configure

### Method 1: Environment Variable (Recommended)

**For Koyeb/Heroku/Railway:**
1. Go to your app settings
2. Find "Environment Variables" or "Config Vars"
3. Add new variable:
   - **Key:** `BIMBO_TERABOX_COOKIE`
   - **Value:** `lang=en; ndus=YOUR_NDUS_VALUE;`

**For Local Testing:**
```bash
export BIMBO_TERABOX_COOKIE="lang=en; ndus=YOUR_NDUS_VALUE;"
python3 bot.py
```

### Method 2: Direct in config.py (Not Recommended)
```python
BIMBO_TERABOX_COOKIE = "lang=en; ndus=YOUR_NDUS_VALUE;"
```

⚠️ **Warning:** Don't commit cookie to GitHub!

---

## 🎮 How It Works

### User Flow:

1. **User sends Terabox link:**
   ```
   https://terasharefile.com/s/1iMeUkUoX0SHsjqqbkBT_Mw
   ```

2. **Bot detects and extracts info:**
   ```
   🔄 Processing Terabox Link
   
   Extracting file information...
   ⏳ Please wait...
   ```

3. **Bot shows file info:**
   ```
   ✅ Terabox file detected
   
   📁 File: 1080p.mp4
   📦 Size: 1.2 GB
   
   🎯 Choose download option
   [🎬 Send as Video] [📁 Send as File]
   ```

4. **User clicks download button**

5. **Bot downloads and uploads:**
   ```
   📥 Downloading from Terabox
   
   📁 File: 1080p.mp4
   📦 Size: 1.2 GB
   
   ⏳ Downloading...
   Please wait, this may take a while.
   ```

6. **Success:**
   ```
   ✅ Uploaded successfully
   
   📁 File: 1080p.mp4
   📦 Size: 1.2 GB
   ⏱ Upload Time: 45s
   
   Join: @Bimbobot69
   ```

---

## 🧪 Testing

### Step 1: Configure Cookie
Set the `BIMBO_TERABOX_COOKIE` environment variable

### Step 2: Install Package
```bash
pip install terabox-downloader
```

### Step 3: Test with Your Link
Send this to your bot:
```
https://terasharefile.com/s/1iMeUkUoX0SHsjqqbkBT_Mw
```

### Step 4: Check Logs
Look for these log messages:
```
✓ Initializing TeraboxDL for URL: ...
✓ Fetching file info from Terabox...
✓ Successfully extracted Terabox file info: 1080p.mp4
```

---

## 🔧 Troubleshooting

### Error: "Terabox cookie not configured"

**Solution:**
- Set `BIMBO_TERABOX_COOKIE` environment variable
- Make sure format is correct: `lang=en; ndus=VALUE;`

### Error: "TeraboxDL package not installed"

**Solution:**
```bash
pip install terabox-downloader
```

### Error: "Failed to get file information"

**Possible Causes:**
1. **Invalid cookie** - Get fresh cookie from browser
2. **Expired cookie** - Cookies expire, get new one
3. **Invalid link** - Check if link works in browser
4. **Private file** - File might require login
5. **Terabox API issues** - Wait and try again

**Solution:**
- Get fresh cookie from browser
- Test link in browser first
- Check Koyeb logs for detailed error

### Error: "Download failed"

**Possible Causes:**
1. Network issues
2. File too large
3. Terabox rate limiting

**Solution:**
- Wait a few minutes and retry
- Check server internet connection
- Try smaller files first

---

## 📊 Supported Domains

All these domains are supported:
- terabox.com
- teraboxapp.com
- 1024tera.com
- terasharefile.com
- mirrobox.com
- nephobox.com
- 4funbox.com
- And 30+ more mirrors!

---

## 🚀 Deployment

### Update requirements.txt
Add this line:
```
terabox-downloader==1.8
```

### Deploy
```bash
cd BIMBO
git add .
git commit -m "Added Terabox support with TeraboxDL"
git push
```

---

## 💡 Important Notes

### Cookie Expiration
- Terabox cookies expire after some time
- If downloads stop working, get a fresh cookie
- Update environment variable with new cookie

### Rate Limiting
- Don't spam too many downloads at once
- Terabox might temporarily block your cookie
- Wait a few minutes between downloads

### File Size Limits
- Telegram bot limit: 50 MB (normal)
- Telegram bot limit: 2 GB (premium)
- Check your bot's limits

### Privacy
- Never commit cookie to GitHub
- Use environment variables
- Rotate cookies periodically

---

## 📝 Example Environment Variables

**Koyeb:**
```
BIMBO_TERABOX_COOKIE=lang=en; ndus=YxK9mP2nQ8rT5vW3jL6hF4gD1sA7cB0e;
```

**Heroku:**
```bash
heroku config:set BIMBO_TERABOX_COOKIE="lang=en; ndus=YxK9mP2nQ8rT5vW3jL6hF4gD1sA7cB0e;"
```

**Railway:**
```
BIMBO_TERABOX_COOKIE=lang=en; ndus=YxK9mP2nQ8rT5vW3jL6hF4gD1sA7cB0e;
```

---

## ✅ Checklist

Before deploying:

- [ ] Got Terabox cookie from browser
- [ ] Set `BIMBO_TERABOX_COOKIE` environment variable
- [ ] Installed `terabox-downloader` package
- [ ] Added to requirements.txt
- [ ] Tested with sample link
- [ ] Checked logs for errors
- [ ] Committed and pushed code

---

## 🎉 Success!

Ab tera bot **fully Terabox-ready** hai!

**Features:**
- ✅ Automatic Terabox detection
- ✅ File info extraction
- ✅ High-quality downloads
- ✅ Video/File/Audio upload options
- ✅ Progress tracking
- ✅ Custom thumbnails
- ✅ Error handling

**Next Steps:**
1. Get Terabox cookie from browser
2. Set environment variable
3. Deploy to Koyeb
4. Test with your link
5. Enjoy! 🚀

---

## 📞 Support

Agar koi issue aaye toh:
1. Check Koyeb logs
2. Look for `terabox:` prefixed messages
3. Verify cookie is correct
4. Test link in browser first
5. Share error logs with me

Main fix kar dunga! 💪
