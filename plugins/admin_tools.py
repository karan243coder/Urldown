# BIMBO v4.0 — Admin Tools Plugin
# Commands (owner/admin only):
#   /admin        - open admin panel (inline keyboard)
#   /stats        - bot usage statistics
#   /ban <id/reply> [reason]
#   /unban <id/reply>
#   /banlist
#   /broadcast    - reply to msg → broadcast to all users (supports media)
#   /addpremium <id> <days>
#   /delpremium <id>
#   /backup       - send DB export (if mongo reachable)
#   /maintenance on|off
#   /clearcache   - wipe downloads folder
import os
import io
import time
import json
import asyncio
import logging
import shutil
from datetime import datetime, timedelta

import psutil
from pyrogram import Client, filters, enums
from pyrogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton,
    InputMediaPhoto, InputMediaVideo, InputMediaDocument, InputMediaAudio,
)
from pyrogram.errors import FloodWait, InputUserDeactivated, UserIsBlocked, PeerIdInvalid

from config import Config
from translation import Translation
from database.access import bimbo
from database.users_chats_db import db
from utils import is_admin, humanbytes, time_formatter

logger = logging.getLogger(__name__)


# ---- helpers ----
def _kb_admin():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Stats", callback_data="admin_stats"),
         InlineKeyboardButton("📢 Broadcast", callback_data="admin_bc")],
        [InlineKeyboardButton("🚫 Ban List", callback_data="admin_banlist"),
         InlineKeyboardButton("💎 Premium List", callback_data="admin_premium")],
        [InlineKeyboardButton("🧹 Clean Cache", callback_data="admin_clear"),
         InlineKeyboardButton("🔧 Maintenance", callback_data="admin_maint")],
        [InlineKeyboardButton("💾 Backup DB", callback_data="admin_backup"),
         InlineKeyboardButton("✖️ Close", callback_data="close")],
    ])


# ============== /admin ==============

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


@Client.on_message(filters.private & _cmd('admin', 'panel'))
async def admin_panel(client: Client, m: Message):
    if not is_admin(m.from_user.id):
        return await m.reply_text(Translation.NOT_AUTHORIZED)
    total = await bimbo.total_users_count()
    bans = await db.ban_list()
    disk = psutil.disk_usage(Config.BIMBO_DOWNLOAD_LOCATION)
    ram = psutil.virtual_memory()
    text = (
        f"👑 **BIMBO Admin Panel (v4.0)**\n\n"
        f"👥 Total users: `{total}`\n"
        f"🚫 Banned: `{len(bans)}`\n"
        f"🛠 Maintenance: `{'ON' if Config.MAINTENANCE_MODE else 'OFF'}`\n\n"
        f"💻 CPU: `{psutil.cpu_percent()}%`\n"
        f"🧠 RAM: `{ram.percent}%` ({humanbytes(ram.used)}/{humanbytes(ram.total)})\n"
        f"💾 Disk: `{disk.percent}%` (free {humanbytes(disk.free)})\n"
        f"⏱ Uptime: `{time_formatter(time.time() - psutil.boot_time())}`"
    )
    await m.reply_text(text, reply_markup=_kb_admin())


# ============== /stats ==============
@Client.on_message(filters.private & _cmd('stats'))
async def stats_cmd(client: Client, m: Message):
    if not is_admin(m.from_user.id):
        return await m.reply_text(Translation.NOT_AUTHORIZED)
    total = await bimbo.total_users_count()
    today = await db.get_stat("today_downloads") or 0
    total_dl = await db.get_stat("total_downloads") or 0
    disk = psutil.disk_usage(Config.BIMBO_DOWNLOAD_LOCATION)
    text = (
        f"📊 **Bot Statistics**\n\n"
        f"👥 Users: `{total}`\n"
        f"📥 Today downloads: `{today}`\n"
        f"📦 Total downloads: `{total_dl}`\n"
        f"💾 Disk free: `{humanbytes(disk.free)}`\n"
    )
    await m.reply_text(text)


# ============== BAN / UNBAN ==============
@Client.on_message(filters.private & _cmd('ban'))
async def ban_cmd(client: Client, m: Message):
    if not is_admin(m.from_user.id):
        return await m.reply_text(Translation.NOT_AUTHORIZED)
    uid = None; reason = ""
    if m.reply_to_message and m.reply_to_message.from_user:
        uid = m.reply_to_message.from_user.id
        rest = (m.text or "").split(None, 1)
        reason = rest[1] if len(rest) > 1 else ""
    else:
        parts = (m.text or "").split()
        if len(parts) >= 2 and parts[1].isdigit():
            uid = int(parts[1])
            reason = parts[2] if len(parts) > 2 else ""
    if not uid:
        return await m.reply_text("Usage: <code>/ban user_id reason</code> ya kisi user ke message pe reply karke /ban")
    if is_admin(uid):
        return await m.reply_text("❌ Cannot ban another admin/owner.")
    await db.ban_user(uid, reason)
    await m.reply_text(f"🚫 Banned user `{uid}`. Reason: {reason or 'n/a'}")


