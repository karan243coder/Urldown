# -*- coding: utf-8 -*-
# BIMBO v9.0 — Auto Cleaner (FIXED - ALL COMMAND RESPONSES DELETE IN 10s)
# ================================================
# Bug Fix: Pehle sirf user ka /start delete hota tha, bot ka response nahi.
# Ab har command ka user + bot response dono 10s me auto-delete hoga agar use nahi hua.
# Media / Screenshots / Upload / Download progress -> KABHI delete nahi
# Private + Groups dono

import asyncio
import logging
import time
import re
from typing import Dict, Any, Union, List

from pyrogram import Client, filters, enums
from pyrogram.types import Message
from pyrogram.errors import FloodWait

from config import Config

logger = logging.getLogger(__name__)

# ---------------- Delays ----------------
AUTO_SEC = int(getattr(Config, "AUTO_DELETE_SECONDS", 10) or 10)
if AUTO_SEC < 1: AUTO_SEC = 10

USER_CMD_DELAY = AUTO_SEC
USER_LINK_DELAY = 60
BOT_TEXT_DELAY = AUTO_SEC
BOT_MENU_DELAY = AUTO_SEC
BOT_SUCCESS_DELAY = AUTO_SEC
BOT_ERROR_DELAY = AUTO_SEC
REAP_INTERVAL = 1.5

URL_RE = re.compile(r"((?:https?://|www\.)[^\s)>\]]+|t\.me/[^\s)>\]]+|magnet:\?xt=urn:btih:[a-zA-Z0-9]+)", re.IGNORECASE)
COMMAND_RE = re.compile(r"^/([a-zA-Z0-9_]+)(?:@[a-zA-Z0-9_]+bot)?(?:\s|$)", re.IGNORECASE)

# Command reply captions – inko delete karna hai, protect nahi
COMMAND_PHOTO_KEYWORDS = (
    "welcome", "start", "help", "about", "admin panel", "admin control",
    "choose an option", "bot statistics", "bot settings", "premium management",
    "channel management", "ban management", "bimbo", "command", "usage",
    # ⚡ NEW PRO START keywords
    "url uploader pro", "active", "up to 100", "4 gb available",
    "just send me any direct link", "upload it instantly", "hello",
    "status", "speed", "limit", "⚡"
)

_TRACK: Dict[tuple, Dict[str, Any]] = {}
_TRACK_LOCK = asyncio.Lock()
_reaper_started = False

def _has_url(text: str) -> bool:
    return bool(text and URL_RE.search(text))

def _is_command(text: str) -> bool:
    return bool(text and COMMAND_RE.match(text.strip()))

def _is_progress(text: str) -> bool:
    if not text: return False
    if "█" in text or "░" in text: return True
    low = text.lower()
    ACTIVE = ("processing", "downloading", "uploading", "eta", "speed", "initializing", "fetching", "extracting", "splitting", "merging", "preparing", "queuing", "sending", "%")
    return any(k in low for k in ACTIVE) and re.search(r"\d+%", text)

def _has_keyboard(reply_markup) -> bool:
    if reply_markup is None: return False
    try:
        kb = getattr(reply_markup, "inline_keyboard", None)
        return bool(kb and len(kb) > 0)
    except Exception:
        return False

def _is_success(text: str) -> bool:
    if not text: return False
    success_keywords = ["✅", "complete", "finished", "done", "success", "uploaded", "downloaded"]
    text_lower = text.lower()
    return any(kw in text_lower for kw in success_keywords)

def _is_error(text: str) -> bool:
    if not text: return False
    error_keywords = ["❌", "failed", "error", "timeout", "expired"]
    text_lower = text.lower()
    return any(kw in text_lower for kw in error_keywords)

def _is_command_photo(m: Message, text: str) -> bool:
    low = (text or "").lower()
    return any(kw in low for kw in COMMAND_PHOTO_KEYWORDS)

