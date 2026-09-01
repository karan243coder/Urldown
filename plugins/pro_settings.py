# -*- coding: utf-8 -*-
# BIMBO v4.9 — PRO Settings Menu 🔥
# Professional-tier inline settings menu (screenshot wale bot jaisa).
# Saari settings DB me save hoti hain — user ek baar set kare, har download pe apply hoti hain.
#
# NOTE: Uses a CUSTOM command filter to avoid tuple/list argument bugs across
# different Pyrogram versions. Works on pyrogram 2.0.x, 2.1.x, 1.x.
#
import os
import re
import json
import asyncio
import logging
from datetime import datetime

from pyrogram import Client, filters
from pyrogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    InputMediaPhoto,
)
from pyrogram import enums

from config import Config
from database.access import bimbo
from utils import is_admin, humanbytes

logger = logging.getLogger(__name__)

# --------------- Settings keys + defaults ---------------
DEFAULTS = {
    "upload_mode": "video",        # video (streamable) | file (document) | audio
    "auto_rename": False,
    "rename_template": "{title}",  # can use {title} {quality} {size} {ext} {date}
    "spoiler": False,
    "screenshots": True,
    "sample_video": False,
    "watermark": False,
    "watermark_text": "@Bimbobot69",
    "delete_source": False,
    "delete_after_upload": True,
    "notify_complete": True,
    "caption_template": "🎬 **{title}**\n📥 {quality} | ⚡ BIMBO",
    "progress_style": "detailed",  # detailed | minimal | bar
    "sample_duration": 30,
    "screenshot_count": 10,
}

BOOL_KEYS = {
    "auto_rename", "spoiler", "screenshots", "sample_video", "watermark",
    "delete_source", "delete_after_upload", "notify_complete",
}

UPLOAD_MODES = [
    ("video", "VIDEO 🎬"),
    ("file",  "DOCUMENT 📁"),
    ("audio", "AUDIO 🎵"),
]


# --------------- CROSS-VERSION SAFE COMMAND FILTER ---------------
def _cmd(*names):
    """Custom command filter — works with any Pyrogram version.
    Matches messages starting with /<name> (optionally with @bot suffix)."""
    names = [n.lower().lstrip("/") for n in names]
    def f(_flt, _client, m: Message):
        if not m or not getattr(m, "text", None):
            return False
        if m.media:
            return False
        t = m.text.strip()
        if not t.startswith("/"):
            return False
        # extract first token
        first = t.split()[0][1:].split("@")[0].lower()
        return first in names
    return filters.create(f)


def _non_cmd_text():
    """Filter: private text message that is NOT a /cancel command.
    Used to catch free-text input (caption/rename/watermark)."""
    def f(_flt, _client, m: Message):
        if not m or not getattr(m, "text", None):
            return False
        if m.media:
            return False
        chat = getattr(m, "chat", None)
        if not chat:
            return False
        if str(getattr(chat, "type", "")).lower() != "private":
            return False
        t = m.text.strip()
        if t.startswith("/"):
            first = t.split()[0][1:].split("@")[0].lower()
            if first == "cancel":
                return False
        return True
    return filters.create(f)


# ---------------- Helpers ----------------
async def _gs(uid, key, default=None):
    try:
        v = await bimbo.db.get_user_setting(int(uid), key, default)
        if v is None:
            return DEFAULTS.get(key, default)
        return v
    except Exception:
        return DEFAULTS.get(key, default)


async def _ss(uid, key, value):
    try:
        await bimbo.db.set_user_setting(int(uid), key, value)
        return True
    except Exception as e:
        logger.warning(f"_ss err uid={uid} key={key}: {e}")
        return False


async def _all_settings(uid):
    s = dict(DEFAULTS)
    for k in DEFAULTS:
        try:
            v = await bimbo.db.get_user_setting(int(uid), k, None)
            if v is not None:
                s[k] = v
        except Exception:
            pass
    return s


def _onoff(b: bool) -> str:
    return "ON ✅" if b else "OFF 📴"


# ---------------- Main Menu ----------------
async def _main_menu_text(s: dict, user) -> str:
    name = getattr(user, "first_name", "User")
    return (
        f"⚙️ **Settings**\n\n"
        f"Welcome back, **{name}**! 👋\n\n"
        f"Customize your download & upload experience. "
        f"Har setting apne aap save ho jati hai aur next downloads pe apply hoti hai.\n\n"
        f"Neeche buttons se har feature ko ON/OFF karo ya configure karo:"
    )


