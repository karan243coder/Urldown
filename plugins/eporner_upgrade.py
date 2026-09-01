# -*- coding: utf-8 -*-
# BIMBO v4.0 — Eporner ULTIMATE Plugin
# Supports:
#   • Single videos
#   • Pornstars / models / tags / search listing & pagination
# Commands:
#   /ep <url> or /eporner <url>
#   /eps <query>
#   /epp <pornstar_url>

import os
import re
import json
import math
import time
import asyncio
import logging
import html as html_lib
import functools
import gc
from urllib.parse import urlparse, urljoin, quote

import aiohttp
from bs4 import BeautifulSoup
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

from config import Config
from utils import (
    safe_filename, user_download_dir, cleanup_dir, humanbytes, run_cmd,
    is_admin, is_premium, rate_limit_check, get_url,
    safe_reply_text, safe_edit_text,
)
from plugins.eporner_engine import (
    is_eporner, UA, QLABEL, extract_video as ep_extract, extract_listing as ep_listing,
    _parse_duration_sec, _clean_eporner_page_url,
)
from plugins.media_pipeline import set_bulk_backlog, clear_bulk_backlog

logger = logging.getLogger(__name__)


async def _auto_delete_message(message, delay=15):
    try:
        await asyncio.sleep(delay)
        await message.delete()
    except Exception:
        pass

# Global store for eporner listings (token -> listing data)
_EP_STORE = {}

# Global job queue for "Download Entire Profile" feature
_EP_JOBS = {}
_JOB_COUNTER = 0

async def create_job(user_id, chat_id, title, url, items):
    """Create a new download job for entire profile."""
    global _JOB_COUNTER
    _JOB_COUNTER += 1
    job_id = f"ep_job_{_JOB_COUNTER}"
    _EP_JOBS[job_id] = {
        "id": job_id,
        "user_id": user_id,
        "owner_id": user_id,
        "chat_id": chat_id,
        "title": title,
        "url": url,
        "items": [{"index": i, "url": item.get("url", ""), "title": item.get("title", "Video"), "status": "pending"} for i, item in enumerate(items)],
        "status": "running",
        "created": time.time(),
    }
    return job_id

async def get_job(job_id):
    """Get job by ID."""
    return _EP_JOBS.get(job_id)

async def claim_next_item(job_id):
    """Get the next pending item from the job."""
    job = _EP_JOBS.get(job_id)
    if not job:
        return None
    for item in job["items"]:
        if item["status"] == "pending":
            item["status"] = "processing"
            return item
    return None

async def update_job(job_id, **kwargs):
    """Update job fields."""
    job = _EP_JOBS.get(job_id)
    if job:
        job.update(kwargs)

async def finish_item(job_id, index, status, error=None):
    """Mark an item as completed or failed."""
    job = _EP_JOBS.get(job_id)
    if not job:
        return
    for item in job["items"]:
        if item["index"] == index:
            item["status"] = status
            if error:
                item["error"] = error
            break


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

async def _ep_vip_allowed(m: Message) -> bool:
    uid = m.from_user.id if m.from_user else 0
    if is_admin(uid):
        return True
    try:
        if await is_premium(uid):
            return True
    except Exception:
        pass
    return False

_EP_VIP_DENY_TEXT = (
    "🔒 **Eporner Advanced Features Premium Only!** 💎\n\n"
    "Ye features (🔍 Search, 👤 Pornstar/Tag profiles, Paginated listings) sirf **Premium users** ya **Admin** ke liye hain.\n\n"
    "✅ Normal users ke liye: bas kisi Eporner **single video ka direct link** bhejo — main auto quality select karke download kar dunga!"
)

RE_EP_VIDEO = re.compile(r"/(?:hd-porn|embed)/|/video-", re.I)
RE_EP_PROFILE = re.compile(r"/(?:pornstar|tag|search|category|channels)/", re.I)