def _is_media_message(m: Message) -> bool:
    """FINAL UPLOADED MEDIA — keep forever. Photo menus -> delete"""
    if not m.media:
        return False
    if getattr(m, "video", None) or getattr(m, "document", None) or getattr(m, "audio", None) or getattr(m, "voice", None) or getattr(m, "animation", None) or getattr(m, "sticker", None):
        return True
    photo = getattr(m, "photo", None)
    if photo:
        if getattr(m, "media_group_id", None):
            return True
        text = getattr(m, "caption", "") or getattr(m, "text", "") or ""
        if _is_command_photo(m, text):
            return False
        if _has_keyboard(getattr(m, "reply_markup", None)):
            return False
        # No keyboard and not command photo -> likely screenshot -> PROTECT
        # But if caption looks like command (short), don't protect
        if len(text) < 600 and any(k in text.lower() for k in COMMAND_PHOTO_KEYWORDS):
            return False
        return True
    return not _has_keyboard(getattr(m, "reply_markup", None))

async def _track_msg(m: Message, delay: float, perm: bool = False, reason: str = ""):
    if not m or not getattr(m, "chat", None): return
    cid, mid = m.chat.id, m.id
    if not cid or not mid: return
    async with _TRACK_LOCK:
        _TRACK[(cid, mid)] = {"ts": time.time() + delay if not perm else float("inf"), "perm": perm, "reason": reason}

async def _mark_perm(m: Message):
    await _track_msg(m, 0, perm=True)

async def _invalidate(m: Message):
    if not m or not getattr(m, "chat", None): return
    async with _TRACK_LOCK:
        _TRACK.pop((m.chat.id, m.id), None)

# ============== PUBLIC HELPERS - FOR OTHER PLUGINS ==============
async def track_bot_response(message: Message, delay: float = None, reason: str = "bot_response"):
    """Call this from any plugin after sending a bot reply to ensure it auto-deletes"""
    if delay is None:
        delay = AUTO_SEC
    await _track_msg(message, delay, reason=reason)

async def track_user_command(message: Message, delay: float = None):
    if delay is None:
        delay = AUTO_SEC
    await _track_msg(message, delay, reason="user_cmd_explicit")

async def schedule_delete_both(client: Client, user_msg: Message, bot_msg: Message, delay: float = None):
    """Guaranteed delete both user cmd + bot response after delay"""
    if delay is None:
        delay = AUTO_SEC
    try:
        if user_msg:
            await _track_msg(user_msg, delay, reason="user_cmd_both")
    except: pass
    try:
        if bot_msg:
            await _track_msg(bot_msg, delay, reason="bot_both")
    except: pass

# ============== USER messages ==============
def _user_filter(_, __, m: Message):
    if not m or getattr(m, "service", None): return False
    if m.media: return False
    if not getattr(m, "chat", None): return False
    from_user = getattr(m, "from_user", None)
    if from_user and from_user.is_bot: return False
    return bool(getattr(m, "text", None))

_user_filter = filters.create(_user_filter)

@Client.on_message(_user_filter, group=-5)
@Client.on_edited_message(_user_filter, group=-5)
async def track_user_message(client: Client, m: Message):
    try:
        text = (m.text or "").strip()
        if not text: return
        if _has_url(text):
            await _track_msg(m, USER_LINK_DELAY, reason="user_link"); return
        if _is_command(text):
            await _track_msg(m, USER_CMD_DELAY, reason="cmd"); return
        # Private non-command text -> instant delete to keep clean (old behavior)
        if m.chat.type == enums.ChatType.PRIVATE:
            # Don't instant delete if it's a link that we already tracked for 60s
            if not _has_url(text):
                try: 
                    await m.delete()
                except Exception: pass
    except Exception:
        pass

