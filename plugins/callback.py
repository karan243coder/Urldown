# BIMBO URL Bot
# Powered by BIMBO | Support: @Bimbo69

import logging
import time
from config import Config
from pyrogram import filters
from pyrogram.errors import UserNotParticipant
from pyrogram import Client as BimboBot
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from plugins.youtube_dl_button import youtube_dl_call_back, terabox_call_back
from plugins.dl_button import ddl_call_back
from translation import Translation
from utils import safe_edit_text_or_caption
from plugins.forcesub import get_invite_link
from plugins.media_pipeline import begin_interactive_job, end_interactive_job

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logging.getLogger("pyrogram").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


@BimboBot.on_callback_query(filters.regex('^X0$'))
async def delt(bot, update):
    await update.message.delete(True)


# IMPORTANT:
# This handler ONLY processes yt-dlp/ddl/terabox/direct/force-sub routes.
# It uses a WHITELIST of prefixes to avoid intercepting callbacks owned by
# other plugins (xhamster_upgrade, commands, admin_panel, torrent_search, ...).
# Those plugins have their own on_callback_query handlers (with regex filters)
# that are registered before this catch-all and fire first.
@BimboBot.on_callback_query(filters.create(lambda _, __, cq: _is_owned_callback(cq.data)))
async def button(bot, update):
    try:
        cb_data = update.data or ""
        logger.info(f"Callback (core): {cb_data[:80]}")
        
        user_id = update.from_user.id if update.from_user else 0

        if cb_data.startswith("terabox="):
            logger.info("Routing to terabox_call_back")
            try:
                await safe_edit_text_or_caption(update.message, "⏳ **Queue me hain...**\n\nWaiting for an active download slot...")
            except Exception:
                pass
            
            from utils import GLOBAL_DOWNLOAD_SEM
            from plugins.preemption_manager import pause_bulk_jobs, resume_bulk_jobs
            
            async with GLOBAL_DOWNLOAD_SEM:
                paused_jobs = await pause_bulk_jobs(user_id)
                try:
                    await terabox_call_back(bot, update)
                finally:
                    if paused_jobs:
                        await resume_bulk_jobs(user_id, bot)

        elif "|" in cb_data:
            logger.info("Routing to youtube_dl_call_back")
            try:
                await safe_edit_text_or_caption(update.message, "⏳ **Queue me hain...**\n\nWaiting for an active download slot...")
            except Exception:
                pass
            
            # Active bulk downloads finish naturally; this interactive single
            # gets the next free slot before any new bulk item.
            interactive_id = f"single_{user_id}_{time.time_ns()}"
            await begin_interactive_job(interactive_id)
            try:
                await youtube_dl_call_back(bot, update, priority=100)
            finally:
                await end_interactive_job(interactive_id)

        elif cb_data.startswith(("file=DIRECT=", "video=DIRECT=", "audio=DIRECT=")):
            # Route direct links through yt-dlp engine (headers, aria2, resume)
            tg_type, _, ext = cb_data.split("=", 2)
            update.data = f"{tg_type}|AUTO|{ext}|direct_{int(time.time())}"
            logger.info(f"Routing DIRECT link via yt-dlp ({tg_type})")
            try:
                await safe_edit_text_or_caption(update.message, "⏳ **Queue me hain...**\n\nWaiting for an active download slot...")
            except Exception:
                pass
            
            # Active bulk downloads finish naturally; this interactive single
            # gets the next free slot before any new bulk item.
            interactive_id = f"single_{user_id}_{time.time_ns()}"
            await begin_interactive_job(interactive_id)
            try:
                await youtube_dl_call_back(bot, update, priority=100)
            finally:
                await end_interactive_job(interactive_id)

        elif cb_data.startswith(("file=", "video=", "audio=")) and not cb_data.startswith((
            "file=DIRECT=", "video=DIRECT=", "audio=DIRECT="
        )):
            logger.info("Routing to ddl_call_back")
            try:
                await safe_edit_text_or_caption(update.message, "⏳ **Queue me hain...**\n\nWaiting for an active download slot...")
            except Exception:
                pass
            
            from utils import GLOBAL_DOWNLOAD_SEM
            from plugins.preemption_manager import pause_bulk_jobs, resume_bulk_jobs
            
            async with GLOBAL_DOWNLOAD_SEM:
                paused_jobs = await pause_bulk_jobs(user_id)
                try:
                    await ddl_call_back(bot, update)
                finally:
                    if paused_jobs:
                        await resume_bulk_jobs(user_id, bot)

        elif "refreshForceSub" in cb_data:
            if Config.BIMBO_UPDATES_CHANNEL:
                if str(Config.BIMBO_UPDATES_CHANNEL).startswith("-100"):
                    channel_chat_id = int(Config.BIMBO_UPDATES_CHANNEL)
                else:
                    channel_chat_id = Config.BIMBO_UPDATES_CHANNEL
                try:
                    user = await bot.get_chat_member(channel_chat_id, update.message.chat.id)
                    if user.status == "kicked":
                        await update.message.edit(
                            text="Sorry Sir, You are Banned to use me. Contact my [owner](https://t.me/bimbobot69).",
                            disable_web_page_preview=True
                        )
                        return
                except UserNotParticipant:
                    invite_link = await get_invite_link(bot, channel_chat_id)
                    await update.message.edit(
                        text="**I like Your Smartness But Don't be Oversmart! 😑**\n\n",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("🤖 Join Updates Channel", url=invite_link.invite_link)],
                            [InlineKeyboardButton("🔄 Refresh 🔄", callback_data="refreshForceSub")],
                        ])
                    )
                    return
                except Exception:
                    await update.message.edit(
                        text="Something went Wrong. Contact my [owner](https://t.me/bimbobot69).",
                        disable_web_page_preview=True
                    )
                    return
            try:
                start_txt = Translation.BIMBO_START_TEXT.format(update.from_user.mention, update.from_user.id)
            except Exception:
                start_txt = Translation.BIMBO_START_TEXT
            await update.message.edit(
                text=start_txt,
                reply_markup=Translation.BIMBO_START_BUTTONS,
            )

        # anything else matched the whitelist but no route -> ignore silently
        return

    except Exception as e:
        err_msg = str(e)
        if "MessageNotModified" in err_msg or "query is too old" in err_msg:
            return
        logger.error(f"Callback error: {e}", exc_info=True)
        try:
            await update.answer("Error, try again", show_alert=True)
        except Exception:
            pass


