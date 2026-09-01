# BIMBO v4.0 - Core Commands (status, help, cancel, maintenance ban checks)
import os
import time
import asyncio
import logging

from pyrogram import Client, filters, enums
from pyrogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
)
from pyrogram.errors import FloodWait

from config import Config
from translation import Translation
from database.adduser import AddUser
from database.access import bimbo
from database.users_chats_db import db
from utils import is_admin, humanbytes
from plugins.forcesub import handle_force_sub
from plugins.premium_plans import track_referral_if_any
from plugins.stickers import send_sticker

import psutil

logger = logging.getLogger(__name__)


# ============== Cross-version safe command filter (avoids tuple/list Pyrogram bug) ==============
def _cmd(*names):
    names = [n.lower().lstrip("/") for n in names]
    def f(_flt, _client, m: Message):
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


_CMD_START_HELP_CANCEL = _cmd("start", "help", "cancel")


# =================== GLOBAL MESSAGE FILTERS (ban + maintenance) ===================
@Client.on_message(filters.private & ~_CMD_START_HELP_CANCEL, group=-1)
async def gatekeeper(client: Client, m: Message):
    """Pre-process every private message: ban/maintenance/fsub/running user checks."""
    uid = m.from_user.id if m.from_user else None
    if not uid:
        return

    # Check if the message is too old (updates flood protection on startup)
    msg_age = time.time() - m.date.timestamp() if getattr(m, "date", None) else 0
    if msg_age > 120:  # Older than 2 minutes
        logger.info(f"Gatekeeper: Discarded old message (age: {msg_age:.1f}s) to prevent startup overload.")
        m.stop_propagation()
        return

    # Ban check
    if await db.is_banned(uid):
        try:
            await m.reply_text("🚫 You are banned from using this bot. Contact @Bimbo69")
        except Exception:
            pass
        m.stop_propagation()
        return
    # Maintenance
    if Config.MAINTENANCE_MODE and not is_admin(uid):
        try:
            await m.reply_text(Translation.MAINTENANCE_MSG)
        except Exception:
            pass
        m.stop_propagation()
        return


# =================== HELP (unified) - FIXED AUTO-DELETE 10s ===================
@Client.on_message(filters.private & _cmd("help"))
async def help_cmd(client: Client, m: Message):
    await AddUser(client, m)
    bot_msg = await m.reply_text(
        Translation.BIMBO_HELP_TEXT,
        parse_mode=enums.ParseMode.HTML,
        disable_web_page_preview=True,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🏠 Home", callback_data="home"),
             InlineKeyboardButton("✖️ Close", callback_data="close")]
        ])
    )
    # ✅ FIX: Auto-delete both user cmd + bot response in 10s
    try:
        from plugins.auto_cleaner import schedule_delete_both
        await schedule_delete_both(client, m, bot_msg)
    except Exception:
        pass