def _main_menu_kb(s: dict) -> InlineKeyboardMarkup:
    mode_label = dict(UPLOAD_MODES).get(s["upload_mode"], "VIDEO 🎬")
    rows = [
        [
            InlineKeyboardButton(f"📤 Upload Mode: {mode_label}", callback_data="st:upload_mode"),
            InlineKeyboardButton(f"✏️ Auto Rename: {_onoff(s['auto_rename'])}", callback_data="st_tog:auto_rename:settings"),
        ],
        [
            InlineKeyboardButton(f"🌠 Spoiler: {_onoff(s['spoiler'])}", callback_data="st_tog:spoiler:settings"),
            InlineKeyboardButton("🖼️ Set Thumb / Cover", callback_data="st:thumb"),
        ],
        [
            InlineKeyboardButton(f"📸 Screen Shots: {_onoff(s['screenshots'])}", callback_data="st_tog:screenshots:settings"),
            InlineKeyboardButton(f"🎬 Sample Video: {_onoff(s['sample_video'])}", callback_data="st_tog:sample_video:settings"),
        ],
        [
            InlineKeyboardButton("📝 File & Caption", callback_data="st:caption"),
            InlineKeyboardButton("🔄 Automation", callback_data="st:automation"),
        ],
        [
            InlineKeyboardButton("⚙️ Preferences", callback_data="st:prefs"),
            InlineKeyboardButton("📊 Dashboard 📊", callback_data="st:dashboard"),
        ],
        [
            InlineKeyboardButton("📱 Open Mini App", url="https://t.me/bimbobot69"),
        ],
        [
            InlineKeyboardButton("🔄 Reset Settings ⚙️", callback_data="st:reset"),
        ],
        [
            InlineKeyboardButton("⬅️ Back", callback_data="home"),
            InlineKeyboardButton("❌ Close", callback_data="close"),
        ],
    ]
    return InlineKeyboardMarkup(rows)


# ---------------- Sub-menu keyboards ----------------
def _upload_mode_kb(s: dict):
    rows = []
    row = []
    for key, label in UPLOAD_MODES:
        active = " ✅" if s["upload_mode"] == key else ""
        row.append(InlineKeyboardButton(f"{label}{active}", callback_data=f"st_set:upload_mode:{key}"))
        if len(row) == 2:
            rows.append(row); row = []
    if row: rows.append(row)
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="settings")])
    return InlineKeyboardMarkup(rows)


def _caption_kb(s: dict):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Edit Caption Template", callback_data="st:edit_caption")],
        [InlineKeyboardButton("✏️ Edit Rename Template", callback_data="st:edit_rename_tpl")],
        [InlineKeyboardButton("🔄 Reset to Default", callback_data="st:reset_caption")],
        [InlineKeyboardButton("⬅️ Back", callback_data="settings")],
    ])


def _automation_kb(s: dict):
    rows = [
        [InlineKeyboardButton(f"🗑️ Delete Source Msg: {_onoff(s['delete_source'])}",
                              callback_data="st_tog:delete_source:automation")],
        [InlineKeyboardButton(f"🧹 Auto-Delete Progress: {_onoff(s['delete_after_upload'])}",
                              callback_data="st_tog:delete_after_upload:automation")],
        [InlineKeyboardButton(f"🔔 Completion Notification: {_onoff(s['notify_complete'])}",
                              callback_data="st_tog:notify_complete:automation")],
        [InlineKeyboardButton("⬅️ Back", callback_data="settings")],
    ]
    return InlineKeyboardMarkup(rows)


def _prefs_kb(s: dict):
    rows = [
        [InlineKeyboardButton(f"💧 Watermark: {_onoff(s['watermark'])}",
                              callback_data="st_tog:watermark:prefs")],
        [InlineKeyboardButton("✏️ Watermark Text", callback_data="st:edit_watermark")],
        [
            InlineKeyboardButton(f"🎨 Style: {s['progress_style']}", callback_data="st:style"),
        ],
        [InlineKeyboardButton("🌐 Language", callback_data="st:lang")],
        [InlineKeyboardButton("⬅️ Back", callback_data="settings")],
    ]
    return InlineKeyboardMarkup(rows)


