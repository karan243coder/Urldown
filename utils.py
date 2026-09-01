# BIMBO v4.0 - Common Utilities
import os
import re
import json
import time
import random
import asyncio
import logging
import string
import shutil
import aiohttp
import requests
import pytz
from datetime import datetime, date
from typing import Union, List
from bs4 import BeautifulSoup

from pyrogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup
from pyrogram.errors import FloodWait, UserIsBlocked, MessageNotModified, PeerIdInvalid

from config import Config
from database.access import bimbo

logger = logging.getLogger(__name__)

# =================== TOKEN / VERIFY (URL shortener) ===================
TOKENS = {}
VERIFIED = {}

# =================== RATE LIMITER ===================
_user_last_req = {}
_user_semaphore = {}  # per-user semaphore (1 task at a time for free users)
_global_semaphore = asyncio.Semaphore(Config.BIMBO_MAX_CONCURRENT_TASKS)


def user_sem(uid: int):
    if uid not in _user_semaphore:
        _user_semaphore[uid] = asyncio.Semaphore(1)
    return _user_semaphore[uid]


async def rate_limit_check(uid: int) -> int:
    """Returns seconds to wait (0 if OK)."""
    now = time.time()
    last = _user_last_req.get(uid, 0)
    wait = int(Config.RATE_LIMIT_SECONDS - (now - last))
    if wait <= 0:
        _user_last_req[uid] = now
        return 0
    return wait


# =================== COMMON HELPERS ===================

def humanbytes(n: float) -> str:
    if not n:
        return "0 B"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.2f} {unit}"
        n /= 1024
    return f"{n:.2f} PB"


def time_formatter(seconds: float) -> str:
    seconds = int(max(seconds, 0))
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    d, h = divmod(h, 24)
    if d:
        return f"{d}d {h}h {m}m"
    if h:
        return f"{h}h {m}m {s}s"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


def safe_filename(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|]+', ' ', str(name or "file"))
    name = re.sub(r'\s+', ' ', name).strip()
    return (name[:180] or f"file_{int(time.time())}")


def user_download_dir(uid) -> str:
    p = os.path.join(Config.BIMBO_DOWNLOAD_LOCATION, str(uid))
    os.makedirs(p, exist_ok=True)
    return p


def is_url(text: str) -> bool:
    return bool(re.match(r"https?://[^\s]+", (text or "").strip(), re.I))


def get_url(text: str):
    m = re.search(r"(https?://[^\s]+)", (text or "").strip(), re.I)
    return m.group(1) if m else None


def is_media(msg: Message):
    return bool(
        msg.video or msg.document or msg.audio or msg.voice
        or msg.video_note or msg.photo or msg.animation
    )


def get_file_id(msg: Message):
    for t in ("video", "document", "audio", "voice", "video_note", "photo", "animation"):
        m = getattr(msg, t, None)
        if m:
            if t == "photo":
                return m.file_id, "photo", m
            return m.file_id, t, m
    return None, None, None


async def cleanup_dir(path: str):
    """Best-effort cleanup of a download directory."""
    try:
        if path and os.path.exists(path):
            shutil.rmtree(path, ignore_errors=True)
    except Exception as e:
        logger.warning(f"cleanup_dir failed for {path}: {e}")


async def run_cmd(cmd, timeout=None):
    """Run a subprocess and capture output. Returns (returncode, stdout, stderr)."""
    p = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(p.communicate(), timeout=timeout or Config.BIMBO_PROCESS_MAX_TIMEOUT)
        return p.returncode, out.decode("utf-8", "ignore"), err.decode("utf-8", "ignore")
    except asyncio.TimeoutError:
        try:
            p.kill()
        except Exception:
            pass
        return -1, "", "timeout"


# =================== URL SHORTENER / VERIFY ===================
async def get_verify_shorted_link(link):
    API = Config.BIMBO_API
    URL = Config.BIMBO_URL
    if not API or not URL:
        return link
    https = link.split(":")[0]
    if "http" == https:
        https = "https"
        link = link.replace("http", https)

    if URL == "api.shareus.in":
        url = f"https://{URL}/shortLink"
        params = {"token": API, "format": "json", "link": link}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, raise_for_status=True, ssl=False) as r:
                    data = await r.json(content_type="text/html")
                    if data.get("status") == "success":
                        return data["shortlink"]
        except Exception as e:
            logger.error(e)
        return f"https://{URL}/shortLink?token={API}&format=json&link={link}"

    url = f'https://{URL}/api'
    params = {'api': API, 'url': link}
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, params=params, ssl=False) as r:
                data = await r.json()
                if data.get("status") == "success":
                    return data.get('shortenedUrl') or link
    except Exception as e:
        logger.error(e)
    return f'{URL}/api?api={API}&link={link}'