def _ep_type(url: str) -> str:
    url = url or ""
    if RE_EP_VIDEO.search(url):
        return "video"
    if RE_EP_PROFILE.search(url):
        return "listing"
    return "unknown"


async def _ep_collect_all_pages(start_url, max_videos=None):
    found, seen, current = [], set(), start_url
    visited = set()
    loop = asyncio.get_event_loop()
    for _ in range(500):
        if not current or current in visited:
            break
        visited.add(current)
        if max_videos is not None and len(found) >= max_videos:
            break
        items, nxt, err = await loop.run_in_executor(None, ep_listing, current)
        if err or not items:
            break
        for item in items:
            u = item.get("url")
            if u and u not in seen:
                seen.add(u); found.append(item)
                if max_videos is not None and len(found) >= max_videos:
                    break
        if not nxt or nxt == current:
            break
        current = nxt
        await asyncio.sleep(1)
    return found


async def _ep_full_queue_worker(client, job_id, user, status_msg):
    completed = failed = 0
    try:
        while True:
            job = await get_job(job_id)
            if not job or job.get("status") in ("cancelled", "paused"):
                return
            item = await claim_next_item(job_id)
            if not item:
                await update_job(job_id, status="completed")
                clear_bulk_backlog(job_id)
                try:
                    done_msg = await client.send_message(
                        status_msg.chat.id,
                        f"✅ Full profile queue complete\n\nDone: {completed} | Failed: {failed}",
                    )
                    asyncio.create_task(_auto_delete_message(done_msg, 15))
                except Exception:
                    pass
                return
            idx = item.get("index", 0) + 1
            title = item.get("title", "Video")
            current_job = await get_job(job_id)
            total = len((current_job or {}).get("items", []))
            pending = sum(
                1 for queued_item in (current_job or {}).get("items", [])
                if queued_item.get("status") == "pending"
            )
            set_bulk_backlog(
                job_id, user.id, pending, site="eporner",
                label=(current_job or {}).get("title", "Eporner Profile"),
            )

            url = item.get("url", "")
            best_url = url
            best_h = 1080
            try:
                loop = asyncio.get_event_loop()
                res = await loop.run_in_executor(None, ep_extract, url)
                if res and res.get("qualities"):
                    qlts = res["qualities"]
                    best_q = max(qlts, key=lambda q: q.get("height", 0))
                    best_h = best_q.get("height", 1080)
                    best_url = best_q.get("url", url)
            except Exception as e:
                logger.warning(f"ep full queue prefetch fail: {e}")

            try:
                from plugins.xhamster_upgrade import _xh_download_and_upload
                ok = await asyncio.wait_for(
                    _xh_download_and_upload(
                        client, status_msg, user, url, best_url, title, best_h, "video",
                        {"User-Agent": UA, "Referer": url, "Origin": "https://www.eporner.com"},
                        priority=0,
                    ),
                    timeout=max(300, int(Config.BIMBO_PROCESS_MAX_TIMEOUT))
                )
                if not ok:
                    raise RuntimeError("media pipeline failed")
                await finish_item(job_id, item["index"], "completed")
                completed += 1
            except asyncio.TimeoutError:
                await finish_item(job_id, item["index"], "failed", "timeout")
                failed += 1
            except Exception as exc:
                await finish_item(job_id, item["index"], "failed", str(exc))
                failed += 1
            gc.collect()
            await asyncio.sleep(5)
    except Exception as exc:
        clear_bulk_backlog(job_id)
        await update_job(job_id, status="paused", last_error=str(exc)[:500])