@Client.on_message(filters.private & _cmd('unban'))
async def unban_cmd(client: Client, m: Message):
    if not is_admin(m.from_user.id):
        return await m.reply_text(Translation.NOT_AUTHORIZED)
    uid = None
    if m.reply_to_message and m.reply_to_message.from_user:
        uid = m.reply_to_message.from_user.id
    else:
        parts = (m.text or "").split()
        if len(parts) >= 2 and parts[1].isdigit():
            uid = int(parts[1])
    if not uid:
        return await m.reply_text("Usage: <code>/unban user_id</code>")
    await db.unban_user(uid)
    await m.reply_text(f"✅ Unbanned user `{uid}`")


@Client.on_message(filters.private & _cmd('banlist'))
async def banlist_cmd(client: Client, m: Message):
    if not is_admin(m.from_user.id):
        return await m.reply_text(Translation.NOT_AUTHORIZED)
    bans = await db.ban_list()
    if not bans:
        return await m.reply_text("✅ No banned users.")
    text = "🚫 **Banned users:**\n\n" + "\n".join(f"• `{uid}`" for uid in bans[:100])
    if len(bans) > 100:
        text += f"\n\n...and {len(bans)-100} more."
    await m.reply_text(text)


# ============== BROADCAST ==============
@Client.on_message(filters.private & _cmd('broadcast', 'bc'))
async def broadcast_cmd(client: Client, m: Message):
    if not is_admin(m.from_user.id):
        return await m.reply_text(Translation.NOT_AUTHORIZED)
    if not m.reply_to_message:
        return await m.reply_text("📌 Kisi message (text/photo/video/doc) pe reply karke /broadcast bhejo.")
    src = m.reply_to_message
    status = await m.reply_text("📣 Broadcasting...")
    users = await bimbo.get_all_users()
    done = 0; fail = 0
    async for u in users:
        uid = u.get("id") or u.get("_id")
        if not uid:
            continue
        try:
            if src.photo:
                await client.send_photo(uid, src.photo.file_id, caption=src.caption or "")
            elif src.video:
                await client.send_video(uid, src.video.file_id, caption=src.caption or "")
            elif src.document:
                await client.send_document(uid, src.document.file_id, caption=src.caption or "")
            elif src.audio:
                await client.send_audio(uid, src.audio.file_id, caption=src.caption or "")
            elif src.text:
                await client.send_message(uid, src.text.html if src.text else "")
            done += 1
        except FloodWait as e:
            await asyncio.sleep(e.value + 1)
            try:
                if src.text:
                    await client.send_message(uid, src.text.html)
                done += 1
            except Exception:
                fail += 1
        except (InputUserDeactivated, UserIsBlocked, PeerIdInvalid):
            await bimbo.delete_user(uid)
            fail += 1
        except Exception:
            fail += 1
        if (done + fail) % 50 == 0:
            try:
                await status.edit_text(f"📣 Broadcasting...\n✅ Sent: {done}\n❌ Failed: {fail}")
            except Exception:
                pass
        await asyncio.sleep(0.1)
    await status.edit_text(f"✅ Broadcast complete!\n\n✅ Sent: {done}\n❌ Failed/removed: {fail}")


# ============== PREMIUM ADMIN ==============
@Client.on_message(filters.private & _cmd('addpremium', 'gifted'))
async def add_premium(client: Client, m: Message):
    if not is_admin(m.from_user.id):
        return await m.reply_text(Translation.NOT_AUTHORIZED)
    parts = (m.text or "").split()
    if len(parts) < 3 or not parts[1].isdigit() or not parts[2].isdigit():
        return await m.reply_text("Usage: <code>/addpremium user_id days</code>")
    uid = int(parts[1]); days = int(parts[2])
    exp = time.time() + days * 86400
    await db.set_premium(uid, exp, plan="premium")
    await m.reply_text(f"💎 Premium granted to `{uid}` for {days} days.\nExpires: <code>{datetime.utcfromtimestamp(exp)}</code>")
    try:
        await client.send_message(uid, f"💎 Aapko Premium mil gaya hai! ({days} din ke liye)\n\nUse /plan for details.")
    except Exception:
        pass


