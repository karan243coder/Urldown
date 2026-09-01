# BIMBO v4.0 — Instagram / TikTok / Short Video Downloader Plugin
# Uses gallery-dl approach via yt-dlp (already supports 1000+ sites), plus
# custom handling for Terabox, Pixeldrain, Gofile, Doodstream, M3U8.
import os
import re
import json
import time
import shutil
import asyncio
import logging

import aiohttp
from pyrogram import Client, filters
from pyrogram.types import Message

from config import Config
from translation import Translation
from database.adduser import AddUser
from plugins.forcesub import handle_force_sub
from utils import (
    is_url, get_url, safe_filename, user_download_dir,
    cleanup_dir, run_cmd, is_admin, is_premium, rate_limit_check, humanbytes,
)

logger = logging.getLogger(__name__)

# -------- Site detection --------
SITE_PATTERNS = {
    "instagram": re.compile(r"(instagram\.com/(p|reel|stories|tv)/|instagr\.am/)", re.I),
    "tiktok":    re.compile(r"(tiktok\.com/|vm\.tiktok\.com/|vt\.tiktok\.com/)", re.I),
    "facebook":  re.compile(r"(facebook\.com/|fb\.watch/|fb\.com/)", re.I),
    "twitter":   re.compile(r"(twitter\.com/|x\.com/)", re.I),
    "terabox":   re.compile(r"(terabox\.com|teraboxapp\.com|nephobox\.com|4funbox\.com|momerybox\.com|tibibox\.com)", re.I),
    "pixeldrain":re.compile(r"pixeldrain\.com/(u|l)/([\w-]+)", re.I),
    "gofile":    re.compile(r"gofile\.io/d/([\w-]+)", re.I),
    "doodstream":re.compile(r"(dood\.(watch|so|la|to|ws)|doodstream|doodcdn)", re.I),
    "streamtape":re.compile(r"(streamtape\.com|stp\.cloud)", re.I),
    "m3u8":      re.compile(r"\.m3u8(\?|$)|\.mpd(\?|$)|m3u8_", re.I),
    "mdisk":     re.compile(r"(mdisk\.me|mdiskdrive|mdisk\.)", re.I),
    "youtu":     re.compile(r"(youtube\.com|youtu\.be|music\.youtube\.com)", re.I),
    "xhamster":  re.compile(r"xhamster", re.I),
    "eporner":   re.compile(r"eporner", re.I),
}


def detect_site(url: str) -> str:
    for name, pat in SITE_PATTERNS.items():
        if pat.search(url):
            return name
    return "direct"


# -------- Pixeldrain direct URL fetcher --------
async def pixeldrain_download_url(file_id: str) -> str:
    return f"https://pd.cybar.xyz/{file_id}"