def _ep_listing_kbd(token, items, has_next, current_page=1, sort_mode="long"):
    rows = []
    rows.append([
        InlineKeyboardButton("⬇️ Longest first" + (" ✅" if sort_mode == "long" else ""), callback_data=f"ep_sort::{token}::long"),
        InlineKeyboardButton("⬆️ Shortest first" + (" ✅" if sort_mode == "short" else ""), callback_data=f"ep_sort::{token}::short"),
    ])
    page_items = items[:10]
    for i, v in enumerate(page_items, 1):
        title = re.sub(r"\s+", " ", v["title"])[:24]
        dur = f" ⏱{v['duration']}" if v.get("duration") else ""
        rows.append([InlineKeyboardButton(f"▶️ {i}. {title}{dur}", callback_data=f"ep_q::{token}::{i-1}")])
    rows.append([InlineKeyboardButton(f"⬇️ Download Page ({len(page_items)} videos)", callback_data=f"ep_pageall::{token}")])
    rows.append([InlineKeyboardButton("📥 Download Entire Profile/Channel — MAX QUALITY", callback_data=f"ep_all::{token}")])
    nav = []
    if current_page > 1:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"ep_prevpg::{token}"))
    nav.append(InlineKeyboardButton("❌ Close", callback_data="close"))
    if has_next:
        nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"ep_pg::{token}"))
    rows.append(nav)
    return InlineKeyboardMarkup(rows)


def _ep_quality_kbd(token, idx, qlts):
    rows = []
    if not qlts:
        qlts = [{"height": 720, "label": "720p (HD)"}]
    row = []
    for q in sorted(qlts, key=lambda x: -x["height"]):
        h = q["height"]
        label = q.get("label", f"{h}p")
        cb_dl = f"ep_vid::{token}::{idx}::{h}::video"
        cb_fi = f"ep_vid::{token}::{idx}::{h}::file"
        row.append(InlineKeyboardButton(f"🎬 {label}", callback_data=cb_dl))
        if len(row) == 2:
            rows.append(row); row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("🎵 MP3 (audio)", callback_data=f"ep_vid::{token}::{idx}::0::audio")])
    rows.append([InlineKeyboardButton("⬅️ Back to list", callback_data=f"ep_back::{token}")])
    return InlineKeyboardMarkup(rows)


async def _send_ep_listing(m: Message, url: str, title: str = "🔞 Eporner"):
    msg = await safe_reply_text(m, f"{title}\n🔍 Loading...")
    try:
        loop = asyncio.get_event_loop()
        logger.info("ep listing: calling extract_listing for URL: %s", url)
        items, next_page, err = await loop.run_in_executor(None, ep_listing, url)
        logger.info("ep listing: result items=%d, next=%s, err=%s", len(items), bool(next_page), err)
        if err or not items:
            return await safe_edit_text(msg, f"❌ No videos found or error: {err or 'unknown'}\n\nURL: <code>{url[:100]}</code>")
        items = sorted(items, key=lambda v: v.get("duration_sec", 999999), reverse=True)
        token = _store_ep_listing(items, next_page, title=title, current_url=url)
        text = f"{title}\n\n📋 {len(items)} videos detected\n⏱ Default: longest first\n\n"
        for i, v in enumerate(items[:10], 1):
            t = re.sub(r"\s+", " ", v["title"])[:35]
            dur = f" ⏱{v['duration']}" if v.get("duration") else ""
            text += f"\n{i}. {t}{dur}"
        await safe_edit_text(msg, text, reply_markup=_ep_listing_kbd(token, items, bool(next_page), current_page=1, sort_mode="long"))
    except Exception as e:
        logger.exception("ep listing")
        await safe_edit_text(msg, f"❌ Error: <code>{e}</code>")


def _store_ep_listing(items, next_page, title="🔞 Eporner", current_url=""):
    import secrets
    for _ in range(5):
        token = secrets.token_hex(5)
        if token not in _EP_STORE:
            break
    _EP_STORE[token] = {
        "items": items, "next": next_page, "ts": time.time(),
        "title": title, "page": 1, "current_url": current_url, "sort": "long",
    }
    return token