async def check_token(bot, userid, token):
    if userid in TOKENS and token in TOKENS.get(userid, {}):
        return TOKENS[userid][token] is False
    return False


async def get_token(bot, userid, link):
    token = ''.join(random.choices(string.ascii_letters + string.digits, k=7))
    TOKENS[userid] = {token: False}
    link = f"{link}verify-{userid}-{token}"
    return await get_verify_shorted_link(link)


async def verify_user(bot, userid, token):
    TOKENS.setdefault(userid, {})[token] = True
    tz = pytz.timezone('Asia/Kolkata')
    VERIFIED[userid] = str(date.today())


async def check_verification(bot, userid):
    tz = pytz.timezone('Asia/Kolkata')
    today = date.today()
    exp = VERIFIED.get(userid)
    if exp:
        try:
            y, m, d = exp.split('-')
            comp = date(int(y), int(m), int(d))
            return comp >= today
        except Exception:
            return False
    return False


# =================== PREMIUM HELPER ===================
async def is_premium(uid: int):
    try:
        p = await bimbo.db.get_premium(int(uid))
        return bool(p)
    except Exception:
        return False


def is_admin(uid: int) -> bool:
    try:
        return int(uid) in Config.BIMBO_ADMIN_IDS
    except Exception:
        return False

# Global download semaphore - allows 2 concurrent downloads (for 512MB RAM)
# Per-user queue system prevents abuse while allowing multi-user support
import asyncio
GLOBAL_DOWNLOAD_SEM = asyncio.Semaphore(2)  # Increased from 1 to 2

# Per-user download queue system
_user_download_queues = {}

def get_user_queue(user_id: int):
    """Get or create user's download queue"""
    if user_id not in _user_download_queues:
        _user_download_queues[user_id] = {
            'queue': [],
            'processing': False,
            'position': 0
        }
    return _user_download_queues[user_id]

def add_to_queue(user_id: int, task_info: dict) -> int:
    """Add task to user's queue, returns queue position"""
    queue = get_user_queue(user_id)
    queue['queue'].append(task_info)
    queue['position'] += 1
    return len(queue['queue'])


# =================== FLOODWAIT SAFE MESSAGE FUNCTIONS ===================

async def safe_reply_text(message, text, **kwargs):
    """Reply to message with FloodWait handling"""
    try:
        return await message.reply_text(text, **kwargs)
    except FloodWait as e:
        logger.warning(f"FloodWait: Waiting {e.value}s before reply...")
        await asyncio.sleep(e.value)
        return await message.reply_text(text, **kwargs)
    except Exception as e:
        logger.error(f"safe_reply_text error: {e}")
        return None


async def safe_edit_text(message, text, **kwargs):
    """Edit message with FloodWait handling"""
    try:
        return await message.edit_text(text, **kwargs)
    except FloodWait as e:
        logger.warning(f"FloodWait: Waiting {e.value}s before edit...")
        await asyncio.sleep(e.value)
        return await message.edit_text(text, **kwargs)
    except MessageNotModified:
        return None
    except Exception as e:
        logger.error(f"safe_edit_text error: {e}")
        return None


async def safe_send_message(client, chat_id, text, **kwargs):
    """Send message with FloodWait handling"""
    try:
        return await client.send_message(chat_id, text, **kwargs)
    except FloodWait as e:
        logger.warning(f"FloodWait: Waiting {e.value}s before send...")
        await asyncio.sleep(e.value)
        return await client.send_message(chat_id, text, **kwargs)
    except Exception as e:
        logger.error(f"safe_send_message error: {e}")
        return None


async def safe_edit_text_or_caption(message, text, **kwargs):
    """Edit message text or caption (works for both text and photo messages) with FloodWait handling"""
    try:
        if getattr(message, "photo", None) or getattr(message, "video", None) or getattr(message, "document", None):
            return await message.edit_caption(caption=text, **kwargs)
        else:
            return await message.edit_text(text=text, **kwargs)
    except FloodWait as e:
        logger.warning(f"FloodWait: Waiting {e.value}s before edit...")
        await asyncio.sleep(e.value)
        if getattr(message, "photo", None) or getattr(message, "video", None) or getattr(message, "document", None):
            return await message.edit_caption(caption=text, **kwargs)
        else:
            return await message.edit_text(text=text, **kwargs)
    except MessageNotModified:
        return None
    except Exception as e:
        if "MESSAGE_EMPTY" in str(e).upper() or "NO TEXT IN THE MESSAGE" in str(e).upper():
            try:
                return await message.edit_caption(caption=text, **kwargs)
            except Exception:
                pass
        logger.debug(f"safe_edit_text_or_caption skipped: {e}")
        return None


