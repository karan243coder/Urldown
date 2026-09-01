# -*- coding: utf-8 -*-
# BIMBO URL Bot
# Powered by BIMBO
# Support: @Bimbo69

import os
import json
import html
import asyncio
import logging
import re
import aiohttp
import hashlib
import time
from urllib.parse import urlparse, unquote

from config import Config
from pyrogram import filters, enums
from database.adduser import AddUser
from pyrogram import Client as BimboBot
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from helper_funcs.display_progress import humanbytes
from utils import check_verification, get_token
from plugins.xhamster_engine import is_xhamster as _xh_is, extract as xh_extract
from plugins.eporner_engine import is_eporner as _ep_is, extract_video as ep_extract
from plugins.terabox_engine import is_terabox as _tb_is, extract as tb_extract
from plugins.sxyprn_engine import is_sxyprn as _sxy_is, extract_video_info as sxyprn_extract
from plugins.universal_engine import (
    is_universal_candidate as _uni_ok,
    extract_video_info as universal_extract,
)
from plugins.pornhub_engine import is_pornhub as _ph_is, extract_video_info as pornhub_extract
from plugins.xvideos_engine import is_xvideos as _xv_is, extract_video_info as xvideos_extract
from plugins.redtube_engine import is_redtube as _rt_is, extract_video_info as redtube_extract
from plugins.youporn_engine import is_youporn as _yp_is, extract_video_info as youporn_extract
from plugins.tube8_engine import is_tube8 as _t8_is, extract_video_info as tube8_extract
from plugins.spankbang_engine import is_spankbang as _sb_is, extract_video_info as spankbang_extract
from plugins.wowxxx_engine import is_wowxxx as _wx_is, extract_video_info as wowxxx_extract
from plugins.xhand_engine import is_xhand as _xh2_is, extract_video_info as xhand_extract
from plugins.bang_engine import is_bang as _bg_is, extract_video_info as bang_extract
from plugins.jav_engine import is_jav as _jav_is, extract_video_info as jav_extract
from plugins.stickers import send_sticker as _send_sticker

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logging.getLogger("pyrogram").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

def generate_task_id(user_id: int) -> str:
    """Generate unique task ID for each download"""
    timestamp = str(time.time()).encode()
    random_bytes = os.urandom(8)
    data = f"{user_id}_{timestamp}_{random_bytes.hex()}".encode()
    return hashlib.md5(data).hexdigest()[:16]

DIRECT_FILE_EXTENSIONS = [
    '.mp4', '.mkv', '.mov', '.avi', '.webm', '.flv', '.m4v', '.3gp',
    '.mp3', '.m4a', '.wav', '.flac', '.aac', '.ogg', '.wma',
    '.pdf', '.zip', '.rar', '.7z', '.tar', '.gz', '.apk',
    '.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.svg',
    '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.txt',
    '.exe', '.dmg', '.iso', '.torrent'
]

PREFERRED_VIDEO_EXTS = ["mp4", "mkv", "webm"]
HLS_PROTOCOLS = {"m3u8", "m3u8_native"}


# ============================================================
#  xHamster special handling
#  Reason: xHamster ke "progressive mp4" (h264-480p etc.) URLs ab DEAD hain
#  (CDN "Wrong key" 403 deta hai) aur av1 HLS variants resolve nahi hote.
#  SIRF h264 (avc1) + audio (mp4a) wale HLS variants actually download hote
#  hain. Isliye xHamster ke liye hum:
#    - clean height-based buttons dikhate hain (144p..1080p)
#    - format_id "xh-<height>" rakhte hain -> download time pe ek HEIGHT-BASED
#      format-string use hota hai (specific format_id nahi), taaki yt-dlp
#      khud sahi (avc1+mp4a) HLS variant chun le.
# ============================================================
def is_xhamster(url: str) -> bool:
    # asli detection xhamster_engine me hai (saare domains/mirrors)
    return _xh_is(url)


def is_eporner(url: str) -> bool:
    return _ep_is(url)


def is_terabox(url: str) -> bool:
    # Terabox detection terabox_engine me hai
    return _tb_is(url)


def is_sxyprn(url: str) -> bool:
    return _sxy_is(url)


def is_pornhub(url: str) -> bool:
    return _ph_is(url)


def is_xvideos(url: str) -> bool:
    return _xv_is(url)


def is_redtube(url: str) -> bool:
    return _rt_is(url)


def is_youporn(url: str) -> bool:
    return _yp_is(url)


def is_tube8(url: str) -> bool:
    return _t8_is(url)


def is_spankbang(url: str) -> bool:
    return _sb_is(url)


def is_wowxxx(url: str) -> bool:
    return _wx_is(url)


def is_xhand(url: str) -> bool:
    return _xh2_is(url)


def is_bang(url: str) -> bool:
    return _bg_is(url)


def is_jav(url: str) -> bool:
    return _jav_is(url)


def build_terabox_keyboard(tb_info, task_id=""):
    """Build keyboard for Terabox file download"""
    inline_keyboard = []
    
    file_size = tb_info.get("size", 0)
    size_text = humanbytes(file_size) if file_size > 0 else "Unknown"
    
    # Determine file type from title
    title = tb_info.get("title", "").lower()
    is_video = any(title.endswith(ext) for ext in ['.mp4', '.mkv', '.avi', '.mov', '.webm', '.flv'])
    is_audio = any(title.endswith(ext) for ext in ['.mp3', '.m4a', '.wav', '.flac', '.aac', '.ogg'])
    
    if is_video:
        # Video file - offer both video and file options
        inline_keyboard.append([
            InlineKeyboardButton(f"🎬 Send as Video ({size_text})", callback_data=f"terabox=video|{task_id}".encode("UTF-8")),
            InlineKeyboardButton(f"📁 Send as File ({size_text})", callback_data=f"terabox=file|{task_id}".encode("UTF-8")),
        ])
    elif is_audio:
        # Audio file
        inline_keyboard.append([
            InlineKeyboardButton(f"🎵 Send as Audio ({size_text})", callback_data=f"terabox=audio|{task_id}".encode("UTF-8")),
            InlineKeyboardButton(f"📁 Send as File ({size_text})", callback_data=f"terabox=file|{task_id}".encode("UTF-8")),
        ])
    else:
        # Other files - only file option
        inline_keyboard.append([
            InlineKeyboardButton(f"📁 Send as File ({size_text})", callback_data=f"terabox=file|{task_id}".encode("UTF-8")),
        ])
    
    return InlineKeyboardMarkup(inline_keyboard)


def build_xhamster_keyboard_from_engine(xh, task_id=""):
    """Engine ke nikaale qualities se clean buttons banao."""
    inline_keyboard = []
    for q in sorted(xh.get("qualities", []), key=lambda x: -int(x["height"])):
        h = int(q["height"])
        label = "🎬 " + q.get("label", f"{h}p")
        cb_video = f"video|xh-{h}|mp4|{task_id}"
        cb_file = f"file|xh-{h}|mp4|{task_id}"
        inline_keyboard.append([
            InlineKeyboardButton(label, callback_data=cb_video.encode("UTF-8")),
            InlineKeyboardButton("📁 File", callback_data=cb_file.encode("UTF-8")),
        ])
    if xh.get("duration") is not None:
        inline_keyboard.append([
            InlineKeyboardButton("🎵 MP3 128K", callback_data=f"audio|128k|mp3|{task_id}".encode("UTF-8")),
            InlineKeyboardButton("🎧 MP3 320K", callback_data=f"audio|320k|mp3|{task_id}".encode("UTF-8")),
        ])
    if not inline_keyboard:
        inline_keyboard.append([
            InlineKeyboardButton("🎬 Send Video", callback_data=f"video|xh-720|mp4|{task_id}".encode("UTF-8")),
            InlineKeyboardButton("📁 Send File", callback_data=f"file|xh-720|mp4|{task_id}".encode("UTF-8")),
        ])
    return InlineKeyboardMarkup(inline_keyboard)


def build_eporner_keyboard_from_engine(ep, task_id=""):
    """Eporner engine qualities se clean buttons banao."""
    inline_keyboard = []
    for q in sorted(ep.get("qualities", []), key=lambda x: -int(x["height"])):
        h = int(q["height"])
        label = "🎬 " + q.get("label", f"{h}p")
        cb_video = f"video|ep-{h}|mp4|{task_id}"
        cb_file = f"file|ep-{h}|mp4|{task_id}"
        inline_keyboard.append([
            InlineKeyboardButton(label, callback_data=cb_video.encode("UTF-8")),
            InlineKeyboardButton("📁 File", callback_data=cb_file.encode("UTF-8")),
        ])
    if ep.get("duration") is not None:
        inline_keyboard.append([
            InlineKeyboardButton("🎵 MP3 128K", callback_data=f"audio|128k|mp3|{task_id}".encode("UTF-8")),
            InlineKeyboardButton("🎧 MP3 320K", callback_data=f"audio|320k|mp3|{task_id}".encode("UTF-8")),
        ])
    if not inline_keyboard:
        inline_keyboard.append([
            InlineKeyboardButton("🎬 Send Video", callback_data=f"video|ep-720|mp4|{task_id}".encode("UTF-8")),
            InlineKeyboardButton("📁 Send File", callback_data=f"file|ep-720|mp4|{task_id}".encode("UTF-8")),
        ])
    return InlineKeyboardMarkup(inline_keyboard)


