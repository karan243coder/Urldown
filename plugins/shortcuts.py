# BIMBO v4.0 — Shortcut commands that pre-route to correct handler
# /yt <url>    → same as sending youtube link
# /direct <u>  → direct HTTP download (aria2c fallback)
# /tera <url>  → Terabox download
# These commands essentially echo the URL so existing youtube_dl_echo picks them up.
import logging
import re
from pyrogram import Client, filters
from pyrogram.types import Message
from utils import get_url

logger = logging.getLogger(__name__)



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


@Client.on_message(filters.private & _cmd('yt', 'youtube'))
async def yt_shortcut(client: Client, m: Message):
    parts = (m.text or "").split(None, 1)
    url = parts[1] if len(parts) > 1 else ""
    if m.reply_to_message and m.reply_to_message.text:
        url = m.reply_to_message.text
    url = get_url(url)
    if not url or not re.search(r"(youtube\.com|youtu\.be)", url, re.I):
        return await m.reply_text("Usage: <code>/yt https://youtu.be/...</code>")
    # Forward as normal message to be picked up by ytdlp echo handler
    await m.reply_text(url)


@Client.on_message(filters.private & _cmd('direct', 'dl'))
async def direct_shortcut(client: Client, m: Message):
    parts = (m.text or "").split(None, 1)
    url = parts[1] if len(parts) > 1 else ""
    if m.reply_to_message and m.reply_to_message.text:
        url = m.reply_to_message.text
    url = get_url(url)
    if not url:
        return await m.reply_text("Usage: <code>/direct https://site.com/file.mp4</code>")
    await m.reply_text(url)


@Client.on_message(filters.private & _cmd('tera', 'terabox'))
async def tera_shortcut(client: Client, m: Message):
    parts = (m.text or "").split(None, 1)
    url = parts[1] if len(parts) > 1 else ""
    if m.reply_to_message and m.reply_to_message.text:
        url = m.reply_to_message.text
    url = get_url(url)
    if not url or not re.search(r"(terabox|nephobox|4funbox|momerybox|tibibox)", url, re.I):
        return await m.reply_text("Usage: <code>/tera https://terabox.com/s/xxxx</code>")
    await m.reply_text(url)


@Client.on_message(filters.private & _cmd('m3u8'))
async def m3u8_shortcut(client: Client, m: Message):
    parts = (m.text or "").split(None, 1)
    url = parts[1] if len(parts) > 1 else ""
    if m.reply_to_message and m.reply_to_message.text:
        url = m.reply_to_message.text
    url = get_url(url)
    if not url:
        return await m.reply_text("Usage: <code>/m3u8 https://site.com/play.m3u8</code>")
    await m.reply_text(url)
