# BIMBO Bot v4.0 - Translations (Hindi + English)
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton


class Translation(object):

    # ----------------------------------------------------------------
    # START / HOME / HELP
    # ----------------------------------------------------------------
    # ⚡ SOUMITRISHA PRO - SHORT ADVANCE ENGLISH VERSION
    BIMBO_START_TEXT = """
<b>⚡ Soumitrisha ⚡</b>
━━━━━━━━━━━━━━━━━━━━
👋 Hello {0} (<code>{1}</code>)

• <b>Status:</b> <code>Active 🟢</code>
• <b>Speed:</b> <code>Ultra-Fast 🚀</code>
• <b>Limit:</b> <code>4GB Available 📂</code>

<b>🚀 What I Do:</b>
• Instant Stream Link Generator
• Any URL → Telegram Direct Upload
• Supports Adult-site, YouTube, IG, M3U8, Direct & 1000+ Sites

<i>✨ Just send me any link, I'll upload it instantly with streaming support.</i>
"""

    BIMBO_HELP_TEXT = """
<b>📚 BIMBO Bot — Full Command List</b>

<b>📥 Downloads:</b>
• Link bhejo — auto format select
• <code>/yt link</code> — YouTube download
• <code>/direct link</code> — direct HTTP
• <code>/m3u8 link</code> — HLS stream
• <code>/tera link</code> — Terabox
• <code>/ig link</code> — Instagram
• <code>/tt link</code> — TikTok
• <code>/torrent magnet|file</code> — Torrent (if libtorrent available)
• <code>/ts query</code> — torrent search (1337x/YTS)

<b>🔞 xHamster (Advanced):</b>
• <code>/xh url</code> — auto detect video/gallery/profile
• <code>/xhs query</code> — xHamster search
• <code>/xhg gallery_url</code> — download gallery photos as album
• <code>/xhp profile_url</code> — list videos from creator/pornstar
• Direct xHamster video link bhejo — auto download

<b>🎬 Media Tools:</b>
• <code>/ss</code> reply to video — screenshots
• <code>/sample</code> — 60s sample video
• <code>/trim start end</code> — cut video
• <code>/compress</code> — compress video
• <code>/wm</code> reply — add watermark
• <code>/mp3</code> reply — extract audio
• <code>/rename name</code> — rename file
• <code>/zip</code> reply files — zip & send
• <code>/unzip</code> reply — extract zip

<b>☁️ Cloud:</b>
• <code>/gdrive</code> reply — upload to Google Drive
• <code>/mega</code> reply — upload to Mega
• <code>/gofile</code> reply — Gofile stream link

<b>📊 Utilities:</b>
• <code>/status</code> — system/bot status
• <code>/speed</code> — speed test
• <code>/queue</code> — download queue
• <code>/tuning</code> — optimization info
• <code>/quota</code> — your daily quota
• <code>/plan</code> — premium plans
• <code>/cancel</code> — cancel task

<b>🖼️ Thumbnail:</b>
• Photo bhejo — thumbnail set
• <code>/delthumbnail</code> — thumbnail remove

<b>👑 Admin:</b>
• <code>/admin</code> — admin panel
• <code>/broadcast</code> — broadcast
• <code>/ban</code>, <code>/unban</code>
• <code>/addpremium</code>, <code>/delpremium</code>
• <code>/stats</code> — bot stats
• <code>/backup</code> — DB backup
• <code>/maintenance on|off</code>
• <code>/clearcache</code> — clean downloads
"""

    BIMBO_ABOUT_TEXT = """
<b>ℹ️ About BIMBO Bot v4.0</b>

<b>🤖 Name:</b> BIMBO URL Uploader
<b>🔰 Version:</b> v4.0 Ultimate
<b>🐍 Lang:</b> Python 3
<b>⚙️ Framework:</b> Pyrogram + yt-dlp + aria2
<b>📦 Engines:</b> yt-dlp | aria2c | FFmpeg | libtorrent
<b>👨‍💻 Developer:</b> @Bimbo69
<b>📢 Channel:</b> @Bimbobot69
"""

    # ----------------------------------------------------------------
    # BUTTONS
    # ----------------------------------------------------------------
    # ⚡ NEW 2x2 BUTTONS - FULL WORKING
    BIMBO_START_BUTTONS = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🛠️ Help", callback_data="help"),
            InlineKeyboardButton("📊 Stats", callback_data="status"),
        ],
        [
            InlineKeyboardButton("📢 Updates", url="https://t.me/Bimbobot69"),
            InlineKeyboardButton("👥 Support", url="https://t.me/Bimbo69"),
        ],
    ])

    BIMBO_HELP_BUTTONS = InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 Home", callback_data="home"),
         InlineKeyboardButton("ℹ️ About", callback_data="about")],
        [InlineKeyboardButton("✖️ Close", callback_data="close")],
    ])

    BIMBO_ABOUT_BUTTONS = InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 Home", callback_data="home"),
         InlineKeyboardButton("❓ Help", callback_data="help")],
        [InlineKeyboardButton("✖️ Close", callback_data="close")],
    ])

    # ----------------------------------------------------------------
    # STATUS / ERRORS
    # ----------------------------------------------------------------
    BIMBO_ERROR = "<b>❌ Error:</b> <code>{}</code>"
    BIMBO_DOWNLOAD_START = "<b>📥 Downloading...</b>"
    BIMBO_UPLOAD_START = "<b>📤 Uploading to Telegram...</b>"

    BIMBO_RCHD_TG_API_LIMIT = """
<b>⚠️ File too large for Telegram</b>

Downloaded in: {} seconds
Size: {}

Sorry, files above ~2GB can't be uploaded as bot. Use split feature.
"""

    BIMBO_AFTER_SUCCESSFUL_UPLOAD_MSG = """
<b>✅ Uploaded successfully!</b>

Join: @Bimbobot69
"""

    BIMBO_AFTER_SUCCESSFUL_UPLOAD_MSG_WITH_TS = """
<b>✅ Upload Completed</b>

📥 Downloaded in: {}s
📤 Uploaded in: {}s

💾 Size: {}
⚡ Avg Speed: {}

Join: @Bimbobot69
"""

    BIMBO_SAVED_CUSTOM_THUMB_NAIL = "<b>✅ Custom thumbnail saved!</b>"
    BIMBO_DEL_ETED_CUSTOM_THUMB_NAIL = "<b>✅ Thumbnail removed.</b>"
    BIMBO_CUSTOM_CAPTION_UL_FILE = "<b>{}</b>"
    BIMBO_NO_VOID_FORMAT_FOUND = "<b>❌ Unable to process this link.</b>\n{}"
    BIMBO_REPLY_TO_MEDIA_ALBUM_TO_GEN_THUMB = "<b>Reply to an album with /generatecustomthumbnail.</b>"
    BIMBO_ERR_ONLY_TWO_MEDIA_IN_ALBUM = "<b>Album must have exactly 2 photos.</b>"
    BIMBO_CANCEL_STR = "<b>❌ Cancelled.</b>"
    BIMBO_ZIP_UPLOADED_STR = "<b>✅ Zipped and uploaded {} files in {}s.</b>"
    BIMBO_SLOW_URL_DECED = "<b>⚠️ Link too slow or unreachable.</b> Try another source."
    BIMBO_ERROR_YTDLP = "<b>❌ yt-dlp error.</b> Try again later or check the link."
    BIMBO_FORMAT_SELECTION = """
<b>🎯 Select Format</b>

Choose file type and quality:
"""
    BIMBO_SET_CUSTOM_USERNAME_PASSWORD = """
<b>🔐 Auth Required:</b>
<code>URL | filename | username | password</code>
"""
    MAINTENANCE_MSG = """
<b>🛠️ Bot is under maintenance.</b>
Please try again later. Admin @Bimbo69
"""
    JOIN_CHNL_MSG = """
<b>🔒 Join our updates channel first!</b>

Please join {} to use the bot, then tap Try Again.
"""
    RATE_LIMIT_MSG = "<b>⏳ Wait {}s more before next download.</b>"
    NOT_AUTHORIZED = "<b>❌ You're not authorized. Contact owner @Bimbo69.</b>"
    NO_VIDEO_REPLY = "<b>❌ Reply to a video/file with this command.</b>"
    PROCESSING = "<b>⚙️ Processing... please wait.</b>"
    NO_TORRENT = "<b>⚠️ Torrent support not available on this deploy (libtorrent missing).</b>"
    CLOUD_DISABLED = "<b>⚠️ This cloud upload isn't configured by admin.</b>"
    INVALID_CMD = "<b>❌ Invalid usage. Check /help.</b>"
    GDRIVE_404 = "<b>⚠️ G-Drive credentials not set. Admin: set BIMBO_GDRIVE_CREDENTIALS.</b>"
    MEGA_404 = "<b>⚠️ Mega credentials not set.</b>"
    FEATURE_PREMIUM = "<b>💎 This is a premium feature! See</b> /plan"