async def gofile_info(file_id: str):
    """Returns (filename, direct_download_url) or (None, None)."""
    token = Config.GOFILE_TOKEN or ""
    headers = {"User-Agent": "Mozilla/5.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        api = f"https://api.gofile.io/contents/{file_id}?wt=4fd6sg89d7s6"
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as s:
            async with s.get(api, headers=headers, ssl=False) as r:
                j = await r.json()
        if j.get("status") != "ok":
            return None, None
        data = j.get("data", {})
        # Gofile v2: children contains files
        children = data.get("children", {})
        if children:
            # pick first file
            for _id, info in children.items():
                if info.get("type") == "file":
                    return info.get("name"), info.get("link")
        # fallback: top-level is file
        if data.get("type") == "file":
            return data.get("name"), data.get("link")
        return None, None
    except Exception as e:
        logger.error(f"gofile_info: {e}")
        return None, None


# -------- yt-dlp wrapper (generic for Instagram/TikTok/FB/Twitter/...) --------
async def ytdlp_download(url: str, out_dir: str, ext="mp4", quality="best", cookiefile="cookies.txt"):
    os.makedirs(out_dir, exist_ok=True)
    out_tpl = os.path.join(out_dir, "%(title).150B [%(id)s].%(ext)s")
    cmd = [
        "yt-dlp", "--no-warnings", "-c", "--newline",
        "--geo-bypass", "--no-check-certificates",
        "--buffer-size", "16M",
        "--retries", "10", "--fragment-retries", "10",
        "--concurrent-fragments", str(Config.YTDLP_CONCURRENT_FRAGMENTS),
        "--add-header", "User-Agent:Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36",
        "-o", out_tpl,
    ]
    if quality == "audio":
        cmd += ["-x", "--audio-format", ext or "mp3", "--audio-quality", "192K"]
    else:
        if quality in ("best", ""):
            fmt = "bv*+ba/b"
        elif quality == "720":
            fmt = "bv*[height<=720]+ba/b[height<=720]/b"
        elif quality == "480":
            fmt = "bv*[height<=480]+ba/b[height<=480]/b"
        elif quality == "360":
            fmt = "bv*[height<=360]+ba/b[height<=360]/b"
        else:
            fmt = "bv*+ba/b"
        cmd += ["-f", fmt, "--merge-output-format", "mp4"]

    if os.path.exists(cookiefile):
        cmd += ["--cookies", cookiefile]

    if Config.YTDLP_USE_ARIA2C and detect_site(url) not in ("instagram", "tiktok", "twitter"):
        cmd += [
            "--downloader", "aria2c",
            "--downloader-args", "aria2c:-x 16 -s 16 -k 1M --file-allocation=none "
                                  "--max-tries=10 --retry-wait=2",
        ]
    cmd.append(url)

    logger.info(f"[yt-dlp] running on {url[:80]}")
    rc, out, err = await run_cmd(cmd, timeout=Config.BIMBO_PROCESS_MAX_TIMEOUT)
    # Find the downloaded file — pick the newest in out_dir
    if rc != 0:
        return None, (err or out)[-800:]
    files = []
    for f in os.listdir(out_dir):
        p = os.path.join(out_dir, f)
        if os.path.isfile(p) and not f.endswith((".part", ".ytdl", ".temp")):
            files.append(p)
    if not files:
        return None, "no file produced"
    # pick largest/newest
    files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return files[0], None


# -------- Command handler: /ig /tt /fb /tw /tera /pd /gofile /m3u8 --------

# ============== Cross-version safe command filter ==============
def _cmd(*names):
    names = [n.lower().lstrip("/") for n in names]
    def f(_flt, _client, m):
        if not m or not getattr(m, "text", None):
            return False
        if m.media:
            return False
        t = (m.text or "").strip()
        if not t.startswith("/"):
            return False
        first = t.split()[0][1:].split("@")[0].lower()
        return first in names
    return filters.create(f)


@Client.on_message(filters.private & _cmd('ig', 'instagram', 'tt', 'tiktok', 'fb', 'facebook', 'tw', 'twitter', 'x', 'm3u8', 'pd', 'pixeldrain'))
async def short_download(client: Client, message: Message):
    await AddUser(client, message)
    if Config.BIMBO_UPDATES_CHANNEL is not None:
        if await handle_force_sub(client, message) == 400:
            return
    if Config.MAINTENANCE_MODE and not is_admin(message.from_user.id):
        return await message.reply_text(Translation.MAINTENANCE_MSG)
    uid = message.from_user.id
    wait = await rate_limit_check(uid)
    if wait > 0:
        return await message.reply_text(Translation.RATE_LIMIT_MSG.format(wait))

    from plugins.preemption_manager import pause_bulk_jobs, resume_bulk_jobs
    paused_jobs = await pause_bulk_jobs(uid)

    text = (message.text or "").split(None, 1)
    cmd = text[0].lstrip("/").lower()
    url = text[1] if len(text) > 1 else ""
    if message.reply_to_message and message.reply_to_message.text:
        url = message.reply_to_message.text.strip()
    url = get_url(url)
    if not url:
        return await message.reply_text(Translation.INVALID_CMD + "\n\nUsage: <code>/"
                                        + cmd + " https://example.com/...</code>")

    msg = await message.reply_text(Translation.PROCESSING)
    out_dir = user_download_dir(uid) + f"/dl_{int(time.time())}"
    os.makedirs(out_dir, exist_ok=True)
    try:
        site = detect_site(url)
        site_name = {
            "instagram": "Instagram", "tiktok": "TikTok", "facebook": "Facebook",
            "twitter": "Twitter/X", "pixeldrain": "Pixeldrain",
            "m3u8": "M3U8 Stream", "gofile": "Gofile", "youtu": "YouTube",
            "terabox": "Terabox", "xhamster": "xHamster", "eporner": "Eporner", "direct": "Direct",
        }.get(site, site)

        await msg.edit_text(f"🔍 **Detected:** {site_name}\n📥 Fetching...")

        # ----- PIXELDRAIN: build direct URL and let aria2/yt-dlp handle -----
        if site == "pixeldrain":
            m = SITE_PATTERNS["pixeldrain"].search(url)
            if m:
                file_id = m.group(2)
                url = await pixeldrain_download_url(file_id)

        # ----- M3U8: directly use yt-dlp with hls flags -----
        # (falls through to generic ytdlp_download)

        # Download with generic yt-dlp
        dl_path, err = await ytdlp_download(url, out_dir, quality="best")
        if not dl_path:
            await msg.edit_text(f"❌ **Download failed** for {site_name}.\n\n<code>{err or 'unknown error'}</code>")
            return

        size = os.path.getsize(dl_path)
        await msg.edit_text(f"✅ Downloaded ({site_name})\n📤 Uploading to Telegram...\n"
                            f"📁 {os.path.basename(dl_path)} | {humanbytes(size)}")

        # Send as video or document based on extension
        cap = f"✅ **{site_name} Downloaded via BIMBO**\n📁 {os.path.basename(dl_path)}"
        if dl_path.lower().endswith((".mp4", ".mkv", ".webm", ".mov")) and size < Config.BIMBO_TG_MAX_FILE_SIZE:
            await client.send_video(
                message.chat.id, video=dl_path, caption=cap,
                supports_streaming=True,
                reply_to_message_id=message.id,
            )
        else:
            await client.send_document(
                message.chat.id, document=dl_path, caption=cap,
                reply_to_message_id=message.id,
            )
        try:
            await msg.delete()
        except Exception:
            pass
    except Exception as e:
        logger.exception("short_download error")
        await msg.edit_text(f"❌ **Error:** <code>{e}</code>")
    finally:
        asyncio.create_task(cleanup_dir(out_dir))
        if paused_jobs:
            await resume_bulk_jobs(uid, client)