def build_generic_engine_keyboard(engine_info, task_id="", prefix="custom", site_name="Video"):
    """Generic keyboard builder for all custom engines."""
    inline_keyboard = []
    for q in sorted(engine_info.get("qualities", []), key=lambda x: -int(x["height"])):
        h = int(q["height"])
        label = "🎬 " + q.get("label", f"{h}p")
        cb_video = f"video|{prefix}-{h}|mp4|{task_id}"
        cb_file = f"file|{prefix}-{h}|mp4|{task_id}"
        inline_keyboard.append([
            InlineKeyboardButton(label, callback_data=cb_video.encode("UTF-8")),
            InlineKeyboardButton("📁 File", callback_data=cb_file.encode("UTF-8")),
        ])
    if engine_info.get("duration") is not None:
        inline_keyboard.append([
            InlineKeyboardButton("🎵 MP3 128K", callback_data=f"audio|128k|mp3|{task_id}".encode("UTF-8")),
            InlineKeyboardButton("🎧 MP3 320K", callback_data=f"audio|320k|mp3|{task_id}".encode("UTF-8")),
        ])
    if not inline_keyboard:
        inline_keyboard.append([
            InlineKeyboardButton("🎬 Send Video", callback_data=f"video|{prefix}-720|mp4|{task_id}".encode("UTF-8")),
            InlineKeyboardButton("📁 Send File", callback_data=f"file|{prefix}-720|mp4|{task_id}".encode("UTF-8")),
        ])
    return InlineKeyboardMarkup(inline_keyboard)


def build_xhamster_keyboard(response_json, task_id=""):
    """xHamster ke liye clean height-based quality buttons."""
    heights = set()
    for fmt in (response_json.get("formats") or []):
        proto = (fmt.get("protocol") or "")
        h = fmt.get("height")
        vc = (fmt.get("vcodec") or "")
        # SIRF h264 (avc1) HLS variants count karo (yahi download hote hain)
        if h and proto.startswith("m3u8") and vc.lower().startswith(("avc1", "h264")):
            heights.add(int(h))
    if not heights:
        # fallback: kisi bhi HLS height
        for fmt in (response_json.get("formats") or []):
            if fmt.get("height") and (fmt.get("protocol") or "").startswith("m3u8"):
                heights.add(int(fmt["height"]))

    QLABEL = {144: "144p", 240: "240p", 360: "360p", 480: "480p (SD)",
              720: "720p (HD)", 1080: "1080p (FHD)", 1440: "1440p", 2160: "4K"}
    inline_keyboard = []
    for h in sorted(heights, reverse=True):
        label = "🎬 " + QLABEL.get(h, f"{h}p")
        # format_id "xh-<height>" -> download step ise pehchaan kar height-based
        # format-string use karega. ext hamesha mp4.
        cb_video = f"video|xh-{h}|mp4|{task_id}"
        cb_file = f"file|xh-{h}|mp4|{task_id}"
        inline_keyboard.append([
            InlineKeyboardButton(label, callback_data=cb_video.encode("UTF-8")),
            InlineKeyboardButton("📁 File", callback_data=cb_file.encode("UTF-8")),
        ])
    if response_json.get("duration") is not None:
        inline_keyboard.append([
            InlineKeyboardButton("🎵 MP3 128K", callback_data=f"audio|128k|mp3|{task_id}".encode("UTF-8")),
            InlineKeyboardButton("🎧 MP3 320K", callback_data=f"audio|320k|mp3|{task_id}".encode("UTF-8")),
        ])
    if not inline_keyboard:
        inline_keyboard.append([
            InlineKeyboardButton("🎬 Send Video", callback_data=f"video|xh-720|mp4|{task_id}".encode("UTF-8")),
            InlineKeyboardButton("📁 Send File", callback_data=f"file|xh-720|mp4|{task_id}".encode("UTF-8")),
        ])
    return InlineKeyboardMarkup(inline_keyboard)


def escape_html(text):
    return html.escape(str(text or ""), quote=False)


def trim_text(text: str, limit: int = 60) -> str:
    text = str(text or "").strip()
    return text if len(text) <= limit else text[:limit - 3] + "..."


def build_verify_markup(verify_url: str):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🧑‍💻 Verify Now", url=verify_url)],
        [InlineKeyboardButton("📘 How to Verify", url=f"{Config.BIMBO_TUTORIAL}")]
    ])


def build_direct_markup():
    cb_string_file = "{}={}={}".format("file", "DIRECT", "AUTO")
    cb_string_video = "{}={}={}".format("video", "DIRECT", "AUTO")
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("📁 File", callback_data=cb_string_file.encode("UTF-8")),
        InlineKeyboardButton("🎬 Video", callback_data=cb_string_video.encode("UTF-8"))
    ]])


def safe_filesize(fmt):
    if fmt.get("filesize"):
        return humanbytes(fmt["filesize"])
    if fmt.get("filesize_approx"):
        return f"~{humanbytes(fmt['filesize_approx'])}"
    return "?"


def clean_quality_label(fmt):
    height = fmt.get("height")
    width = fmt.get("width")
    note = fmt.get("format_note") or fmt.get("format") or "Unknown"

    if height:
        return f"{height}p"
    if width and fmt.get("height"):
        return f"{width}x{fmt.get('height')}"

    note = str(note)
    note = note.replace("video only", "").replace("audio only", "").strip()
    return note[:20] if note else "Auto"


def score_format(fmt):
    score = 0
    ext = (fmt.get("ext") or "").lower()
    protocol = (fmt.get("protocol") or "").lower()
    vcodec = (fmt.get("vcodec") or "").lower()
    acodec = (fmt.get("acodec") or "").lower()
    height = int(fmt.get("height") or 0)
    tbr = float(fmt.get("tbr") or 0)

    if vcodec and vcodec != "none":
        score += 1000
    if acodec and acodec != "none":
        score += 120
    if ext in PREFERRED_VIDEO_EXTS:
        score += 200 - (PREFERRED_VIDEO_EXTS.index(ext) * 20)
    if protocol not in HLS_PROTOCOLS:
        score += 180
    score += height
    score += int(tbr)
    return score


def select_best_video_formats(formats_list):
    grouped = {}

    for fmt in formats_list:
        format_id = fmt.get("format_id")
        ext = fmt.get("ext")
        vcodec = fmt.get("vcodec")
        if not format_id or not ext or not vcodec or vcodec == "none":
            continue

        label = clean_quality_label(fmt)
        old = grouped.get(label)
        if old is None or score_format(fmt) > score_format(old):
            grouped[label] = fmt

    selected = list(grouped.values())
    selected.sort(key=lambda x: (int(x.get("height") or 0), score_format(x)), reverse=True)
    return selected[:10]


def build_format_keyboard(response_json, task_id=""):
    inline_keyboard = []
    selected_formats = select_best_video_formats(response_json.get("formats") or [])

    for fmt in selected_formats:
        format_id = fmt.get("format_id")
        format_ext = (fmt.get("ext") or "mp4").upper()
        quality_label = clean_quality_label(fmt)
        size_label = safe_filesize(fmt)

        video_label = trim_text(f"🎬 {quality_label} • {format_ext} • {size_label}", 28)
        file_label = trim_text(f"📁 {format_ext}", 12)

        cb_string_video = f"video|{format_id}|{fmt.get('ext')}|{task_id}"
        cb_string_file = f"file|{format_id}|{fmt.get('ext')}|{task_id}"

        inline_keyboard.append([
            InlineKeyboardButton(video_label, callback_data=cb_string_video.encode("UTF-8")),
            InlineKeyboardButton(file_label, callback_data=cb_string_file.encode("UTF-8")),
        ])

    if response_json.get("duration") is not None:
        inline_keyboard.append([
            InlineKeyboardButton("🎵 MP3 64K", callback_data=f"audio|64k|mp3|{task_id}".encode("UTF-8")),
            InlineKeyboardButton("🎵 MP3 128K", callback_data=f"audio|128k|mp3|{task_id}".encode("UTF-8")),
        ])
        inline_keyboard.append([
            InlineKeyboardButton("🎧 MP3 320K", callback_data=f"audio|320k|mp3|{task_id}".encode("UTF-8"))
        ])

    if not inline_keyboard:
        format_id = response_json.get("format_id", "best")
        format_ext = response_json.get("ext", "mp4")
        inline_keyboard.append([
            InlineKeyboardButton("🎬 Send Video", callback_data=f"video|{format_id}|{format_ext}|{task_id}".encode("UTF-8")),
            InlineKeyboardButton("📁 Send File", callback_data=f"file|{format_id}|{format_ext}|{task_id}".encode("UTF-8")),
        ])

    return InlineKeyboardMarkup(inline_keyboard)