async def _dashboard_text(uid, user, s: dict) -> str:
    try:
        total_dl = await bimbo.db.get_stat(f"downloads_{uid}") or 0
        total_bytes = await bimbo.db.get_stat(f"bytes_{uid}") or 0
    except Exception:
        total_dl = 0; total_bytes = 0
    is_prem = False
    try:
        from utils import is_premium as _ip
        is_prem = await _ip(uid)
    except Exception:
        pass
    thumb_set = False
    try:
        t = await bimbo.db.get_thumb(uid)
        thumb_set = bool(t)
    except Exception:
        pass
    name = getattr(user, "first_name", "User")
    uname = f"@{user.username}" if getattr(user, "username", None) else "(no username)"
    return (
        f"📊 **Dashboard**\n\n"
        f"👤 **Name**: {name}\n"
        f"🆔 **User ID**: `{uid}`\n"
        f"🔖 **Username**: {uname}\n"
        f"💎 **Plan**: {'Premium ⭐' if is_prem else 'Free 🆓'}\n"
        f"👑 **Admin**: {'Yes' if is_admin(uid) else 'No'}\n\n"
        f"📥 **Total Downloads**: `{total_dl}`\n"
        f"📦 **Data Used**: `{humanbytes(int(total_bytes))}`\n"
        f"🖼️ **Custom Thumb**: {'Set ✅' if thumb_set else 'Not set'}\n"
        f"📤 **Default Upload Mode**: `{s['upload_mode']}`\n"
    )


def _dashboard_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Refresh Stats", callback_data="st:dashboard")],
        [InlineKeyboardButton("⬅️ Back", callback_data="settings")],
    ])


def _thumb_kb(has_thumb: bool):
    rows = []
    if has_thumb:
        rows.append([InlineKeyboardButton("👁️ View Current Thumb", callback_data="st:view_thumb")])
        rows.append([InlineKeyboardButton("🗑️ Delete Thumb", callback_data="st:del_thumb")])
    rows.append([InlineKeyboardButton("📸 Send Photo to Set as Thumb", callback_data="st:await_thumb")])
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="settings")])
    return InlineKeyboardMarkup(rows)


