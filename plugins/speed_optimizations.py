# -*- coding: utf-8 -*-
# BIMBO Bot v3.1 — Speed optimization plugin
# Commands:
#   /speed   - Quick network test (download ~10MB from fast CDN)
#   /tuning  - Show active speed tuning settings
#   /clearcache - Manual cleanup of downloads folder (owner only)

import os
import time
import shutil
import asyncio
import logging
import psutil

import aiohttp
from pyrogram import Client, filters
from pyrogram.types import Message

from config import Config

logger = logging.getLogger(__name__)


def _human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.2f} {unit}/s"
        n /= 1024
    return f"{n:.2f} TB/s"



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


@Client.on_message(filters.private & _cmd('speed', 'speedtest'))
async def speed_test(client: Client, message: Message):
    """Quick download speed test from Cloudflare cache."""
    m = await message.reply_text("🚀 **Running quick speed test…**\n(10 MB from Cloudflare CDN)")
    url = "https://speed.cloudflare.com/__down?bytes=10000000"  # 10 MB
    try:
        timeout = aiohttp.ClientTimeout(total=30)
        connector = aiohttp.TCPConnector(limit=4)
        async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
            t0 = time.time()
            total = 0
            async with session.get(url) as r:
                async for chunk in r.content.iter_chunked(1024 * 256):
                    total += len(chunk)
            elapsed = time.time() - t0
            speed = total / max(elapsed, 0.001)
        await m.edit_text(
            "🚀 **Speed Test Result**\n\n"
            f"📦 Downloaded: `{total/1024/1024:.2f} MB`\n"
            f"⏱️ Time: `{elapsed:.2f} s`\n"
            f"⚡ Speed: `{_human(speed)}`\n\n"
            "💡 Ye VPS/Instance ki outbound speed hai. Telegram pe upload "
            "speed Telegram ke servers aur DC pe bhi depend karti hai."
        )
    except Exception as e:
        await m.edit_text(f"❌ Speed test failed: `{e}`")


@Client.on_message(filters.private & _cmd('tuning', 'optimization'))
async def tuning_info(client: Client, message: Message):
    """Show current tuning config."""
    disk = psutil.disk_usage(Config.BIMBO_DOWNLOAD_LOCATION)
    ram = psutil.virtual_memory()
    cpu = psutil.cpu_percent(interval=0.5)
    text = (
        "⚙️ **BIMBO Speed Tuning (v3.1)**\n\n"
        f"👷 Pyrogram Workers: `{Config.BIMBO_WORKERS}`\n"
        f"📤 Max Concurrent TX: `8`\n"
        f"🔽 Max Concurrent Tasks: `{Config.BIMBO_MAX_CONCURRENT_TASKS}`\n"
        f"🧩 Chunk Size: `{Config.BIMBO_CHUNK_SIZE//1024} KB`\n"
        f"🎬 yt-dlp Fragments: `{Config.YTDLP_CONCURRENT_FRAGMENTS}` parallel\n"
        f"⚡ Aria2 External DL: `{'ON ✅' if Config.YTDLP_USE_ARIA2C else 'OFF ❌'}`\n"
        f"📂 Download Dir: `{Config.BIMBO_DOWNLOAD_LOCATION}`\n"
        f"🧹 Auto Cleanup: `{Config.BIMBO_AUTO_CLEANUP_HOURS}h`\n\n"
        "📊 **Live System Stats**\n"
        f"• CPU: `{cpu}%`\n"
        f"• RAM: `{ram.percent}%` ({ram.used//1024//1024} MB / {ram.total//1024//1024} MB)\n"
        f"• Disk: `{disk.percent}%` ({disk.free//1024//1024//1024} GB free)\n"
    )
    await message.reply_text(text)


@Client.on_message(filters.private & _cmd('clearcache', 'cleandl'))
async def clear_cache(client: Client, message: Message):
    """Owner-only manual cleanup of download folder."""
    if message.from_user.id != Config.BIMBO_OWNER_ID:
        await message.reply_text("❌ Owner only command.")
        return
    m = await message.reply_text("🧹 Cleaning downloads folder…")
    d = Config.BIMBO_DOWNLOAD_LOCATION
    removed = 0
    freed = 0
    for root, dirs, files in os.walk(d, topdown=False):
        if ".aria2" in root:
            continue
        for f in files:
            p = os.path.join(root, f)
            try:
                freed += os.path.getsize(p)
                os.remove(p)
                removed += 1
            except Exception:
                pass
        for dr in dirs:
            p = os.path.join(root, dr)
            try:
                shutil.rmtree(p, ignore_errors=True)
            except Exception:
                pass
    await m.edit_text(
        f"✅ Cleanup done.\n"
        f"🗑️ Files removed: `{removed}`\n"
        f"💾 Freed: `{freed/1024/1024:.1f} MB`"
    )