async def send_log(bot, action, user, link, extra=""):
    if not Config.BIMBO_LOG_CHANNEL or Config.BIMBO_LOG_CHANNEL == 0:
        return

    username = f"@{user.username}" if getattr(user, "username", None) else "N/A"
    first_name = escape_html(getattr(user, "first_name", None) or "User")
    user_mention = f'<a href="tg://user?id={user.id}">{first_name}</a>'

    html_text = (
        "<b>📊 New Bot Activity</b>\n\n"
        f"<b>👤 User:</b> {user_mention} (<code>{user.id}</code>)\n"
        f"<b>🔖 Username:</b> {escape_html(username)}\n"
        f"<b>⚡ Action:</b> {escape_html(action)}\n"
        f"<b>🔗 Link:</b> <code>{escape_html(link)[:1500]}</code>\n"
        f"{extra}"
    )

    try:
        await bot.send_message(
            chat_id=Config.BIMBO_LOG_CHANNEL,
            text=html_text,
            parse_mode=enums.ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception as e:
        logger.error(f"Log channel HTML error: {e}")
        try:
            plain_text = (
                f"New Bot Activity\n\n"
                f"User: {getattr(user, 'first_name', 'User')} ({user.id})\n"
                f"Username: {username}\n"
                f"Action: {action}\n"
                f"Link: {link}\n"
            )
            await bot.send_message(chat_id=Config.BIMBO_LOG_CHANNEL, text=plain_text, disable_web_page_preview=True)
        except Exception as e2:
            logger.error(f"Log channel fallback error: {e2}")


async def is_direct_download_url(url):
    parsed_url = urlparse(url)
    path = parsed_url.path.lower()

    if any(path.endswith(ext) for ext in DIRECT_FILE_EXTENSIONS):
        return True

    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            try:
                async with session.head(url, allow_redirects=True) as response:
                    content_type = response.headers.get('Content-Type', '').lower()
                    content_length = response.headers.get('Content-Length')
                    if any(ct in content_type for ct in [
                        'video/', 'audio/', 'application/octet-stream',
                        'application/zip', 'application/pdf', 'application/x-rar',
                        'image/', 'application/vnd.android.package-archive'
                    ]):
                        return True
                    if content_length and content_length.isdigit() and int(content_length) > 1024 * 1024:
                        return True
            except Exception:
                pass

            try:
                async with session.get(url, allow_redirects=True) as response:
                    content_type = response.headers.get('Content-Type', '').lower()
                    content_length = response.headers.get('Content-Length')
                    if any(ct in content_type for ct in [
                        'video/', 'audio/', 'application/octet-stream',
                        'application/zip', 'application/pdf', 'application/x-rar',
                        'image/', 'application/vnd.android.package-archive'
                    ]):
                        return True
                    if content_length and content_length.isdigit() and int(content_length) > 1024 * 1024:
                        return True
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"Direct download check failed: {e}")

    return False


def _clean_extracted_url(url: str) -> str:
    """Telegram/Markdown text se asli URL nikaalo. Logs me utm ka tukda aa raha tha."""
    url = str(url or "").strip()
    # Markdown preview/copy kabhi [text](url) bana deta hai
    m = re.search(r"\((https?://[^\s)]+)\)", url)
    if m:
        url = m.group(1)
    # Normal http URL extract
    m = re.search(r"https?://[^\s<>]+", url)
    if m:
        url = m.group(0)
    url = url.strip().strip("`\'\"<>[]()")
    url = url.replace("&amp;", "&")
    return url


def extract_url_parts(text, entities):
    youtube_dl_username = None
    youtube_dl_password = None
    file_name = None
    raw_text = text or ""
    url = raw_text

    # Sabse pehle Telegram entity se exact URL lo. Ye sabse reliable hai.
    for entity in (entities or []):
        entity_type = str(getattr(entity, "type", "")).lower()
        if "text_link" in entity_type and getattr(entity, "url", None):
            url = entity.url
            break
        elif entity_type.endswith("url") or entity_type == "url":
            o = entity.offset
            l = entity.length
            url = raw_text[o:o + l]
            break

    # Agar custom format use kiya: URL | filename | username | password
    # Sirf tab split karo jab left part me actual http ho.
    if "|" in raw_text and raw_text.strip().lower().startswith(("http://", "https://")):
        url_parts = raw_text.split("|")
        if len(url_parts) == 2:
            url = url_parts[0]
            file_name = url_parts[1]
        elif len(url_parts) == 4:
            url = url_parts[0]
            file_name = url_parts[1]
            youtube_dl_username = url_parts[2]
            youtube_dl_password = url_parts[3]

    url = _clean_extracted_url(url)
    file_name = file_name.strip() if file_name is not None else file_name
    youtube_dl_username = youtube_dl_username.strip() if youtube_dl_username is not None else youtube_dl_username
    youtube_dl_password = youtube_dl_password.strip() if youtube_dl_password is not None else youtube_dl_password

    return url, file_name, youtube_dl_username, youtube_dl_password


def get_thumb_from_ytdl_json(rjson):
    if not isinstance(rjson, dict):
        return None
    t = rjson.get("thumbnail")
    if t and isinstance(t, str) and t.startswith("http"):
        return t
    thumbs = rjson.get("thumbnails")
    if isinstance(thumbs, list) and thumbs:
        for item in reversed(thumbs):
            if isinstance(item, dict) and item.get("url") and str(item.get("url")).startswith("http"):
                return item.get("url")
    return None


async def send_buttons_with_thumbnail(
    bot,
    chat_id: int,
    text: str,
    reply_markup: InlineKeyboardMarkup,
    thumb_url: str = None,
    reply_to_message_id: int = None,
    referer: str = None,
):
    """
    Safely send quality/format buttons along with the REAL thumbnail of the link.
    Engineered for Koyeb (512 MB RAM):
    1. First tries zero-RAM direct URL photo sending via Telegram servers.
    2. If CDN requires headers/Referer or blocks direct send, downloads lightweight thumbnail (<2 MB)
       to temporary storage, sends it, and removes the temp file immediately.
    3. 100% crash-proof: falls back to regular text message if anything fails.
    """
    if thumb_url and isinstance(thumb_url, str) and thumb_url.startswith(("http://", "https://")):
        # Tier 1: Try sending direct URL via Telegram servers (0 MB RAM used)
        try:
            return await bot.send_photo(
                chat_id=chat_id,
                photo=thumb_url,
                caption=text,
                reply_markup=reply_markup,
                parse_mode=enums.ParseMode.HTML,
                reply_to_message_id=reply_to_message_id,
            )
        except Exception as e1:
            logger.debug("Direct send_photo failed (%s), trying lightweight download fallback...", e1)
            # Tier 2: Download lightweight thumbnail (< 3 MB) with Referer/headers
            tmp_thumb = None
            try:
                import tempfile
                import aiohttp

                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0.0.0 Safari/537.36",
                }
                if referer:
                    headers["Referer"] = referer

                timeout = aiohttp.ClientTimeout(total=8)
                async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
                    async with session.get(thumb_url, allow_redirects=True) as resp:
                        if resp.status == 200:
                            content = await resp.read()
                            if 100 < len(content) <= 3 * 1024 * 1024:
                                fd, tmp_thumb = tempfile.mkstemp(suffix=".jpg")
                                os.close(fd)
                                with open(tmp_thumb, "wb") as f:
                                    f.write(content)
                                result = await bot.send_photo(
                                    chat_id=chat_id,
                                    photo=tmp_thumb,
                                    caption=text,
                                    reply_markup=reply_markup,
                                    parse_mode=enums.ParseMode.HTML,
                                    reply_to_message_id=reply_to_message_id,
                                )
                                return result
            except Exception as e2:
                logger.debug("Lightweight thumb download/send failed: %s", e2)
            finally:
                if tmp_thumb and os.path.exists(tmp_thumb):
                    try:
                        os.remove(tmp_thumb)
                    except Exception:
                        pass

    # Tier 3: 100% reliable fallback (normal text message)
    return await bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=reply_markup,
        parse_mode=enums.ParseMode.HTML,
        reply_to_message_id=reply_to_message_id,
    )