# ---------------- Callback Handlers ----------------
@Client.on_callback_query(filters.regex(r"^st(_tog|_set)?:") | filters.regex(r"^(settings|st_home)$"))
async def settings_callback(client: Client, c: CallbackQuery):
    try:
        uid = c.from_user.id
        data = c.data or "settings"
        s = await _all_settings(uid)

        async def refresh(menu: str = "settings"):
            if menu == "settings":
                txt = await _main_menu_text(s, c.from_user)
                await c.message.edit_text(txt, reply_markup=_main_menu_kb(s),
                                          disable_web_page_preview=True)
            elif menu == "upload_mode":
                await c.message.edit_text(
                    f"📤 **Upload Mode**\n\n"
                    f"Choose how media should be sent to Telegram:\n"
                    f"• **Video** → streamable (plays inline, supports scrubbing)\n"
                    f"• **Document** → file (faster, shows filename)\n"
                    f"• **Audio** → music file\n\n"
                    f"Current: `{s['upload_mode']}`",
                    reply_markup=_upload_mode_kb(s))
            elif menu == "thumb":
                has = False
                try:
                    has = bool(await bimbo.db.get_thumb(uid))
                except Exception:
                    pass
                await c.message.edit_text(
                    "🖼️ **Custom Thumbnail / Cover**\n\n"
                    "Set a custom cover jo har video/document pe lagegi. "
                    "Nahi set karoge to auto-generated frame use hoga.\n\n"
                    f"Current: {'Set ✅' if has else 'Not set'}",
                    reply_markup=_thumb_kb(has))
            elif menu == "caption":
                await c.message.edit_text(
                    "📝 **File & Caption Settings**\n\n"
                    f"**Caption:**\n`{s['caption_template'][:400]}`\n\n"
                    f"**Auto Rename:** {_onoff(s['auto_rename'])}\n"
                    f"**Rename Template:** `{s['rename_template'][:200]}`\n\n"
                    "Placeholders: `{title} {quality} {size} {ext} {date}`",
                    reply_markup=_caption_kb(s))
            elif menu == "automation":
                await c.message.edit_text(
                    "🔄 **Automation Rules**\n\n"
                    "Automatic actions before/after downloads:",
                    reply_markup=_automation_kb(s))
            elif menu == "prefs":
                await c.message.edit_text(
                    "⚙️ **Preferences**\n\nCosmetic & language preferences:",
                    reply_markup=_prefs_kb(s))
            elif menu == "dashboard":
                txt = await _dashboard_text(uid, c.from_user, s)
                await c.message.edit_text(txt, reply_markup=_dashboard_kb())

        if data in ("settings", "st_home", "st:home"):
            await c.answer(); await refresh("settings"); return

        if data.startswith("st_set:"):
            parts = data.split(":", 2)
            if len(parts) >= 3:
                key, val = parts[1], parts[2]
                if key == "upload_mode" and val in dict(UPLOAD_MODES):
                    await _ss(uid, "upload_mode", val); s["upload_mode"] = val
            await c.answer("Saved ✅"); await refresh("upload_mode"); return

        if data.startswith("st_tog:"):
            parts = data.split(":", 2)
            key = parts[1] if len(parts) > 1 else ""
            back = parts[2] if len(parts) > 2 else "settings"
            if key in BOOL_KEYS:
                new_val = not bool(s.get(key, False))
                await _ss(uid, key, new_val); s[key] = new_val
                await c.answer(f"{'ON ✅' if new_val else 'OFF 📴'}")
            else:
                await c.answer("Setting not found", show_alert=True)
            back_map = {"settings": "settings", "automation": "automation",
                        "prefs": "prefs", "caption": "caption"}
            await refresh(back_map.get(back, "settings"))
            return

        if data == "st:upload_mode": await c.answer(); await refresh("upload_mode"); return
        if data == "st:thumb":       await c.answer(); await refresh("thumb"); return
        if data == "st:caption":     await c.answer(); await refresh("caption"); return
        if data == "st:automation":  await c.answer(); await refresh("automation"); return
        if data == "st:prefs":       await c.answer(); await refresh("prefs"); return
        if data == "st:dashboard":   await c.answer(); await refresh("dashboard"); return

        if data == "st:reset":
            for k, v in DEFAULTS.items():
                await _ss(uid, k, v)
            try: await bimbo.db.del_thumb(uid)
            except Exception: pass
            s = await _all_settings(uid)
            await c.answer("Reset done ✅", show_alert=True); await refresh("settings")
            return

        if data == "st:view_thumb":
            try:
                fid = await bimbo.db.get_thumb(uid)
                if fid:
                    await c.message.reply_photo(fid, caption="🖼️ Your current thumbnail")
                    await c.answer()
                else:
                    await c.answer("No thumbnail set", show_alert=True)
            except Exception as e:
                await c.answer(f"Error: {e}", show_alert=True)
            return

        if data == "st:del_thumb":
            try: await bimbo.db.del_thumb(uid); await c.answer("Thumbnail deleted 🗑️")
            except Exception as e: await c.answer(f"Error: {e}", show_alert=True)
            await refresh("thumb"); return

        if data == "st:await_thumb":
            await c.message.edit_text(
                "📸 **Set Custom Thumbnail**\n\n"
                "Ab jo bhi photo bhejoge woh custom thumb ban jayegi.\n"
                "Cancel: /cancel",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="st:thumb")]])
            )
            _AWAIT_THUMB[uid] = True
            await c.answer(); return

        if data == "st:edit_caption":
            await c.message.edit_text(
                "📝 **Edit Caption**\n\n"
                "Next message me caption template bhejo.\n"
                "Variables: `{title} {quality} {size} {ext} {date}`\nCancel: /cancel",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="st:caption")]])
            )
            _AWAIT_STATE[uid] = {"state": "caption"}
            await c.answer(); return

        if data == "st:edit_rename_tpl":
            await c.message.edit_text(
                "✏️ **Edit Rename Template**\n\n"
                "Next message me rename template bhejo. Vars: `{title} {quality} {size} {ext}`\n"
                "Example: `BIMBO_{title}_{quality}p`\nCancel: /cancel",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="st:caption")]])
            )
            _AWAIT_STATE[uid] = {"state": "rename_tpl"}
            await c.answer(); return

        if data == "st:edit_watermark":
            await c.message.edit_text(
                "💧 **Set Watermark Text**\n\n"
                "Next message me watermark text bhejo (max 30 chars).\nCancel: /cancel",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="st:prefs")]])
            )
            _AWAIT_STATE[uid] = {"state": "watermark"}
            await c.answer(); return

        if data == "st:reset_caption":
            await _ss(uid, "caption_template", DEFAULTS["caption_template"])
            await _ss(uid, "rename_template", DEFAULTS["rename_template"])
            s = await _all_settings(uid)
            await c.answer("Caption reset ✅"); await refresh("caption"); return

        if data == "st:style":
            styles = ["detailed", "minimal", "bar"]
            cur = s["progress_style"]
            nxt = styles[(styles.index(cur) + 1) % len(styles)] if cur in styles else "detailed"
            await _ss(uid, "progress_style", nxt); s["progress_style"] = nxt
            await c.answer(f"Style: {nxt}"); await refresh("prefs"); return

        if data == "st:lang":
            await c.answer("Language coming soon 🌐", show_alert=True); await refresh("prefs"); return

    except Exception as e:
        err = str(e)
        # Silent errors: message already same, query too old, message deleted
        if any(k in err for k in ("MESSAGE_NOT_MODIFIED", "MessageNotModified",
                                   "message was not modified", "query is too old",
                                   "MESSAGE_ID_INVALID", "MessageIdInvalid",
                                   "message to edit not found")):
            try: await c.answer()
            except Exception: pass
            return
        logger.exception(f"settings_cb err: {e}")
        try: await c.answer(f"Error: {err[:60]}", show_alert=True)
        except Exception: pass