@Client.on_message(filters.private & _cmd("eps", "epsearch"))
async def cmd_ep_search(client: Client, m: Message):
    if not await _ep_vip_allowed(m):
        return await safe_reply_text(m, _EP_VIP_DENY_TEXT, disable_web_page_preview=True)
    parts = (m.text or "").split(None, 1)
    if len(parts) < 2:
        return await safe_reply_text(m, "Usage: <code>/eps search query</code>")
    q = parts[1].strip()
    url = f"https://www.eporner.com/search/{quote(q)}/"
    await _send_ep_listing(m, url, title=f"🔞 Eporner Search: {q}")


@Client.on_message(filters.private & _cmd("epp", "eppornstar"))
async def cmd_ep_pornstar(client: Client, m: Message):
    if not await _ep_vip_allowed(m):
        return await safe_reply_text(m, _EP_VIP_DENY_TEXT, disable_web_page_preview=True)
    parts = (m.text or "").split(None, 1)
    url = parts[1] if len(parts) > 1 else ""
    if m.reply_to_message and m.reply_to_message.text:
        url = m.reply_to_message.text
    url = get_url(url)
    if not url or not is_eporner(url):
        return await safe_reply_text(m, "Usage: <code>/epp https://www.eporner.com/pornstar/angela-white/</code>")
    await _send_ep_listing(m, url, title="🔞 Eporner Pornstar / Profile")


@Client.on_message(filters.private & _cmd("ep", "eporner"))
async def cmd_ep_auto(client: Client, m: Message):
    parts = (m.text or "").split(None, 1)
    url = parts[1] if len(parts) > 1 else ""
    if m.reply_to_message and m.reply_to_message.text:
        url = m.reply_to_message.text
    url = get_url(url)
    is_vip = await _ep_vip_allowed(m)

    if not url or not is_eporner(url):
        base = (
            "🔞 **Eporner**\n\n"
            "✅ <b>Free:</b> Send any Eporner single video link for automatic quality buttons & download.\n"
        )
        if is_vip:
            base += "\n💎 <b>Commands:</b> /eps <query>, /epp <pornstar_url>\n"
        return await safe_reply_text(m, base, disable_web_page_preview=True)

    t = _ep_type(url)
    if t == "video":
        await safe_reply_text(m, 
            f"🔞 <b>Eporner Video Detected</b>\n"
            f"<code>{url[:150]}</code>\n\n"
            f"🔄 Quality buttons load ho rahe hain..."
        )
        return

    if not is_vip:
        return await safe_reply_text(m, _EP_VIP_DENY_TEXT, disable_web_page_preview=True)

    await _send_ep_listing(m, url, title="🔞 Eporner Listing")