# =================== START (unified, supports referrals and verify) ===================
@Client.on_message(filters.private & _cmd("start"))
async def start_cmd(client: Client, m: Message):
    await AddUser(client, m)

    # Force sub
    if Config.BIMBO_UPDATES_CHANNEL is not None:
        back = await handle_force_sub(client, m)
        if back == 400:
            return

    uid = m.from_user.id
    # Parse payload manually (m.command is None with custom filter)
    parts = (m.text or "").strip().split()
    payload = parts[1] if len(parts) > 1 else ""

    # Referral tracking
    if payload.startswith("ref"):
        await track_referral_if_any(client, payload, uid)

    # Verify flow (from URL shortener)
    if payload.startswith("verify-"):
        parts = payload.split("-")
        if len(parts) >= 3:
            userid = parts[1]
            token = parts[2] if len(parts) == 3 else "-".join(parts[2:])
            if str(uid) != str(userid):
                return await m.reply_text("<b>⚠️ Invalid / expired link.</b>")
            from utils import check_token, verify_user, check_verification
            valid = await check_token(client, userid, token)
            if valid:
                await verify_user(client, userid, token)
                await m.reply_text(
                    f"<b>✅ Hello {m.from_user.mention}!</b>\n\n"
                    f"Verification successful! You can now download files "
                    f"for today without limits."
                )
                return
            else:
                return await m.reply_text("<b>⚠️ Link already used or expired.</b>")

    # 🐱 LadyCat greeting sticker (welcome ke saath) — fail ho to ignore
    await send_sticker(client, m.chat.id, mood="start", reply_to=m.id)

    # Custom start msg? If owner set custom, use it else new PRO design
    try:
        if Config.BIMBO_START_MSG:
            start_text = Config.BIMBO_START_MSG.format(
                mention=m.from_user.mention,
                id=m.from_user.id,
                first=m.from_user.first_name
            )
        else:
            start_text = Translation.BIMBO_START_TEXT.format(m.from_user.mention, m.from_user.id)
    except Exception:
        # Fallback old style
        try:
            start_text = Translation.BIMBO_START_TEXT.format(m.from_user.mention, m.from_user.id)
        except Exception:
            start_text = Translation.BIMBO_START_TEXT

    # ⚡ NEW SHORT 2x2 BUTTONS - FULL WORKING
    buttons = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🛠️ Help", callback_data="help"),
            InlineKeyboardButton("📊 Stats", callback_data="status"),
        ],
        [
            InlineKeyboardButton("📢 Updates", url="https://t.me/Bimbobot69"),
            InlineKeyboardButton("👥 Support", url="https://t.me/Bimbo69"),
        ],
    ])

    # Try to get start image from multiple sources (priority order):
    # 1. Admin panel start pic
    # 2. Config BIMBO_START_PIC
    # 3. Random from progress images folder
    start_pic = None
    
    # Check admin panel start pic first
    try:
        from plugins.admin_panel import get_start_pic as _get_start_pic
        admin_start = _get_start_pic()
        if admin_start and os.path.exists(admin_start):
            start_pic = admin_start
            logger.info(f"Using admin panel start pic: {start_pic}")
    except Exception as e:
        logger.debug(f"Admin start pic check failed: {e}")
    
    # Then check Config
    if not start_pic and Config.BIMBO_START_PIC:
        start_pic = Config.BIMBO_START_PIC
        logger.info(f"Using config start pic: {start_pic}")
    
    # Fall back to random image from images/ folder
    if not start_pic:
        try:
            from plugins.admin_panel import get_random_progress_image
            start_pic = get_random_progress_image()
            if start_pic:
                logger.info(f"Using random progress image as start pic: {start_pic}")
        except Exception as e:
            logger.debug(f"Random image fallback failed: {e}")
    
    # Send photo if we have one - FIXED AUTO-DELETE
    if start_pic:
        try:
            bot_msg = await client.send_photo(m.chat.id, start_pic, caption=start_text,
                                    parse_mode=enums.ParseMode.HTML,
                                    reply_markup=buttons,
                                    reply_to_message_id=m.id)
            # ✅ FIX: Track both for 10s delete
            try:
                from plugins.auto_cleaner import schedule_delete_both
                await schedule_delete_both(client, m, bot_msg)
            except Exception:
                pass
            return
        except Exception as e:
            logger.debug(f"Start photo failed: {e}")
    
    # Fallback: text only - FIXED AUTO-DELETE
    bot_msg = await m.reply_text(start_text, parse_mode=enums.ParseMode.HTML,
                       reply_markup=buttons, disable_web_page_preview=True,
                       reply_to_message_id=m.id)
    try:
        from plugins.auto_cleaner import schedule_delete_both
        await schedule_delete_both(client, m, bot_msg)
    except Exception:
        pass


# =================== CANCEL ===================
@Client.on_message(filters.private & _cmd("cancel"))
async def cancel_cmd(client: Client, m: Message):
    bot_msg = await m.reply_text(Translation.BIMBO_CANCEL_STR)
    try:
        from plugins.auto_cleaner import schedule_delete_both
        await schedule_delete_both(client, m, bot_msg)
    except:
        pass