def _is_owned_callback(data: str) -> bool:
    """Return True only for callbacks THIS handler should process."""
    if not data:
        return False
    # Exclude callbacks owned by other plugins
    # xhamster_upgrade
    if data.startswith(("xh_q::", "xh_pg::", "xh_vid::", "xh_back::",
                        "xh_dl::", "xh_best::", "xh_album::")):
        return False
    # commands.py menu (home/help/about/close/status/plans/tools_menu/cloud_menu)
    if data in {"home", "help", "about", "close", "status", "plans",
                "tools_menu", "cloud_menu"}:
        return False
    # language
    if data.startswith("set_lang_"):
        return False
    # admin_panel / admin_tools
    if data.startswith(("admin_", "toggle_", "ban_", "broadcast_", "backup_")):
        return False
    # torrent_search
    if data.startswith(("ts_", "tss_")):
        return False
    # torrent_manager
    if data.startswith("cancel_torrent_"):
        return False
    # system_status
    if data in {"refresh_status"}:
        return False
    # premium_plans
    if data.startswith(("plan_", "buy_", "pay_")):
        return False
    # pro_settings plugin
    if data in ("settings", "st_home", "premium") or data.startswith(("st:", "st_")):
        return False
    # Our own: terabox routes
    if data.startswith("terabox="):
        return True
    # yt-dlp pipe format  (type|format|ext|task_id)
    if "|" in data:
        return True
    # DIRECT links
    if data.startswith(("file=DIRECT=", "video=DIRECT=", "audio=DIRECT=")):
        return True
    # ddl_call_back routes (file= / video= / audio= with =-separated parts)
    if data.startswith(("file=", "video=", "audio=")):
        return True
    # forcesub
    if "refreshForceSub" in data:
        return True
    return False