@Client.on_callback_query(filters.regex(r"^ep_(q|pg|vid|back|sort|pageall|all|prevpg)::"))
async def ep_callbacks(client: Client, c: CallbackQuery):
    data = c.data or ""
    parts = data.split("::")
    action = parts[0]
    try:
        await c.answer()
    except Exception:
        pass

    try:
        if action == "ep_all":
            token = parts[1]
            entry = _EP_STORE.get(token)
            if not entry:
                return await c.answer("Session expired", show_alert=True)
            status_msg = await c.message.reply_text("🔎 Collecting all Eporner profile/channel pages...")
            try:
                all_items = await _ep_collect_all_pages(entry.get("current_url") or entry.get("next"), None)
                if not all_items:
                    return await safe_edit_text(status_msg, "❌ No videos found for queue.")
                job_id = await create_job(c.from_user.id, c.message.chat.id, entry.get("title", "Eporner Channel"), entry.get("current_url", ""), all_items)
                set_bulk_backlog(
                    job_id, c.from_user.id, len(all_items), site="eporner",
                    label=entry.get("title", "Eporner Channel"),
                )
                await safe_edit_text(
                    status_msg,
                    f"✅ Added to unified queue\n\n📋 Videos: {len(all_items)}\n"
                    f"⬇️ Global download slots: 2\n⬆️ Global upload slots: 2\n"
                    f"🧭 Fair FIFO enabled",
                )
                asyncio.create_task(_ep_full_queue_worker(client, job_id, c.from_user, status_msg))
            except Exception as exc:
                logger.exception("ep full queue create failed")
                await safe_edit_text(status_msg, f"❌ Queue create failed: <code>{str(exc)[:500]}</code>")
            return

        if action == "ep_pageall":
            token = parts[1]
            entry = _EP_STORE.get(token)
            if not entry:
                return await c.answer("Session expired", show_alert=True)
            items = entry.get("items", [])[:10]
            if not items:
                return await c.answer("No videos", show_alert=True)

            status_msg = await c.message.reply_text(
                f"⬇️ **Preparing Eporner Download All**\n\n"
                f"🔍 Fetching best quality for {len(items)} videos..."
            )
            download_jobs = []
            try:
                for i, item in enumerate(items, 1):
                    url = item.get("url", "")
                    best_url = url
                    best_h = 1080
                    try:
                        loop = asyncio.get_event_loop()
                        res = await loop.run_in_executor(None, ep_extract, url)
                        if res and res.get("qualities"):
                            qlts = res["qualities"]
                            best_q = max(qlts, key=lambda q: q.get("height", 0))
                            best_h = best_q.get("height", 1080)
                            best_url = best_q.get("url", url)
                    except Exception:
                        pass
                    download_jobs.append({
                        "idx": i, "item": item, "best_h": best_h, "best_m3u8": best_url, "final_url": url,
                    })
                    await asyncio.sleep(0.3)
            except Exception as e:
                logger.exception(f"ep all prefetch err: {e}")

            from plugins.xhamster_upgrade import _xh_download_and_upload

            async def _run_one(job):
                item = job["item"]
                title = item.get("title", "Video")
                url = job["final_url"]
                best_h = job["best_h"]
                best_m3u8 = job["best_m3u8"]
                await _xh_download_and_upload(
                    client, status_msg, c.from_user, url, best_m3u8, title, best_h, "video",
                    {"User-Agent": UA, "Referer": url, "Origin": "https://www.eporner.com"},
                    priority=0,
                )

            for job in download_jobs:
                asyncio.create_task(_run_one(job))
                await asyncio.sleep(0.2)

            try:
                await c.answer(
                    f"{len(download_jobs)} videos unified queue me add hue",
                    show_alert=True,
                )
            except Exception:
                pass
            return
        if action == "ep_sort":
            token = parts[1]
            mode = parts[2] if len(parts) > 2 else "long"
            entry = _EP_STORE.get(token)
            if not entry:
                return
            entry["sort"] = mode
            items = list(entry.get("items", []))
            items.sort(key=lambda v: v.get("duration_sec", 999999), reverse=(mode == "long"))
            entry["items"] = items
            page = entry.get("page", 1)
            title = entry.get("title", "🔞 Eporner")
            text = f"{title}\n\n📋 Page {page}:\n"
            for i, v in enumerate(items[:10], 1):
                t = re.sub(r"\s+", " ", v.get("title", "Video"))[:35]
                dur = f" ⏱{v.get('duration')}" if v.get("duration") else ""
                text += f"\n{i}. {t}{dur}"
            await c.message.edit_text(text, reply_markup=_ep_listing_kbd(token, items, bool(entry.get("next")), page, mode))
            return

        if action == "ep_pg":
            token = parts[1]
            entry = _EP_STORE.get(token)
            if not entry or not entry.get("next"):
                return
            next_url = entry["next"]
            loop = asyncio.get_event_loop()
            items, np, err = await loop.run_in_executor(None, ep_listing, next_url)
            if not items:
                return
            items = sorted(items, key=lambda v: v.get("duration_sec", 999999), reverse=(entry.get("sort", "long") == "long"))
            page = entry.get("page", 1) + 1
            entry["items"] = items
            entry["next"] = np
            entry["page"] = page
            entry["current_url"] = next_url
            title = entry.get("title", "🔞 Eporner")
            text = f"{title}\n\n📋 Page {page}:\n"
            for i, v in enumerate(items[:10], 1):
                t = re.sub(r"\s+", " ", v["title"])[:35]
                dur = f" ⏱{v['duration']}" if v.get("duration") else ""
                text += f"\n{i}. {t}{dur}"
            await c.message.edit_text(text, reply_markup=_ep_listing_kbd(token, items, bool(np), page, entry.get("sort", "long")))

        elif action == "ep_q":
            token = parts[1]
            idx = int(parts[2])
            entry = _EP_STORE.get(token)
            if not entry:
                return
            items = entry.get("items", [])
            if idx < 0 or idx >= len(items):
                return
            item = items[idx]
            url = item["url"]
            qlts = []
            try:
                loop = asyncio.get_event_loop()
                res = await loop.run_in_executor(None, ep_extract, url)
                if res and res.get("qualities"):
                    qlts = res["qualities"]
                    item["_qualities"] = qlts
            except Exception as e:
                logger.warning(f"ep_q fetch qualities fail: {e}")
            if not qlts:
                qlts = [
                    {"height": 2160, "label": "4K UHD"},
                    {"height": 1080, "label": "1080p (FHD)"},
                    {"height": 720,  "label": "720p (HD)"},
                    {"height": 480,  "label": "480p (SD)"},
                ]
                item["_qualities"] = qlts
            title = item.get("title", "Video")
            dur = f" ⏱{item.get('duration')}" if item.get("duration") else ""
            await c.message.edit_text(f"🎬 **{title[:80]}**{dur}\n\nQuality select karo:", reply_markup=_ep_quality_kbd(token, idx, qlts))

        elif action == "ep_back":
            token = parts[1]
            entry = _EP_STORE.get(token)
            if not entry:
                return
            items = entry.get("items", [])
            page = entry.get("page", 1)
            title = entry.get("title", "🔞 Eporner")
            text = f"{title}\n\n📋 Videos:\n"
            for i, v in enumerate(items[:10], 1):
                t = re.sub(r"\s+", " ", v["title"])[:35]
                dur = f" ⏱{v['duration']}" if v.get("duration") else ""
                text += f"\n{i}. {t}{dur}"
            await c.message.edit_text(text, reply_markup=_ep_listing_kbd(token, items, bool(entry.get("next")), page, entry.get("sort", "long")))

        elif action == "ep_vid":
            token = parts[1]; idx = int(parts[2]); height = int(parts[3]); mode = parts[4]
            entry = _EP_STORE.get(token)
            if not entry:
                return
            items = entry.get("items", [])
            if idx < 0 or idx >= len(items):
                return
            item = items[idx]
            qlts = item.get("_qualities") or []
            url = item["url"]
            if not qlts:
                loop = asyncio.get_event_loop()
                res = await loop.run_in_executor(None, ep_extract, url)
                if res and res.get("qualities"):
                    qlts = res["qualities"]
            chosen_url = next((q.get("url", "") for q in qlts if q.get("height") == height), "")
            if not chosen_url and qlts:
                chosen_url = qlts[0]["url"]
            if not chosen_url:
                chosen_url = url

            title = item.get("title", "Video")
            h_label = next((q.get("label", f"{height}p") for q in qlts if q.get("height") == height), f"{height}p")

            await c.message.edit_text(
                f"🎬 **{title[:80]}**\n\n"
                f"📥 Quality: **{h_label}**\n"
                f"📦 Type: **{mode.upper()}**\n\n"
                f"📥 Downloading..."
            )
            from plugins.xhamster_upgrade import _xh_download_and_upload
            asyncio.create_task(_xh_download_and_upload(
                client, c.message, c.from_user, url, chosen_url, title, height, mode,
                {"User-Agent": UA, "Referer": url, "Origin": "https://www.eporner.com"}
            ))
    except Exception as e:
        logger.exception(f"ep cb err: {e}")