@BimboBot.on_message(filters.private & ~filters.via_bot & filters.regex(pattern=".*http.*"))
async def echo(bot, update):
    # Skip torrent/magnet links — handled by torrent_download.py
    _text = (update.text or "").strip()
    if _text.startswith("magnet:") or _text.lower().endswith(".torrent"):
        return  # torrent_download.py handles these

    if not await check_verification(bot, update.from_user.id) and Config.BIMBO is True:
        verify_url = await get_token(bot, update.from_user.id, f"https://telegram.me/{Config.BIMBO_BOT_USERNAME}?start=")
        await update.reply_text(
            text=(
                "<b>🔐 Verification Required</b>\n\n"
                "Please verify first, then send your link again."
            ),
            protect_content=True,
            parse_mode=enums.ParseMode.HTML,
            reply_markup=build_verify_markup(verify_url),
        )
        return

    await AddUser(bot, update)
    imog = await update.reply_text(
        "<b>⚡ Processing your request...</b>",
        parse_mode=enums.ParseMode.HTML,
        reply_to_message_id=update.id,
    )

    url, file_name, youtube_dl_username, youtube_dl_password = extract_url_parts(update.text, update.entities)
    original_name = file_name if file_name else "Not Set"

    # ============================================================
    #  AGGREGATOR RESOLVE (qorno.com jaisi redirect sites)
    #  qorno khud video host nahi karti — /out/?l=<base64> asli site
    #  (eporner/xhamster/xozilla/etc.) pe le jaata hai. Yahan asli URL
    #  nikaal lo taaki niche ke dedicated engines / universal use kar sakein.
    # ============================================================
    try:
        import requests as _rq
        from plugins.universal_engine import _resolve_aggregator as _resolve_agg
        _pr = urlparse(url)
        if any(seg in (_pr.path.lower() + "?" + (_pr.query or "").lower())
               for seg in ("/out", "/go", "/away", "/redirect", "l=", "url=")):
            _sess = _rq.Session()
            _sess.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"})
            _resolved = await asyncio.to_thread(_resolve_agg, url, _sess)
            if _resolved and _resolved != url:
                logger.info("aggregator resolved: %s -> %s", url[:60], _resolved[:80])
                url = _resolved
    except Exception as _e:
        logger.debug("aggregator resolve skip: %s", _e)

    # 🐱 Adult-site link? -> LadyCat naughty sticker (fixed adult mood)
    try:
        _adult_kw = (
            "xhamster", "xvideos", "xnxx", "pornhub", "eporner", "redtube",
            "youporn", "tube8", "spankbang", "sxyprn", "xhand", "bang",
            "porn", "sex", "xxx", "fuck", "milf", "anal", "hentai", "adult",
            "camgirl", "nsfw", "cunt", "boobs", "nude", "18", "hqporner",
            "txxx", "hclips", "upornia", "hotmovs", "wankoz", "qorno",
            "missav", "jable", "javguru", "javbus", "javdb", "njav", "123av",
            "supjav", "netflav", "thisav", "hpjav", "javmost", "javgg",
        )
        _low = (url or "").lower()
        if any(k in _low for k in _adult_kw):
            await _send_sticker(bot, update.chat.id, mood="adult", reply_to=update.id)
    except Exception:
        pass

    await send_log(
        bot,
        "Link Received",
        update.from_user,
        url,
        f"<b>📁 Custom Name:</b> <code>{escape_html(original_name)}</code>",
    )

    # ============================================================
    #  xHamster -> apna ALAG engine pehle (yt-dlp se azaad).
    #  Sirf SINGLE VIDEO URLs ke liye quality buttons dikhao.
    #  Creator/profile/gallery/search URLs ko advanced plugin
    #  (/xhs /xhp /xhg /xh) handle karega; yaha sirf /videos/ wale.
    # ============================================================
    if is_xhamster(url):
        # Sirf single video URLs pe hi apna engine chalao
        _p = urlparse(url).path.lower()
        _is_single_video = ("/videos/" in _p) and not any(
            k in _p for k in ("/creators/", "/users/", "/pornstars/", "/channels/",
                              "/gallery", "/photos/", "/search", "/categories/",
                              "/tags/", "/models/")
        )
        if not _is_single_video:
            # Non-video xhamster URL (creator/profile/gallery/search)
            uid = update.from_user.id if update.from_user else 0
            try:
                from utils import is_admin as _ia, is_premium as _ip
                _vip = _ia(uid) or bool(await _ip(uid))
            except Exception:
                _vip = False
            if _vip:
                # AUTO-DETECT for VIP: forward to xhamster_upgrade's listing
                # (bina /xh command ke direct link pe listing dikh jayegi)
                try:
                    from plugins.xhamster_upgrade import _send_listing, _xh_type as _xh_t
                    # Normalize URL: creator/profile -> /videos-porn add
                    from plugins.xhamster_upgrade import RE_CREATOR as _RE_CR
                    _u = url.split("?")[0].split("#")[0]
                    _mcr = _RE_CR.search(_u)
                    if _mcr and "/videos" not in _p:
                        _uname = _mcr.group(1).rstrip("/")
                        _sec_m = re.search(r"/(creators|users|pornstars|channels|models|pornstar-channels)/", _u, re.I)
                        _sec = _sec_m.group(1).lower() if _sec_m else "creators"
                        if _sec in ("pornstar-channels", "channels"):
                            _sec = "channels"
                        
                        # Preserve sorting suffixes if present (longest, popular, newest, etc.)
                        _suffix = "videos"
                        for s_term in ("longest", "popular", "newest", "top-rated", "new-videos"):
                            if s_term in url.lower():
                                if s_term == "newest" or s_term == "new-videos":
                                    _suffix = "videos-new-videos"
                                else:
                                    _suffix = f"videos-{s_term}"
                                break
                        _u = f"https://xhamster46.desi/{_sec}/{_uname}/{_suffix}"
                    # Determine title
                    if "/gallery" in _p or "/photos" in _p:
                        await imog.edit(
                            "<b>🔞 xHamster Gallery link</b>\n\n"
                            "Gallery download ke liye <code>/xhg {}</code> use karo.".format(url),
                            parse_mode=enums.ParseMode.HTML, disable_web_page_preview=True,
                        )
                        return False
                    _title = "🔞 xHamster"
                    if "/search" in _p:
                        _title = f"🔞 xHamster Search"
                    elif _RE_CR.search(_u):
                        _title = "🔞 Creator Profile"
                    await imog.delete()
                    await _send_listing(bot, update, _u, title=_title)
                    return False
                except Exception as _e:
                    logger.warning(f"xh auto-list err: {_e}")
                    try:
                        await imog.edit(
                            "<b>🔞 xHamster non-video link</b>\n\n"
                            "Use <code>/xh link</code> for auto-detect.",
                            parse_mode=enums.ParseMode.HTML, disable_web_page_preview=True,
                        )
                    except Exception:
                        try:
                            await update.reply_text(
                                "<b>🔞 xHamster non-video link</b>\n\n"
                                "Use <code>/xh link</code> for auto-detect.",
                                parse_mode=enums.ParseMode.HTML, disable_web_page_preview=True,
                            )
                        except Exception:
                            pass
                    return False
            else:
                await imog.edit(
                    "<b>🔞 xHamster</b>\n\n"
                    "Yeh link direct single video nahi hai.\n"
                    "Sirf <b>single video</b> links free download hote hain (URL me <code>/videos/</code> hona chahiye).\n\n"
                    "Profile/Search/Gallery/creator pages sirf Premium/Admin ke liye. Owner @bimbobot69.",
                    parse_mode=enums.ParseMode.HTML,
                    disable_web_page_preview=True,
                )
            return False

        # Try custom engine first
        try:
            cookies_path = "cookies.txt" if os.path.exists("cookies.txt") else None
            loop = asyncio.get_event_loop()
            xh = await loop.run_in_executor(None, xh_extract, url, cookies_path)
        except Exception as e:
            logger.warning(f"xhamster engine error: {e}")
            xh = None

        if xh and xh.get("qualities"):
            logger.info("xhamster custom engine OK: %s qualities=%s", url, [q.get("height") for q in xh.get("qualities", [])])
            # button handler ke liye JSON usi jagah save karo (xh marker ke saath)
            xh_json = {
                "title": xh.get("title") or "xHamster video",
                "fulltitle": xh.get("title") or "xHamster video",
                "duration": xh.get("duration"),
                "_xhamster": True,
                "xh_qualities": {str(q["height"]): q["m3u8"] for q in xh["qualities"]},
                "xh_headers": xh.get("headers") or {},
            }
            os.makedirs(Config.BIMBO_DOWNLOAD_LOCATION, exist_ok=True)
            
            # Generate unique task ID for this download
            task_id = generate_task_id(update.from_user.id)
            
            save_ytdl_json_path = os.path.join(
                Config.BIMBO_DOWNLOAD_LOCATION, f"{update.from_user.id}_{task_id}.json")
            with open(save_ytdl_json_path, "w", encoding="utf8") as outfile:
                json.dump(xh_json, outfile, ensure_ascii=False)

            reply_markup = build_xhamster_keyboard_from_engine(xh, task_id)
            await imog.delete(True)
            thumb_url = xh.get("thumbnail") or xh.get("thumb")
            await send_buttons_with_thumbnail(
                bot=bot,
                chat_id=update.chat.id,
                text=(
                    "<b>🎯 Choose quality</b>\n"
                    "<b>✅ xHamster custom engine active</b>\n\n"
                    f"<b>📹 Title:</b> <code>{escape_html(str(xh.get('title', 'Video'))[:100])}</code>\n\n"
                    "Send a photo now to set a custom thumbnail.\n"
                    "Use /delthumbnail to remove a saved thumbnail."
                ),
                reply_markup=reply_markup,
                thumb_url=thumb_url,
                reply_to_message_id=update.id,
                referer=url,
            )
            return

        # 429 FIX: Custom engine fail hone pe yt-dlp pe MAT giro!
        # yt-dlp bhi same IP se 429 khaayega - useless fallback hai.
        # Proper error message dikhao aur ruko.
        logger.warning("xhamster custom engine FAILED (rate limited/blocked): %s", url)
        await imog.edit(
            "<b>❌ xHamster link process nahi ho paya.</b>\n\n"
            "Possible reasons:\n"
            "• Server ne temporary rate limit lagaya hai (429)\n"
            "• Video deleted ya private hai\n"
            "• Region block hai\n\n"
            "<b>Try karo:</b>\n"
            "• 1-2 minute baad dobara bhejo\n"
            "• Koi doosra xHamster link try karo\n"
            "• Link browser me khol ke check karo ki chal raha hai ya nahi",
            parse_mode=enums.ParseMode.HTML,
            disable_web_page_preview=True,
        )
        return False


    if is_eporner(url):
        from plugins.eporner_upgrade import RE_EP_PROFILE, _send_ep_listing
        _path = urlparse(url).path.lower()
        _is_ep_listing = (
            RE_EP_PROFILE.search(url)
            or "/pornstar/" in _path
            or "/tag/" in _path
            or "/search/" in _path
            or "/category/" in _path
            or "/channels/" in _path
            or "/best" in _path
            or "/top-rated" in _path
            or "/cat/" in _path
        )
        # Also detect after redirect: /pornstar/name-ID/recent/ etc.
        if not _is_ep_listing and "/pornstar/" not in _path:
            # Check if it's a non-video eporner URL (pornstar with ID suffix + tab)
            if re.search(r'/[a-zA-Z0-9-]+-[a-zA-Z0-9]{4,}/(?:recent|top-rated|longest|shortest|latest)', _path):
                _is_ep_listing = True
        if _is_ep_listing:
            try:
                await imog.delete()
                await _send_ep_listing(update, url, title="🔞 Eporner Profile / Listing")
                return False
            except Exception as _e:
                logger.warning(f"ep auto-list err: {_e}")

        try:
            cookies_path = "cookies.txt" if os.path.exists("cookies.txt") else None
            loop = asyncio.get_event_loop()
            ep = await loop.run_in_executor(None, ep_extract, url, cookies_path)
        except Exception as e:
            logger.warning(f"eporner engine error: {e}")
            ep = None

        if ep and ep.get("qualities"):
            logger.info("eporner custom engine OK: %s qualities=%s", url, [q.get("height") for q in ep.get("qualities", [])])
            # Safety: replace bad titles (Age Verification etc.) with URL-based title
            _ep_title = ep.get("title") or "Eporner video"
            _bad_words = ["age verification", "access denied", "please verify", "eporner age"]
            if any(bw in _ep_title.lower() for bw in _bad_words) or len(_ep_title.strip()) < 3:
                try:
                    _slug = urlparse(url).path.rstrip('/').split('/')[-1]
                    _slug = unquote(_slug).replace('-', ' ').strip()
                    if _slug and len(_slug) > 3:
                        _ep_title = _slug.title()
                    else:
                        _ep_title = "Eporner video"
                except Exception:
                    _ep_title = "Eporner video"
                logger.info("eporner: replaced bad title with: %s", _ep_title)
            ep_json = {
                "title": _ep_title,
                "fulltitle": _ep_title,
                "duration": ep.get("duration"),
                "_eporner": True,
                "ep_qualities": {str(q["height"]): q["url"] for q in ep["qualities"]},
                "ep_headers": ep.get("headers") or {},
            }
            os.makedirs(Config.BIMBO_DOWNLOAD_LOCATION, exist_ok=True)
            task_id = generate_task_id(update.from_user.id)
            save_ytdl_json_path = os.path.join(
                Config.BIMBO_DOWNLOAD_LOCATION, f"{update.from_user.id}_{task_id}.json")
            with open(save_ytdl_json_path, "w", encoding="utf8") as outfile:
                json.dump(ep_json, outfile, ensure_ascii=False)

            reply_markup = build_eporner_keyboard_from_engine(ep, task_id)
            await imog.delete(True)
            thumb_url = ep.get("thumbnail") or ep.get("thumb")
            await send_buttons_with_thumbnail(
                bot=bot,
                chat_id=update.chat.id,
                text=(
                    "<b>🎯 Choose quality</b>\n"
                    "<b>✅ Eporner custom engine active</b>\n\n"
                    f"<b>📹 Title:</b> <code>{escape_html(str(ep.get('title', 'Video'))[:100])}</code>\n\n"
                    "Send a photo now to set a custom thumbnail.\n"
                    "Use /delthumbnail to remove a saved thumbnail."
                ),
                reply_markup=reply_markup,
                thumb_url=thumb_url,
                reply_to_message_id=update.id,
                referer=url,
            )
            return

        logger.error("eporner custom engine FAILED, not using yt-dlp info fallback: %s", url)
        await imog.edit(
            "<b>❌ Eporner custom engine link parse nahi kar paya.</b>\n\n"
            "Please check URL or try again.",
            parse_mode=enums.ParseMode.HTML,
            disable_web_page_preview=True,
        )
        return False


    # ============================================================
    #  Terabox -> custom engine for Terabox share links
    #  Extracts download URL and shows file info with download options
    # ============================================================
    if is_terabox(url):
        try:
            await imog.edit("<b>🔍 Extracting Terabox file info...</b>", parse_mode=enums.ParseMode.HTML)
            loop = asyncio.get_event_loop()
            tb_info = await loop.run_in_executor(None, tb_extract, url)
        except Exception as e:
            logger.warning(f"terabox engine error: {e}")
            tb_info = None

        if tb_info and tb_info.get("download_url"):
            logger.info("terabox engine OK: %s title=%s size=%s", url, tb_info.get("title"), tb_info.get("size"))
            
            # Save Terabox info to JSON for download handler
            tb_json = {
                "title": tb_info.get("title") or "terabox_file",
                "fulltitle": tb_info.get("title") or "terabox_file",
                "_terabox": True,
                "tb_download_url": tb_info.get("download_url"),
                "tb_direct_url": tb_info.get("direct_url"),
                "tb_headers": tb_info.get("headers") or {},
                "tb_size": tb_info.get("size", 0),
                "tb_share_url": tb_info.get("share_url"),
            }
            os.makedirs(Config.BIMBO_DOWNLOAD_LOCATION, exist_ok=True)
            
            # Generate unique task ID for this download
            task_id = generate_task_id(update.from_user.id)
            
            save_ytdl_json_path = os.path.join(
                Config.BIMBO_DOWNLOAD_LOCATION, f"{update.from_user.id}_{task_id}.json")
            with open(save_ytdl_json_path, "w", encoding="utf8") as outfile:
                json.dump(tb_json, outfile, ensure_ascii=False)

            reply_markup = build_terabox_keyboard(tb_info, task_id)
            
            file_size = tb_info.get("size", 0)
            size_text = humanbytes(file_size) if file_size > 0 else "Unknown"
            file_title = escape_html(tb_info.get("title", "Unknown"))
            
            await imog.delete(True)
            thumb_url = tb_info.get("thumbnail") or tb_info.get("thumb")
            await send_buttons_with_thumbnail(
                bot=bot,
                chat_id=update.chat.id,
                text=(
                    f"<b>✅ Terabox file detected</b>\n\n"
                    f"<b>📁 File:</b> <code>{file_title}</code>\n"
                    f"<b>📦 Size:</b> {size_text}\n\n"
                    f"<b>🎯 Choose download option</b>\n\n"
                    "Send a photo now to set a custom thumbnail.\n"
                    "Use /delthumbnail to remove a saved thumbnail."
                ),
                reply_markup=reply_markup,
                thumb_url=thumb_url,
                reply_to_message_id=update.id,
                referer=url,
            )
            return

        # Terabox engine failed
        logger.error("terabox engine FAILED: %s", url)
        await imog.edit(
            "<b>❌ Terabox link parse nahi kar paya.</b>\n\n"
            "Possible reasons:\n"
            "• Link expired or invalid\n"
            "• File is password protected\n"
            "• Terabox server issue\n\n"
            "Please check the link and try again.\n"
            "Make sure the link is accessible in your browser.",
            parse_mode=enums.ParseMode.HTML,
            disable_web_page_preview=True,
        )
        return False

    # ============================================================
    #  Custom Engines for Adult Sites
    #  Sxyprn, Pornhub, XVideos, RedTube, YouPorn, Tube8, SpankBang
    # ============================================================
    
    # Sxyprn Handler
    if is_sxyprn(url):
        try:
            sxy_info = await asyncio.to_thread(sxyprn_extract, url)
            if sxy_info and sxy_info.get("qualities"):
                logger.info("sxyprn custom engine OK: %s", url)
                sxy_json = {
                    "title": sxy_info.get("title") or "Sxyprn Video",
                    "fulltitle": sxy_info.get("title") or "Sxyprn Video",
                    "duration": sxy_info.get("duration"),
                    "_sxyprn": True,
                    "sxyprn_qualities": {str(q["height"]): q["url"] for q in sxy_info["qualities"]},
                    "sxyprn_headers": sxy_info.get("headers") or {},
                }
                os.makedirs(Config.BIMBO_DOWNLOAD_LOCATION, exist_ok=True)
                task_id = generate_task_id(update.from_user.id)
                save_ytdl_json_path = os.path.join(
                    Config.BIMBO_DOWNLOAD_LOCATION, f"{update.from_user.id}_{task_id}.json")
                with open(save_ytdl_json_path, "w", encoding="utf8") as outfile:
                    json.dump(sxy_json, outfile, ensure_ascii=False)
                
                reply_markup = build_generic_engine_keyboard(sxy_info, task_id, "sxy", "Sxyprn")
                await imog.delete(True)
                thumb_url = sxy_info.get("thumbnail") or sxy_info.get("thumb")
                await send_buttons_with_thumbnail(
                    bot=bot,
                    chat_id=update.chat.id,
                    text=f"<b>🎯 Sxyprn video detected</b>\n\n<b>📹 Title:</b> {escape_html(sxy_info.get('title', 'Unknown')[:100])}\n\nChoose quality:",
                    reply_markup=reply_markup,
                    thumb_url=thumb_url,
                    reply_to_message_id=update.id,
                    referer=url,
                )
                return
        except Exception as e:
            logger.error(f"Sxyprn engine error: {e}")

    # Pornhub Handler
    if is_pornhub(url):
        try:
            loop = asyncio.get_event_loop()
            ph_info = await asyncio.to_thread(pornhub_extract, url)
            if ph_info and ph_info.get("qualities"):
                logger.info("pornhub custom engine OK: %s", url)
                ph_json = {
                    "title": ph_info.get("title") or "Pornhub Video",
                    "fulltitle": ph_info.get("title") or "Pornhub Video",
                    "duration": ph_info.get("duration"),
                    "_pornhub": True,
                    "pornhub_qualities": {str(q["height"]): q["url"] for q in ph_info["qualities"]},
                    "pornhub_headers": ph_info.get("headers") or {},
                }
                os.makedirs(Config.BIMBO_DOWNLOAD_LOCATION, exist_ok=True)
                task_id = generate_task_id(update.from_user.id)
                save_ytdl_json_path = os.path.join(
                    Config.BIMBO_DOWNLOAD_LOCATION, f"{update.from_user.id}_{task_id}.json")
                with open(save_ytdl_json_path, "w", encoding="utf8") as outfile:
                    json.dump(ph_json, outfile, ensure_ascii=False)
                
                reply_markup = build_generic_engine_keyboard(ph_info, task_id, "ph", "Pornhub")
                await imog.delete(True)
                thumb_url = ph_info.get("thumbnail") or ph_info.get("thumb")
                await send_buttons_with_thumbnail(
                    bot=bot,
                    chat_id=update.chat.id,
                    text=f"<b>🎯 Pornhub video detected</b>\n\n<b>📹 Title:</b> {escape_html(ph_info.get('title', 'Unknown')[:100])}\n\nChoose quality:",
                    reply_markup=reply_markup,
                    thumb_url=thumb_url,
                    reply_to_message_id=update.id,
                    referer=url,
                )
                return
        except Exception as e:
            logger.error(f"Pornhub engine error: {e}")

    # XVideos Handler
    if is_xvideos(url):
        try:
            loop = asyncio.get_event_loop()
            xv_info = await asyncio.to_thread(xvideos_extract, url)
            if xv_info and xv_info.get("qualities"):
                logger.info("xvideos custom engine OK: %s", url)
                xv_json = {
                    "title": xv_info.get("title") or "XVideos Video",
                    "fulltitle": xv_info.get("title") or "XVideos Video",
                    "duration": xv_info.get("duration"),
                    "_xvideos": True,
                    "xvideos_qualities": {str(q["height"]): q["url"] for q in xv_info["qualities"]},
                    "xvideos_headers": xv_info.get("headers") or {},
                }
                os.makedirs(Config.BIMBO_DOWNLOAD_LOCATION, exist_ok=True)
                task_id = generate_task_id(update.from_user.id)
                save_ytdl_json_path = os.path.join(
                    Config.BIMBO_DOWNLOAD_LOCATION, f"{update.from_user.id}_{task_id}.json")
                with open(save_ytdl_json_path, "w", encoding="utf8") as outfile:
                    json.dump(xv_json, outfile, ensure_ascii=False)
                
                reply_markup = build_generic_engine_keyboard(xv_info, task_id, "xv", "XVideos")
                await imog.delete(True)
                thumb_url = xv_info.get("thumbnail") or xv_info.get("thumb")
                await send_buttons_with_thumbnail(
                    bot=bot,
                    chat_id=update.chat.id,
                    text=f"<b>🎯 XVideos video detected</b>\n\n<b>📹 Title:</b> {escape_html(xv_info.get('title', 'Unknown')[:100])}\n\nChoose quality:",
                    reply_markup=reply_markup,
                    thumb_url=thumb_url,
                    reply_to_message_id=update.id,
                    referer=url,
                )
                return
        except Exception as e:
            logger.error(f"XVideos engine error: {e}")

    # RedTube Handler
    if is_redtube(url):
        try:
            loop = asyncio.get_event_loop()
            rt_info = await asyncio.to_thread(redtube_extract, url)
            if rt_info and rt_info.get("qualities"):
                logger.info("redtube custom engine OK: %s", url)
                rt_json = {
                    "title": rt_info.get("title") or "RedTube Video",
                    "fulltitle": rt_info.get("title") or "RedTube Video",
                    "duration": rt_info.get("duration"),
                    "_redtube": True,
                    "redtube_qualities": {str(q["height"]): q["url"] for q in rt_info["qualities"]},
                    "redtube_headers": rt_info.get("headers") or {},
                }
                os.makedirs(Config.BIMBO_DOWNLOAD_LOCATION, exist_ok=True)
                task_id = generate_task_id(update.from_user.id)
                save_ytdl_json_path = os.path.join(
                    Config.BIMBO_DOWNLOAD_LOCATION, f"{update.from_user.id}_{task_id}.json")
                with open(save_ytdl_json_path, "w", encoding="utf8") as outfile:
                    json.dump(rt_json, outfile, ensure_ascii=False)
                
                reply_markup = build_generic_engine_keyboard(rt_info, task_id, "rt", "RedTube")
                await imog.delete(True)
                thumb_url = rt_info.get("thumbnail") or rt_info.get("thumb")
                await send_buttons_with_thumbnail(
                    bot=bot,
                    chat_id=update.chat.id,
                    text=f"<b>🎯 RedTube video detected</b>\n\n<b>📹 Title:</b> {escape_html(rt_info.get('title', 'Unknown')[:100])}\n\nChoose quality:",
                    reply_markup=reply_markup,
                    thumb_url=thumb_url,
                    reply_to_message_id=update.id,
                    referer=url,
                )
                return
        except Exception as e:
            logger.error(f"RedTube engine error: {e}")

    # YouPorn Handler
    if is_youporn(url):
        try:
            loop = asyncio.get_event_loop()
            yp_info = await asyncio.to_thread(youporn_extract, url)
            if yp_info and yp_info.get("qualities"):
                logger.info("youporn custom engine OK: %s", url)
                yp_json = {
                    "title": yp_info.get("title") or "YouPorn Video",
                    "fulltitle": yp_info.get("title") or "YouPorn Video",
                    "duration": yp_info.get("duration"),
                    "_youporn": True,
                    "youporn_qualities": {str(q["height"]): q["url"] for q in yp_info["qualities"]},
                    "youporn_headers": yp_info.get("headers") or {},
                }
                os.makedirs(Config.BIMBO_DOWNLOAD_LOCATION, exist_ok=True)
                task_id = generate_task_id(update.from_user.id)
                save_ytdl_json_path = os.path.join(
                    Config.BIMBO_DOWNLOAD_LOCATION, f"{update.from_user.id}_{task_id}.json")
                with open(save_ytdl_json_path, "w", encoding="utf8") as outfile:
                    json.dump(yp_json, outfile, ensure_ascii=False)
                
                reply_markup = build_generic_engine_keyboard(yp_info, task_id, "yp", "YouPorn")
                await imog.delete(True)
                thumb_url = yp_info.get("thumbnail") or yp_info.get("thumb")
                await send_buttons_with_thumbnail(
                    bot=bot,
                    chat_id=update.chat.id,
                    text=f"<b>🎯 YouPorn video detected</b>\n\n<b>📹 Title:</b> {escape_html(yp_info.get('title', 'Unknown')[:100])}\n\nChoose quality:",
                    reply_markup=reply_markup,
                    thumb_url=thumb_url,
                    reply_to_message_id=update.id,
                    referer=url,
                )
                return
        except Exception as e:
            logger.error(f"YouPorn engine error: {e}")

    # Tube8 Handler
    if is_tube8(url):
        try:
            loop = asyncio.get_event_loop()
            t8_info = await asyncio.to_thread(tube8_extract, url)
            if t8_info and t8_info.get("qualities"):
                logger.info("tube8 custom engine OK: %s", url)
                t8_json = {
                    "title": t8_info.get("title") or "Tube8 Video",
                    "fulltitle": t8_info.get("title") or "Tube8 Video",
                    "duration": t8_info.get("duration"),
                    "_tube8": True,
                    "tube8_qualities": {str(q["height"]): q["url"] for q in t8_info["qualities"]},
                    "tube8_headers": t8_info.get("headers") or {},
                }
                os.makedirs(Config.BIMBO_DOWNLOAD_LOCATION, exist_ok=True)
                task_id = generate_task_id(update.from_user.id)
                save_ytdl_json_path = os.path.join(
                    Config.BIMBO_DOWNLOAD_LOCATION, f"{update.from_user.id}_{task_id}.json")
                with open(save_ytdl_json_path, "w", encoding="utf8") as outfile:
                    json.dump(t8_json, outfile, ensure_ascii=False)
                
                reply_markup = build_generic_engine_keyboard(t8_info, task_id, "t8", "Tube8")
                await imog.delete(True)
                thumb_url = t8_info.get("thumbnail") or t8_info.get("thumb")
                await send_buttons_with_thumbnail(
                    bot=bot,
                    chat_id=update.chat.id,
                    text=f"<b>🎯 Tube8 video detected</b>\n\n<b>📹 Title:</b> {escape_html(t8_info.get('title', 'Unknown')[:100])}\n\nChoose quality:",
                    reply_markup=reply_markup,
                    thumb_url=thumb_url,
                    reply_to_message_id=update.id,
                    referer=url,
                )
                return
        except Exception as e:
            logger.error(f"Tube8 engine error: {e}")

    # SpankBang Handler
    if is_spankbang(url):
        try:
            loop = asyncio.get_event_loop()
            sb_info = await asyncio.to_thread(spankbang_extract, url)
            if sb_info and sb_info.get("qualities"):
                logger.info("spankbang custom engine OK: %s", url)
                sb_json = {
                    "title": sb_info.get("title") or "SpankBang Video",
                    "fulltitle": sb_info.get("title") or "SpankBang Video",
                    "duration": sb_info.get("duration"),
                    "_spankbang": True,
                    "spankbang_qualities": {str(q["height"]): q["url"] for q in sb_info["qualities"]},
                    "spankbang_headers": sb_info.get("headers") or {},
                }
                os.makedirs(Config.BIMBO_DOWNLOAD_LOCATION, exist_ok=True)
                task_id = generate_task_id(update.from_user.id)
                save_ytdl_json_path = os.path.join(
                    Config.BIMBO_DOWNLOAD_LOCATION, f"{update.from_user.id}_{task_id}.json")
                with open(save_ytdl_json_path, "w", encoding="utf8") as outfile:
                    json.dump(sb_json, outfile, ensure_ascii=False)
                
                reply_markup = build_generic_engine_keyboard(sb_info, task_id, "sb", "SpankBang")
                await imog.delete(True)
                thumb_url = sb_info.get("thumbnail") or sb_info.get("thumb")
                await send_buttons_with_thumbnail(
                    bot=bot,
                    chat_id=update.chat.id,
                    text=f"<b>🎯 SpankBang video detected</b>\n\n<b>📹 Title:</b> {escape_html(sb_info.get('title', 'Unknown')[:100])}\n\nChoose quality:",
                    reply_markup=reply_markup,
                    thumb_url=thumb_url,
                    reply_to_message_id=update.id,
                    referer=url,
                )
                return
        except Exception as e:
            logger.error(f"SpankBang engine error: {e}")

    # Wow.xxx Handler
    if is_wowxxx(url):
        try:
            loop = asyncio.get_event_loop()
            wx_info = await asyncio.to_thread(wowxxx_extract, url)
            if wx_info and wx_info.get("qualities"):
                logger.info("wowxxx custom engine OK: %s", url)
                wx_json = {
                    "title": wx_info.get("title") or "Wow.xxx Video",
                    "fulltitle": wx_info.get("title") or "Wow.xxx Video",
                    "duration": wx_info.get("duration"),
                    "_wowxxx": True,
                    "wowxxx_qualities": {str(q["height"]): q["url"] for q in wx_info["qualities"]},
                    "wowxxx_headers": wx_info.get("headers") or {},
                }
                os.makedirs(Config.BIMBO_DOWNLOAD_LOCATION, exist_ok=True)
                task_id = generate_task_id(update.from_user.id)
                save_ytdl_json_path = os.path.join(
                    Config.BIMBO_DOWNLOAD_LOCATION, f"{update.from_user.id}_{task_id}.json")
                with open(save_ytdl_json_path, "w", encoding="utf8") as outfile:
                    json.dump(wx_json, outfile, ensure_ascii=False)
                
                reply_markup = build_generic_engine_keyboard(wx_info, task_id, "wx", "Wow.xxx")
                await imog.delete(True)
                thumb_url = wx_info.get("thumbnail") or wx_info.get("thumb")
                await send_buttons_with_thumbnail(
                    bot=bot,
                    chat_id=update.chat.id,
                    text=f"<b>🎯 Wow.xxx video detected</b>\n\n<b>📹 Title:</b> {escape_html(wx_info.get('title', 'Unknown')[:100])}\n\nChoose quality:",
                    reply_markup=reply_markup,
                    thumb_url=thumb_url,
                    reply_to_message_id=update.id,
                    referer=url,
                )
                return
        except Exception as e:
            logger.error(f"Wow.xxx engine error: {e}")

    # Xhand.com Handler
    if is_xhand(url):
        try:
            loop = asyncio.get_event_loop()
            xh_info = await asyncio.to_thread(xhand_extract, url)
            if xh_info and xh_info.get("qualities"):
                logger.info("xhand custom engine OK: %s", url)
                xh_json = {
                    "title": xh_info.get("title") or "Xhand Video",
                    "fulltitle": xh_info.get("title") or "Xhand Video",
                    "duration": xh_info.get("duration"),
                    "_xhand": True,
                    "xhand_qualities": {str(q["height"]): q["url"] for q in xh_info["qualities"]},
                    "xhand_headers": xh_info.get("headers") or {},
                }
                os.makedirs(Config.BIMBO_DOWNLOAD_LOCATION, exist_ok=True)
                task_id = generate_task_id(update.from_user.id)
                save_ytdl_json_path = os.path.join(
                    Config.BIMBO_DOWNLOAD_LOCATION, f"{update.from_user.id}_{task_id}.json")
                with open(save_ytdl_json_path, "w", encoding="utf8") as outfile:
                    json.dump(xh_json, outfile, ensure_ascii=False)
                
                reply_markup = build_generic_engine_keyboard(xh_info, task_id, "xh", "Xhand")
                await imog.delete(True)
                thumb_url = xh_info.get("thumbnail") or xh_info.get("thumb")
                await send_buttons_with_thumbnail(
                    bot=bot,
                    chat_id=update.chat.id,
                    text=f"<b>🎯 Xhand.com video detected</b>\n\n<b>📹 Title:</b> {escape_html(xh_info.get('title', 'Unknown')[:100])}\n\nChoose quality:",
                    reply_markup=reply_markup,
                    thumb_url=thumb_url,
                    reply_to_message_id=update.id,
                    referer=url,
                )
                return
        except Exception as e:
            logger.error(f"Xhand engine error: {e}")

    # Bang.com Handler
    if is_bang(url):
        try:
            loop = asyncio.get_event_loop()
            bg_info = await asyncio.to_thread(bang_extract, url)
            if bg_info and bg_info.get("qualities"):
                logger.info("bang custom engine OK: %s", url)
                bg_json = {
                    "title": bg_info.get("title") or "Bang.com Video",
                    "fulltitle": bg_info.get("title") or "Bang.com Video",
                    "duration": bg_info.get("duration"),
                    "_bang": True,
                    "bang_qualities": {str(q["height"]): q["url"] for q in bg_info["qualities"]},
                    "bang_headers": bg_info.get("headers") or {},
                }
                os.makedirs(Config.BIMBO_DOWNLOAD_LOCATION, exist_ok=True)
                task_id = generate_task_id(update.from_user.id)
                save_ytdl_json_path = os.path.join(
                    Config.BIMBO_DOWNLOAD_LOCATION, f"{update.from_user.id}_{task_id}.json")
                with open(save_ytdl_json_path, "w", encoding="utf8") as outfile:
                    json.dump(bg_json, outfile, ensure_ascii=False)
                
                reply_markup = build_generic_engine_keyboard(bg_info, task_id, "bg", "Bang")
                await imog.delete(True)
                thumb_url = bg_info.get("thumbnail") or bg_info.get("thumb")
                await send_buttons_with_thumbnail(
                    bot=bot,
                    chat_id=update.chat.id,
                    text=f"<b>🎯 Bang.com video detected</b>\n\n<b>📹 Title:</b> {escape_html(bg_info.get('title', 'Unknown')[:100])}\n\nChoose quality:",
                    reply_markup=reply_markup,
                    thumb_url=thumb_url,
                    reply_to_message_id=update.id,
                    referer=url,
                )
                return
        except Exception as e:
            logger.error(f"Bang engine error: {e}")

    # ============================================================
    #  JAV hosts (MissAV / Jable / 123AV / NJAV / mirrors)
    #  HLS-native download — preview clips skip, actual video file.
    # ============================================================
    if is_jav(url):
        try:
            jav_info = await asyncio.to_thread(jav_extract, url)
            if jav_info and jav_info.get("qualities"):
                logger.info("jav custom engine OK: %s qualities=%s", url, [q.get("height") for q in jav_info.get("qualities", [])])
                jav_json = {
                    "title": jav_info.get("title") or "JAV Video",
                    "fulltitle": jav_info.get("title") or "JAV Video",
                    "duration": jav_info.get("duration"),
                    "_jav": True,
                    "jav_qualities": {str(q["height"]): q["url"] for q in jav_info["qualities"]},
                    "jav_headers": jav_info.get("headers") or {},
                }
                os.makedirs(Config.BIMBO_DOWNLOAD_LOCATION, exist_ok=True)
                task_id = generate_task_id(update.from_user.id)
                save_ytdl_json_path = os.path.join(
                    Config.BIMBO_DOWNLOAD_LOCATION, f"{update.from_user.id}_{task_id}.json")
                with open(save_ytdl_json_path, "w", encoding="utf8") as outfile:
                    json.dump(jav_json, outfile, ensure_ascii=False)
                reply_markup = build_generic_engine_keyboard(jav_info, task_id, "jav", "JAV")
                await imog.delete(True)
                thumb_url = jav_info.get("thumbnail") or jav_info.get("thumb")
                await send_buttons_with_thumbnail(
                    bot=bot,
                    chat_id=update.chat.id,
                    text=(
                        f"<b>🎯 JAV video detected</b>\n\n"
                        f"<b>📹 Title:</b> {escape_html((jav_info.get('title') or 'Video')[:100])}\n\n"
                        "Choose quality:"
                    ),
                    reply_markup=reply_markup,
                    thumb_url=thumb_url,
                    reply_to_message_id=update.id,
                    referer=url,
                )
                return
        except Exception as e:
            logger.error(f"JAV engine error: {e}")

    # ============================================================
    #  UNIVERSAL Extractor (koi bhi website) — SCRAPE-FIRST fallback
    #  Kisi dedicated engine se match nahi hua -> page se seedha
    #  video (.mp4/.m3u8/og:video/iframe) nikaalne ki koshish karo.
    #  Mile to generic keyboard dikhao; na mile to niche yt-dlp try hoga.
    # ============================================================
    if _uni_ok(url) and not is_jav(url):
        try:
            uni_info = await asyncio.to_thread(universal_extract, url)
            if uni_info and uni_info.get("qualities"):
                logger.info("universal engine OK: %s", url)
                uni_json = {
                    "title": uni_info.get("title") or "Video",
                    "fulltitle": uni_info.get("title") or "Video",
                    "duration": uni_info.get("duration"),
                    "_universal": True,
                    "universal_qualities": {str(q["height"]): q["url"] for q in uni_info["qualities"]},
                    "universal_headers": uni_info.get("headers") or {},
                }
                os.makedirs(Config.BIMBO_DOWNLOAD_LOCATION, exist_ok=True)
                task_id = generate_task_id(update.from_user.id)
                save_ytdl_json_path = os.path.join(
                    Config.BIMBO_DOWNLOAD_LOCATION, f"{update.from_user.id}_{task_id}.json")
                with open(save_ytdl_json_path, "w", encoding="utf8") as outfile:
                    json.dump(uni_json, outfile, ensure_ascii=False)

                reply_markup = build_generic_engine_keyboard(uni_info, task_id, "uni", "Video")
                await imog.delete(True)
                thumb_url = uni_info.get("thumbnail") or uni_info.get("thumb")
                await send_buttons_with_thumbnail(
                    bot=bot,
                    chat_id=update.chat.id,
                    text=(f"<b>🎯 Video detected</b>\n\n<b>📹 Title:</b> "
                          f"{escape_html((uni_info.get('title') or 'Video')[:100])}\n\nChoose quality:"),
                    reply_markup=reply_markup,
                    thumb_url=thumb_url,
                    reply_to_message_id=update.id,
                    referer=url,
                )
                return
        except Exception as e:
            logger.error(f"Universal engine error: {e}")

    command_to_exec = [
        "yt-dlp",
        "--no-warnings",
        "--geo-bypass",
        "--add-header", "User-Agent:Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "-j",
        url,
    ]

    if Config.BIMBO_HTTP_PROXY != "":
        command_to_exec.extend(["--proxy", Config.BIMBO_HTTP_PROXY])
    if os.path.exists("cookies.txt"):
        command_to_exec.extend(["--cookies", "cookies.txt"])
    if youtube_dl_username is not None:
        command_to_exec.extend(["--username", youtube_dl_username])
    if youtube_dl_password is not None:
        command_to_exec.extend(["--password", youtube_dl_password])

    try:
        process = await asyncio.create_subprocess_exec(
            *command_to_exec,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        await imog.edit("**ERROR:** `yt-dlp` install nahi hai. Requirements install/deploy dobara karo.")
        return False

    stdout, stderr = await process.communicate()
    e_response = stderr.decode(errors="ignore").strip()
    t_response = stdout.decode(errors="ignore").strip()

    if process.returncode != 0:
        await imog.edit("<b>⚠️ yt-dlp failed, checking direct link...</b>", parse_mode=enums.ParseMode.HTML)
        try:
            if await is_direct_download_url(url):
                await imog.delete(True)
                await bot.send_message(
                    chat_id=update.chat.id,
                    text="<b>✅ Direct link detected</b>\nChoose output type:",
                    reply_markup=build_direct_markup(),
                    parse_mode=enums.ParseMode.HTML,
                    reply_to_message_id=update.id,
                )
                return
        except Exception as e:
            logger.error(f"Direct download check error: {e}")

        if "primarily used for piracy" in e_response or "Piracy" in e_response:
            error_message = (
                "<b>⚠️ Piracy Website Detected</b>\n\n"
                "Yeh website piracy ke liye use hoti hai aur yt-dlp isko support nahi karta.\n\n"
                "Kripya koi aur website try karein ya direct video link bhejein."
            )
        elif "This video is only available for registered users." in e_response or "Sign in" in e_response:
            error_message = (
                "<b>🔐 Login required for this link</b>\n\n"
                "Use this format:\n"
                "<code>URL | filename | username | password</code>\n\n"
                "Or add <code>cookies.txt</code> to the bot files."
            )
        elif "Unsupported URL" in e_response or "No supported extractor" in e_response:
            error_message = (
                "<b>❌ Unsupported URL</b>\n\n"
                "Yeh URL supported nahi hai.\n\n"
                "Supported websites:\n"
                "• YouTube\n"
                "• xHamster\n"
                "• Eporner\n"
                "• Pornhub\n"
                "• XVideos\n"
                "• RedTube\n"
                "• YouPorn\n"
                "• Tube8\n"
                "• SpankBang\n"
                "• Sxyprn\n"
                "• Wow.xxx\n"
                "• Xhand\n"
                "• Bang.com\n"
                "• MissAV / Jable / 123AV / NJAV (JAV)\n"
                "• Instagram\n"
                "• Twitter\n"
                "• Facebook\n"
                "• Aur 1000+ aur websites\n\n"
                "ℹ️ Universal extractor bhi try karta hai (koi bhi site), par is\n"
                "link pe video nahi mili — shayad login/DRM/heavy-JS protected hai.\n\n"
                "Kripya valid direct video link ya doosri site try karein."
            )
        elif "Private video" in e_response or "deleted" in e_response:
            error_message = (
                "<b>🚫 Video Unavailable</b>\n\n"
                "Yeh video private hai ya delete ho chuki hai."
            )
        elif "Age-restricted" in e_response or "18+" in e_response:
            error_message = (
                "<b>🔞 Age-Restricted Content</b>\n\n"
                "Yeh video age-restricted hai.\n"
                "Login format use karein:\n"
                "<code>URL | filename | username | password</code>"
            )
        else:
            actual_error = escape_html(e_response.split('\n')[0][:250] or "Invalid or unsupported URL")
            error_message = (
                "<b>❌ Download Failed</b>\n\n"
                f"<b>Reason:</b> <code>{actual_error}</code>\n\n"
                "Kripya valid URL bhejein ya baad me try karein."
            )

        await bot.send_message(
            chat_id=update.chat.id,
            text=error_message,
            disable_web_page_preview=True,
            parse_mode=enums.ParseMode.HTML,
            reply_to_message_id=update.id,
        )
        await imog.delete(True)
        return False

    if t_response:
        first_json_line = next((line for line in t_response.splitlines() if line.strip()), "")
        response_json = json.loads(first_json_line)

        os.makedirs(Config.BIMBO_DOWNLOAD_LOCATION, exist_ok=True)
        
        # Generate unique task ID for this download
        task_id = generate_task_id(update.from_user.id)
        
        # Save JSON with task_id
        save_ytdl_json_path = os.path.join(Config.BIMBO_DOWNLOAD_LOCATION, f"{update.from_user.id}_{task_id}.json")
        with open(save_ytdl_json_path, "w", encoding="utf8") as outfile:
            json.dump(response_json, outfile, ensure_ascii=False)

        if is_xhamster(url):
            reply_markup = build_xhamster_keyboard(response_json, task_id)
        else:
            reply_markup = build_format_keyboard(response_json, task_id)
        await imog.delete(True)
        thumb_url = get_thumb_from_ytdl_json(response_json)
        await send_buttons_with_thumbnail(
            bot=bot,
            chat_id=update.chat.id,
            text=(
                "<b>🎯 Choose format</b>\n\n"
                f"<b>📹 Title:</b> <code>{escape_html(str(response_json.get('title', 'Video'))[:100])}</code>\n\n"
                "Send photo now for custom thumbnail.\n"
                "Use /delthumbnail to remove saved thumbnail.\n\n"
                "<b>🔐 Login format:</b>\n"
                "<code>URL | filename | username | password</code>"
            ),
            reply_markup=reply_markup,
            thumb_url=thumb_url,
            reply_to_message_id=update.id,
            referer=url,
        )
    else:
        await imog.edit("<b>⚠️ No format found, checking direct link...</b>", parse_mode=enums.ParseMode.HTML)
        try:
            if await is_direct_download_url(url):
                await imog.delete(True)
                await bot.send_message(
                    chat_id=update.chat.id,
                    text="<b>✅ Direct link detected</b>\nChoose output type:",
                    reply_markup=build_direct_markup(),
                    parse_mode=enums.ParseMode.HTML,
                    reply_to_message_id=update.id,
                )
                return
        except Exception as e:
            logger.error(f"Direct download check error: {e}")

        fallback_markup = InlineKeyboardMarkup([[
            InlineKeyboardButton("🎬 Video", callback_data="video=OFL=ENON".encode("UTF-8")),
            InlineKeyboardButton("📁 File", callback_data="file=LFO=NONE".encode("UTF-8")),
        ]])
        await imog.delete(True)
        await bot.send_message(
            chat_id=update.chat.id,
            text="<b>📦 Format selection ready</b>",
            reply_markup=fallback_markup,
            parse_mode=enums.ParseMode.HTML,
            reply_to_message_id=update.id,
        )
