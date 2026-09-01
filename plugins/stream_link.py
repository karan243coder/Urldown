# -*- coding: utf-8 -*-
# BIMBO — /stream (website video streaming)
# ================================================================
# File-share-bot style:
#   User kisi video/file par reply kare -> /stream
#   Bot TURANT (instant) ek short token banata hai, video ko stream-channel
#   me save karta hai, MongoDB me store karta hai (24h TTL auto-delete),
#   aur ek playable + download link deta hai jo tumhari website se chalta hai.
#
# Koi re-upload/gofile nahi -> isliye load kam, aur link instant milta hai.
import time
import secrets
import logging

from pyrogram import Client, filters

from config import Config
from translation import Translation
from utils import is_media, rate_limit_check, is_admin
from database.adduser import AddUser
from database.users_chats_db import db

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


def _media_info(m):
    """Return (media_obj, file_name, file_size, mime) from a message."""
    for t in ("video", "document", "audio", "animation"):
        x = getattr(m, t, None)
        if x:
            fn = getattr(x, "file_name", None) or f"{t}_{int(time.time())}.mp4"
            return x, fn, int(getattr(x, "file_size", 0) or 0), getattr(x, "mime_type", None)
    return None, None, 0, None


def _new_token(n=10):
    # URL-safe short token
    return secrets.token_urlsafe(n)[:n]


def _build_links(token: str):
    """Return (watch_url, download_url) based on config."""
    # Prefer bot's own public stream server (instant, range streaming).
    base = Config.BIMBO_STREAM_PUBLIC_URL
    if base:
        return f"{base}/watch/{token}", f"{base}/dl/{token}"
    # Fall back to website's player page.
    site = Config.BIMBO_STREAM_SITE
    player = Config.BIMBO_STREAM_PLAYER_PATH if Config.BIMBO_STREAM_PLAYER_PATH.startswith("/") else "/" + Config.BIMBO_STREAM_PLAYER_PATH
    return f"{site}{player}?t={token}", f"{site}{player}?t={token}&dl=1"


@Client.on_message(filters.private & _cmd("stream", "link", "gs"))
async def cmd_stream(client, message):
    await AddUser(client, message)

    # Force-sub + maintenance gates (same as other download commands)
    try:
        from plugins.forcesub import handle_force_sub
        if Config.BIMBO_UPDATES_CHANNEL is not None:
            if await handle_force_sub(client, message) == 400:
                return
    except Exception:
        pass
    if Config.MAINTENANCE_MODE and not is_admin(message.from_user.id):
        return await message.reply_text(Translation.MAINTENANCE_MSG)

    if not message.reply_to_message or not is_media(message.reply_to_message):
        return await message.reply_text(
            "❌ Kisi **video/file** par reply karke `/stream` bhejo.\n\n"
            "Example: video par reply → `/stream`"
        )

    uid = message.from_user.id
    wait = await rate_limit_check(uid)
    if wait > 0:
        return await message.reply_text(Translation.RATE_LIMIT_MSG.format(wait))

    src = message.reply_to_message
    media, file_name, file_size, mime = _media_info(src)
    if not media:
        return await message.reply_text("❌ Ye media stream nahi ho sakta.")

    msg = await message.reply_text("⚡ Link ban raha hai...")

    try:
        # ---- Video ko stream-channel me save karo (source persist) ----
        store_chat = Config.BIMBO_STREAM_CHANNEL or Config.BIMBO_LOG_CHANNEL
        if store_chat:
            try:
                saved = await src.copy(store_chat)
                chat_id, msg_id = store_chat, saved.id
            except Exception as e:
                logger.warning(f"stream copy to channel failed, using original: {e}")
                chat_id, msg_id = src.chat.id, src.id
        else:
            # Koi channel set nahi — original message hi use karo (user ne
            # message delete kiya to link dead ho jaayega).
            chat_id, msg_id = src.chat.id, src.id

        token = _new_token()
        ttl = int(Config.BIMBO_STREAM_TTL_HOURS or 24)
        await db.add_stream_link(
            token=token,
            url="",  # bot-served; actual bytes via /dl
            user_id=uid,
            ttl_hours=ttl,
            meta={
                "chat_id": chat_id,
                "msg_id": msg_id,
                "file_name": file_name,
                "file_size": file_size,
                "mime_type": mime or "",
            },
        )
        try:
            await db.incr_stat("stream_links_generated", 1)
        except Exception:
            pass

        watch_url, dl_url = _build_links(token)

        from utils import humanbytes
        text = (
            "✅ **Stream link ready!**\n\n"
            f"📁 **File:** `{file_name}`\n"
            f"📦 **Size:** {humanbytes(file_size) if file_size else 'N/A'}\n\n"
            f"▶️ **Watch/Stream:** {watch_url}\n\n"
            f"💡 Download karna ho to website pe niche **Download** button hai.\n"
            f"⏳ Ye link **{ttl} ghante** baad auto-delete/expire ho jaayega."
        )
        await msg.edit_text(text, disable_web_page_preview=False)
    except Exception as e:
        logger.exception("stream cmd")
        await msg.edit_text(f"❌ Error: <code>{e}</code>")