# ============== BOT messages - FIXED FILTER ==============
def _bot_msg_filter(_, __, m: Message):
    """FIXED: Catch ALL bot messages - outgoing, from bot, with keyboard, command-like text"""
    if not m or getattr(m, "service", None): return False
    # Always catch outgoing (bot's own)
    if getattr(m, "outgoing", False):
        return True
    from_user = getattr(m, "from_user", None)
    # No from_user => likely bot/channel
    if from_user is None:
        return True
    # From bot itself
    if getattr(from_user, "is_bot", False):
        return True
    # Has inline keyboard => 99% bot menu
    if _has_keyboard(getattr(m, "reply_markup", None)):
        return True
    # Text looks like bot response (short + keywords)
    txt = (getattr(m, "text", "") or getattr(m, "caption", "") or "").lower()
    if txt and len(txt) < 2000:
        bot_indicators = ("⚡", "url uploader", "bimbo", "bot statistics", "command", "help", "status", "premium", "admin")
        if any(k in txt for k in bot_indicators):
            return True
    return False

_bot_msg_filter = filters.create(_bot_msg_filter)

@Client.on_message(_bot_msg_filter, group=-4)
@Client.on_edited_message(_bot_msg_filter, group=-4)
async def track_bot_message(client: Client, m: Message):
    try:
        text = getattr(m, "text", None) or getattr(m, "caption", "") or ""
        reply_markup = getattr(m, "reply_markup", None)

        # 1. Active progress -> keep forever (don't delete)
        if _is_progress(text):
            await _invalidate(m); return

        # 2. Final media -> PERMANENT (screenshots included)
        if _is_media_message(m):
            await _mark_perm(m); return

        # 3. Success / Error / Menu / Text -> AUTO_SEC
        if _is_success(text):
            await _track_msg(m, BOT_SUCCESS_DELAY, reason="bot_success"); return
        if _is_error(text):
            await _track_msg(m, BOT_ERROR_DELAY, reason="bot_error"); return
        if _has_keyboard(reply_markup):
            await _track_msg(m, BOT_MENU_DELAY, reason="bot_menu"); return

        # 4. Plain bot text / command photos -> AUTO_SEC
        await _track_msg(m, BOT_TEXT_DELAY, reason="bot_text")
    except Exception:
        pass

# ============== REAPER ==============
async def _cleanup_reaper(client: Client):
    await asyncio.sleep(2)
    logger.info(f"✅ cleaner reaper v9.0 running - delete in {AUTO_SEC}s (FIXED)")
    while True:
        try:
            await asyncio.sleep(REAP_INTERVAL)
            now = time.time()
            to_delete = []
            async with _TRACK_LOCK:
                for key, info in list(_TRACK.items()):
                    if info.get("perm"): continue
                    if now >= info.get("ts", 0):
                        to_delete.append(key)
                        _TRACK.pop(key, None)
            if not to_delete: continue
            by_chat: Dict[int, list] = {}
            for cid, mid in to_delete:
                by_chat.setdefault(cid, []).append(mid)
            for cid, mids in by_chat.items():
                try:
                    await client.delete_messages(cid, mids)
                    logger.debug(f"🧹 Deleted {len(mids)} msgs in chat {cid}")
                except FloodWait as fw:
                    await asyncio.sleep(fw.value)
                except Exception:
                    for mid in mids:
                        try: await client.delete_messages(cid, mid)
                        except Exception: pass
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.debug(f"Reaper error: {e}")
            await asyncio.sleep(2)

async def start_cleaner(client: Client):
    global _reaper_started
    if _reaper_started: return
    _reaper_started = True
    asyncio.create_task(_cleanup_reaper(client))
    logger.info("🧹 Auto-cleaner v9.0 FIXED started")

@Client.on_message(filters.all, group=-999)
async def _first_update_starter(client: Client, m: Message):
    await start_cleaner(client)

logger.info(f"✅ auto_cleaner v9.0 FIXED loaded | DELETE={AUTO_SEC}s | media=KEEP | screenshots=KEEP | progress=KEEP | BUGFIX: bot responses now delete")