@Client.on_message(filters.private & _cmd('delpremium', 'removepremium'))
async def del_premium(client: Client, m: Message):
    if not is_admin(m.from_user.id):
        return await m.reply_text(Translation.NOT_AUTHORIZED)
    parts = (m.text or "").split()
    uid = None
    if m.reply_to_message and m.reply_to_message.from_user:
        uid = m.reply_to_message.from_user.id
    elif len(parts) >= 2 and parts[1].isdigit():
        uid = int(parts[1])
    if not uid:
        return await m.reply_text("Usage: <code>/delpremium user_id</code>")
    await db.remove_premium(uid)
    await m.reply_text(f"✅ Premium removed for `{uid}`.")


# ============== BACKUP ==============
@Client.on_message(filters.private & _cmd('backup'))
async def backup_cmd(client: Client, m: Message):
    if not is_admin(m.from_user.id):
        return await m.reply_text(Translation.NOT_AUTHORIZED)
    if db._use_fb:
        return await m.reply_text("⚠️ DB_URI set nahi hai, in-memory mode me backup nahi nikal sakte.")
    msg = await m.reply_text("💾 Building DB backup...")
    try:
        collections = ["users", "bans", "premium", "thumbs", "settings", "stats"]
        out = {}
        for c in collections:
            coll = getattr(db, c)
            out[c] = []
            async for doc in coll.find({}):
                doc.pop("_id", None)
                out[c].append(doc)
        data = json.dumps(out, indent=2, default=str).encode("utf-8")
        buf = io.BytesIO(data)
        buf.name = f"bimbo_backup_{int(time.time())}.json"
        await m.reply_document(buf, caption="✅ Database backup")
        await msg.delete()
    except Exception as e:
        await msg.edit_text(f"❌ Backup failed: <code>{e}</code>")


# ============== MAINTENANCE ==============
@Client.on_message(filters.private & _cmd('maintenance'))
async def maintenance_cmd(client: Client, m: Message):
    if not is_admin(m.from_user.id):
        return await m.reply_text(Translation.NOT_AUTHORIZED)
    parts = (m.text or "").split()
    if len(parts) < 2 or parts[1].lower() not in ("on", "off"):
        return await m.reply_text("Usage: <code>/maintenance on|off</code>")
    Config.MAINTENANCE_MODE = (parts[1].lower() == "on")
    await m.reply_text(f"🔧 Maintenance mode {'ENABLED' if Config.MAINTENANCE_MODE else 'DISABLED'}.")


# ============== ADMIN CALLBACKS ==============
@Client.on_callback_query(filters.regex(r"^admin_"))
async def admin_callbacks(client, c):
    if not is_admin(c.from_user.id):
        return await c.answer("Not authorized", show_alert=True)
    data = c.data
    if data == "admin_stats":
        total = await bimbo.total_users_count()
        disk = psutil.disk_usage(Config.BIMBO_DOWNLOAD_LOCATION)
        ram = psutil.virtual_memory()
        text = (f"📊 Stats\n\nUsers: {total}\nCPU: {psutil.cpu_percent()}% | RAM: {ram.percent}%\n"
                f"Disk free: {humanbytes(disk.free)}")
        await c.message.edit_text(text, reply_markup=_kb_admin())
    elif data == "admin_banlist":
        bans = await db.ban_list()
        text = "🚫 Banned:\n" + ("\n".join(f"`{u}`" for u in bans[:100]) if bans else "No bans.")
        await c.message.edit_text(text, reply_markup=_kb_admin())
    elif data == "admin_clear":
        d = Config.BIMBO_DOWNLOAD_LOCATION
        removed = 0
        for root, dirs, files in os.walk(d, topdown=False):
            if ".aria2" in root: continue
            for f in files:
                try: os.remove(os.path.join(root, f)); removed += 1
                except Exception: pass
            for dr in dirs:
                try: shutil.rmtree(os.path.join(root, dr), ignore_errors=True); removed += 1
                except Exception: pass
        await c.answer(f"Cache cleared: {removed} items", show_alert=True)
    elif data == "admin_maint":
        Config.MAINTENANCE_MODE = not Config.MAINTENANCE_MODE
        await c.answer(f"Maintenance: {'ON' if Config.MAINTENANCE_MODE else 'OFF'}", show_alert=True)
    elif data == "admin_backup":
        await c.answer("Use /backup command", show_alert=True)
    elif data == "admin_premium":
        # list premium users
        if db._use_fb:
            prems = db._fallback.get("premium", {})
            items = [f"`{k}` → exp <code>{v.get('expires',0)}</code>" for k,v in list(prems.items())[:50]]
        else:
            items = []
            async for doc in db.premium.find({}):
                items.append(f"`{doc.get('id')}` → exp <code>{doc.get('expires',0)}</code>")
                if len(items) >= 50: break
        text = "💎 Premium users:\n\n" + ("\n".join(items) if items else "No premium users.")
        await c.message.edit_text(text, reply_markup=_kb_admin())
    elif data == "admin_bc":
        await c.answer("Use /broadcast (reply to a msg)", show_alert=True)