# =================== CALLBACKS for start/help/about/tools/cloud menus ===================
@Client.on_callback_query(filters.regex(r"^(home|help|about|close|status|plans|tools_menu|cloud_menu)$"))
async def menu_cbs(client: Client, c: CallbackQuery):
    d = c.data
    if d == "close":
        try:
            await c.message.delete()
        except Exception:
            pass
        return
    if d == "home":
        try:
            txt = Translation.BIMBO_START_TEXT.format(c.from_user.mention, c.from_user.id)
        except Exception:
            txt = Translation.BIMBO_START_TEXT
        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🛠️ Tools Menu", callback_data="tools_menu"),
                InlineKeyboardButton("📊 Stats", callback_data="status"),
            ],
            [
                InlineKeyboardButton("📢 Updates", url="https://t.me/Bimbobot69"),
                InlineKeyboardButton("👥 Support", url="https://t.me/Bimbo69"),
            ],
        ])
    elif d == "help":
        txt = Translation.BIMBO_HELP_TEXT
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🏠 Home", callback_data="home"),
             InlineKeyboardButton("✖️ Close", callback_data="close")]
        ])
    elif d == "about":
        txt = Translation.BIMBO_ABOUT_TEXT
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🏠 Home", callback_data="home"),
             InlineKeyboardButton("✖️ Close", callback_data="close")]
        ])
    elif d == "plans":
        from plugins.premium_plans import PLANS
        p = await db.get_premium(c.from_user.id)
        s = ("✅ Premium Active" if p else "🆓 Free User")
        txt = (f"💎 **Premium Plans**\n\nStatus: {s}\n\n"
               f"Weekly - {PLANS['1w']['price']}\n"
               f"Monthly - {PLANS['1m']['price']}\n"
               f"3 Months - {PLANS['3m']['price']}\n\n"
               f"Use /plan for details. Contact @Bimbo69 to buy.")
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("👨‍💻 Buy", url="https://t.me/Bimbo69")],
            [InlineKeyboardButton("🏠 Home", callback_data="home")],
        ])
    elif d == "status":
        disk = psutil.disk_usage(Config.BIMBO_DOWNLOAD_LOCATION)
        ram = psutil.virtual_memory()
        txt = (f"📊 **Bot Status**\n\n"
               f"CPU: `{psutil.cpu_percent()}%`\n"
               f"RAM: `{ram.percent}%` ({humanbytes(ram.used)}/{humanbytes(ram.total)})\n"
               f"Disk free: `{humanbytes(disk.free)}`\n"
               f"Workers: `{Config.BIMBO_WORKERS}` | Conc: `{Config.BIMBO_MAX_CONCURRENT_TASKS}`\n"
               f"Maintenance: `{'ON' if Config.MAINTENANCE_MODE else 'OFF'}`")
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Home", callback_data="home")]])
    elif d == "tools_menu":
        txt = ("🎬 **Media Tools**\n\n"
               "Reply to a video/file with any of these:\n\n"
               "• /ss [n] — screenshots\n"
               "• /sample [secs] — sample video\n"
               "• /trim start end — cut video\n"
               "• /compress [low|med|high]\n"
               "• /wm text [pos] — watermark\n"
               "• /mp3 — extract audio\n"
               "• /unzip — extract zip\n"
               "• /rename new_name — rename\n\n"
               "Direct site commands:\n"
               "/ig /tt /fb /tw /m3u8 /pd")
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Home", callback_data="home")]])
    elif d == "cloud_menu":
        txt = ("☁️ **Cloud Upload**\n\n"
               "Reply to a file with:\n"
               "• /stream — website video stream link (24h auto-expire)\n"
               "• /mega — upload to Mega (requires creds)\n"
               "• /gdrive — upload to Google Drive (SA creds)\n")
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Home", callback_data="home")]])
    try:
        # ✅ FIX HELP BUTTON: Use safe_edit that works for both photo + text messages
        from utils import safe_edit_text_or_caption
        await safe_edit_text_or_caption(c.message, txt, parse_mode=enums.ParseMode.HTML,
                                        reply_markup=kb)
        # ✅ FIX: Reset auto-delete timer to 10s after each button click
        try:
            from plugins.auto_cleaner import track_bot_response
            await track_bot_response(c.message, reason=f"menu_{d}")
        except Exception:
            pass
    except Exception as e:
        logger.debug(f"menu_cbs edit failed: {e}")
        try:
            # Fallback: try edit_text then edit_caption
            await c.message.edit_text(txt, parse_mode=enums.ParseMode.HTML,
                                      reply_markup=kb, disable_web_page_preview=True)
        except Exception:
            try:
                await c.message.edit_caption(caption=txt, parse_mode=enums.ParseMode.HTML,
                                             reply_markup=kb)
            except Exception:
                pass
    try:
        await c.answer()
    except Exception:
        pass