# ---------------- In-memory state for multi-step input ----------------
_AWAIT_THUMB = {}
_AWAIT_STATE = {}


@Client.on_message(filters.private & filters.photo, group=10)
async def catch_thumb(client: Client, m: Message):
    uid = m.from_user.id if m.from_user else 0
    if uid not in _AWAIT_THUMB:
        return
    _AWAIT_THUMB.pop(uid, None)
    try:
        fid = m.photo.file_id
        await bimbo.db.set_thumb(uid, fid)
        await m.reply_text("✅ Thumbnail set! Future uploads pe yahi cover lagega.",
                           reply_markup=InlineKeyboardMarkup([
                               [InlineKeyboardButton("⬅️ Back to Settings", callback_data="st:thumb")]
                           ]))
        try: await m.delete()
        except Exception: pass
    except Exception as e:
        await m.reply_text(f"❌ Error: {e}")


@Client.on_message(_non_cmd_text(), group=11)
async def catch_text_input(client: Client, m: Message):
    uid = m.from_user.id if m.from_user else 0
    if uid not in _AWAIT_STATE:
        return
    state = _AWAIT_STATE.pop(uid)
    text = (m.text or "").strip()
    if not text:
        await m.reply_text("❌ Empty input."); return
    try:
        if state["state"] == "caption":
            await _ss(uid, "caption_template", text[:600])
            await m.reply_text("✅ Caption saved!", reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Back to Caption", callback_data="st:caption")]]))
        elif state["state"] == "rename_tpl":
            await _ss(uid, "rename_template", text[:200])
            await _ss(uid, "auto_rename", True)
            await m.reply_text("✅ Rename template saved! Auto Rename ON.", reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Back to Caption", callback_data="st:caption")]]))
        elif state["state"] == "watermark":
            await _ss(uid, "watermark_text", text[:30])
            await m.reply_text("✅ Watermark saved!", reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Back to Preferences", callback_data="st:prefs")]]))
    except Exception as e:
        await m.reply_text(f"❌ Error: {e}")
    try: await m.delete()
    except Exception: pass


@Client.on_message(_cmd("cancel"), group=2)
async def cancel_state(client: Client, m: Message):
    uid = m.from_user.id if m.from_user else 0
    popped = False
    if uid in _AWAIT_THUMB: _AWAIT_THUMB.pop(uid); popped = True
    if uid in _AWAIT_STATE: _AWAIT_STATE.pop(uid); popped = True
    if popped:
        await m.reply_text("❌ Cancelled.", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⚙️ Back to Settings", callback_data="settings")]
        ]))


# ---------------- /settings command ----------------
@Client.on_message(_cmd("settings", "setting", "config", "prefs"))
async def cmd_settings(client: Client, m: Message):
    uid = m.from_user.id
    s = await _all_settings(uid)
    txt = await _main_menu_text(s, m.from_user)
    await m.reply_text(txt, reply_markup=_main_menu_kb(s), disable_web_page_preview=True)


logger.info("✅ pro_settings plugin loaded (custom command filter — version-safe)")
