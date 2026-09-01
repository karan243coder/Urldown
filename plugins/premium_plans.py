# BIMBO v4.0 — Premium / Plans / Referral / Coupons
import os
import json
import time
import random
import string
import logging
from datetime import datetime

from pyrogram import Client, filters
from pyrogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton,
    CallbackQuery
)

from config import Config
from database.users_chats_db import db
from utils import is_admin

logger = logging.getLogger(__name__)

DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)
REFERRAL_FILE = os.path.join(DATA_DIR, "referrals.json")
COUPON_FILE = os.path.join(DATA_DIR, "coupons.json")


def _load(path):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}


def _save(path, data):
    try:
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.error(f"save {path}: {e}")


PLANS = {
    "1w":  {"days": 7,  "price": "₹49",  "name": "Weekly"},
    "1m":  {"days": 30, "price": "₹149", "name": "Monthly"},
    "3m":  {"days": 90, "price": "₹399", "name": "3 Months"},
}

REFERRAL_NEEDED = 3  # 3 referrals = 1 day free premium



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


@Client.on_message(filters.private & _cmd('plan', 'plans', 'premium'))
async def plan_cmd(client: Client, m: Message):
    uid = m.from_user.id
    p = await db.get_premium(uid)
    ref = _load(REFERRAL_FILE)
    my_refs = len(ref.get(str(uid), []))
    if p:
        exp = datetime.utcfromtimestamp(p["expires"]).strftime("%d %b %Y")
        status = f"✅ **Premium Active**\nExpires: `{exp}`\nPlan: `{p.get('plan','premium')}`\n"
    else:
        status = "❌ **Free User**\n"

    txt = (
        f"💎 **BIMBO Premium Plans**\n\n"
        f"{status}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📅 **Weekly** — {PLANS['1w']['price']} / 7 days\n"
        f"📅 **Monthly** — {PLANS['1m']['price']} / 30 days\n"
        f"📅 **3 Months** — {PLANS['3m']['price']} / 90 days\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"🎁 **Referral Rewards:**\n"
        f"Apna referral link 3 friends ko bhejo — unke join karne par "
        f"**1 day FREE Premium** milega!\n\n"
        f"🔗 Your referral link:\n"
        f"<code>https://t.me/{Config.BIMBO_BOT_USERNAME}?start=ref{uid}</code>\n\n"
        f"👥 Referrals: `{my_refs}/{REFERRAL_NEEDED}`\n\n"
        f"🎟️ Coupon code redeem: <code>/redeem CODE</code>\n"
        f"Buy: Contact @Bimbo69"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("👨‍💻 Buy / Contact Owner", url="https://t.me/Bimbo69")],
        [InlineKeyboardButton("🔗 Share Referral", switch_inline_query=f"Join BIMBO Bot & get fast downloads! https://t.me/{Config.BIMBO_BOT_USERNAME}?start=ref{uid}")],
    ])
    await m.reply_text(txt, reply_markup=kb)


@Client.on_message(filters.private & _cmd('myplan', 'quota'))
async def myplan_cmd(client: Client, m: Message):
    uid = m.from_user.id
    p = await db.get_premium(uid)
    if p:
        exp = datetime.utcfromtimestamp(p["expires"]).strftime("%d %b %Y %H:%M UTC")
        await m.reply_text(f"💠 **Your Plan**\n\n💎 Premium\nExpires: `{exp}`\nUnlimited speed, 4 concurrent tasks, all features.")
    else:
        await m.reply_text(
            "🆓 **Your Plan: Free**\n\n"
            "• 2 concurrent downloads\n"
            "• 2 GB max file size\n"
            "• 15s rate limit between requests\n"
            "• Watermark/screenshots enabled\n\n"
            "Upgrade to Premium: /plan"
        )


# ---------- Referral tracking via /start ref<id> ----------
async def track_referral_if_any(client: Client, payload: str, new_user_id: int):
    """Call from start handler when payload starts with 'ref'."""
    try:
        if not payload.startswith("ref"):
            return
        ref_id = int(payload[3:])
        if ref_id == new_user_id:
            return
        data = _load(REFERRAL_FILE)
        refs = data.setdefault(str(ref_id), [])
        if new_user_id not in refs:
            refs.append(new_user_id)
            _save(REFERRAL_FILE, data)
            # notify referrer
            try:
                await client.send_message(ref_id, f"🎉 New referral joined! ({len(refs)}/{REFERRAL_NEEDED})")
            except Exception:
                pass
            if len(refs) >= REFERRAL_NEEDED:
                # grant 1 day premium (only once per threshold)
                granted_key = f"_granted_{len(refs)}"
                if granted_key not in refs:
                    refs.append(granted_key)
                    _save(REFERRAL_FILE, data)
                    exp = time.time() + 86400
                    await db.set_premium(ref_id, exp, plan="referral")
                    try:
                        await client.send_message(
                            ref_id,
                            "🎁 Congrats! 3 referrals complete. **+1 day FREE Premium** added!"
                        )
                    except Exception:
                        pass
    except Exception as e:
        logger.error(f"referral track: {e}")


# ---------- Coupon system ----------
@Client.on_message(filters.private & _cmd('redeem', 'coupon'))
async def redeem_cmd(client: Client, m: Message):
    parts = (m.text or "").split()
    if len(parts) < 2:
        return await m.reply_text("Usage: <code>/redeem COUPON_CODE</code>")
    code = parts[1].strip().upper()
    coupons = _load(COUPON_FILE)
    item = coupons.get(code)
    if not item:
        return await m.reply_text("❌ Invalid coupon code.")
    if item.get("used_by"):
        return await m.reply_text("❌ Coupon already used.")
    if item.get("expires", 0) and item["expires"] < time.time():
        return await m.reply_text("❌ Coupon expired.")
    days = int(item.get("days", 1))
    uid = m.from_user.id
    exp = time.time() + days * 86400
    await db.set_premium(uid, exp, plan="coupon")
    item["used_by"] = uid
    item["used_at"] = time.time()
    coupons[code] = item
    _save(COUPON_FILE, coupons)
    await m.reply_text(f"✅ Coupon redeemed! **{days} days Premium** added to your account.")


@Client.on_message(filters.private & _cmd('createcoupon', 'gencode'))
async def create_coupon(client: Client, m: Message):
    """Admin only: /createcoupon <days> <count>"""
    if not is_admin(m.from_user.id):
        return
    parts = (m.text or "").split()
    days = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 7
    count = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 1
    coupons = _load(COUPON_FILE)
    new_codes = []
    for _ in range(count):
        code = "BIMBO-" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        coupons[code] = {"days": days, "used_by": None, "created": time.time()}
        new_codes.append(code)
    _save(COUPON_FILE, coupons)
    await m.reply_text(f"✅ Created {count} coupon(s) ({days} days):\n\n" + "\n".join(f"<code>{c}</code>" for c in new_codes))
