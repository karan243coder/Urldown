# BIMBO v4.0 — Media Tools Plugin
# Commands:
#   /ss (or /screenshot) [n]  - reply to video → n screenshots (default 5)
#   /sample                   - 60-second sample video
#   /trim START END           - trim video (seconds or HH:MM:SS)
#   /compress [low|med|high]  - compress replied video
#   /wm "text" [pos]          - add watermark to replied video/photo
#   /mp3                      - extract audio from replied video
#   /zip                      - zip replied files/media
#   /unzip                    - extract replied zip
#   /rename NAME              - rename file while re-uploading
import os
import re
import time
import asyncio
import logging
import shutil
import zipfile
from contextlib import asynccontextmanager
from functools import wraps
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

from pyrogram import Client, filters
from pyrogram.types import Message

from config import Config
from translation import Translation
from utils import (
    is_media, get_file_id, run_cmd, humanbytes, time_formatter,
    cleanup_dir, user_download_dir, safe_filename, is_admin,
    safe_reply_text, safe_edit_text, safe_send_message,
)
from plugins.video_utils import (
    video_converter, screenshot_generator, get_video_duration,
    generate_multiple_screenshots, extract_audio,
)
from helper_funcs.display_progress import (
    claim_user_progress_message, finalize_user_progress, get_task,
    get_user_message, register_task, remove_task, set_task_stage,
    update_task, update_user_progress,
)
from plugins.media_pipeline import (
    PRIORITY_INTERACTIVE, begin_interactive_job, end_interactive_job, stage_slot,
)

logger = logging.getLogger(__name__)

_COMMAND_CONTEXT = {}


def _context_key(message):
    return (int(message.chat.id), int(message.id))


class _DashboardProxy:
    """Message-like object that keeps handler edits inside BIMBO LIVE."""

    def __init__(self, client, message, dashboard, task_id, label):
        self.client = client
        self.command = message
        self.dashboard = dashboard
        self.task_id = task_id
        self.label = label
        self.id = dashboard.id
        self.message_id = dashboard.id
        self.chat = dashboard.chat

    async def edit_text(self, text, **kwargs):
        lower = str(text or "").lower()
        if any(word in lower for word in ("upload", "sending")):
            status, engine = "waiting", "pyrogram"
        elif any(word in lower for word in ("ffmpeg", "generat", "trim", "compress", "extract", "watermark", "cutting")):
            status, engine = "processing", "ffmpeg"
        elif "download" in lower:
            status, engine = "waiting", "pyrogram"
        elif any(word in lower for word in ("failed", "error", "❌")):
            status, engine = "failed", "ffmpeg"
        else:
            status, engine = "processing", "ffmpeg"
        detail = re.sub(r"<[^>]+>", "", str(text or ""))
        detail = re.sub(r"\s+", " ", detail).strip()
        set_task_stage(self.task_id, status=status, engine=engine, detail=detail)
        await update_user_progress(self.client, self.command.from_user.id, force=True)
        if status == "failed":
            try:
                await self.client.send_message(
                    self.command.chat.id, str(text)[:3500],
                    reply_to_message_id=self.command.id,
                )
            except Exception:
                pass
        return self

    async def edit(self, text=None, **kwargs):
        return await self.edit_text(text, **kwargs)

    async def delete(self):
        # The decorator owns canonical dashboard lifecycle.
        return None


async def _command_proxy(message):
    ctx = _COMMAND_CONTEXT.get(_context_key(message))
    return ctx["proxy"] if ctx else None


def _interactive_media_task(label):
    def decorator(func):
        @wraps(func)
        async def wrapped(client, message, *args, **kwargs):
            uid = int(message.from_user.id)
            task_id = f"cmd_{func.__name__}_{uid}_{time.time_ns()}"
            await begin_interactive_job(task_id)
            current = get_user_message(uid)
            if current is None:
                candidate = await safe_reply_text(message, f"⚡ {label} queued with priority...")
                if candidate is None:
                    candidate = await client.send_message(
                        message.chat.id, f"⚡ {label} queued with priority..."
                    )
                dashboard = await claim_user_progress_message(uid, candidate, delete_duplicate=False)
            else:
                dashboard = current
            register_task(
                task_id, uid, label, 0,
                task_type="download", engine="pyrogram", source_url=func.__name__,
            )
            proxy = _DashboardProxy(client, message, dashboard, task_id, label)
            _COMMAND_CONTEXT[_context_key(message)] = {
                "task_id": task_id, "dashboard": dashboard, "proxy": proxy,
                "client": client, "uid": uid,
            }
            await update_user_progress(client, uid, force=True)
            try:
                return await func(client, message, *args, **kwargs)
            except Exception as exc:
                task = get_task(task_id)
                if task:
                    task["error"] = str(exc)[:250]
                update_task(
                    task_id, (task or {}).get("downloaded", 0),
                    (task or {}).get("total_size", 0), 0,
                    status="failed", engine=(task or {}).get("engine", "ffmpeg"),
                )
                await update_user_progress(client, uid, force=True)
                raise
            finally:
                _COMMAND_CONTEXT.pop(_context_key(message), None)
                remove_task(task_id)
                await end_interactive_job(task_id)
                await finalize_user_progress(client, uid, dashboard)
        return wrapped
    return decorator


@asynccontextmanager
async def _command_upload_slot(message):
    ctx = _COMMAND_CONTEXT.get(_context_key(message))
    if not ctx:
        yield
        return
    task_id, uid, client = ctx["task_id"], ctx["uid"], ctx["client"]
    set_task_stage(
        task_id, task_type="upload", status="waiting", engine="pyrogram",
        downloaded=0, total_size=0, reset_timer=True,
    )
    async with stage_slot(
        "upload", task_id, uid, site="command", client=client,
        priority=PRIORITY_INTERACTIVE,
    ):
        set_task_stage(task_id, task_type="upload", status="uploading", engine="pyrogram")
        await update_user_progress(client, uid, force=True)
        yield


async def _priority_send(message, sender, *args, **kwargs):
    """Send command output through one of the two global upload slots."""
    ctx = _COMMAND_CONTEXT.get(_context_key(message))
    async with _command_upload_slot(message):
        if ctx and getattr(sender, "__name__", "") != "send_media_group" and "progress" not in kwargs:
            task_id, uid, client = ctx["task_id"], ctx["uid"], ctx["client"]
            upload_start = time.time()

            async def progress(current, total):
                speed = int(current / max(time.time() - upload_start, 0.001))
                update_task(task_id, current, total, speed, "uploading", "pyrogram")
                await update_user_progress(client, uid)

            kwargs["progress"] = progress
        return await sender(*args, **kwargs)


# ---------- helpers ----------
def _to_seconds(s: str) -> int:
    s = s.strip()
    if re.fullmatch(r"\d+(\.\d+)?", s):
        return int(float(s))
    parts = s.split(":")
    try:
        parts = [int(p) for p in parts]
        if len(parts) == 3:
            return parts[0] * 3600 + parts[1] * 60 + parts[2]
        if len(parts) == 2:
            return parts[0] * 60 + parts[1]
        if len(parts) == 1:
            return parts[0]
    except Exception:
        pass
    raise ValueError(f"Invalid time: {s}")


async def _download_replied(client: Client, msg: Message, uid: int, out_dir: str) -> str:
    """Priority-download replied Telegram media into the unified dashboard."""
    os.makedirs(out_dir, exist_ok=True)
    ctx = _COMMAND_CONTEXT.get(_context_key(msg))
    status = ctx["proxy"] if ctx else await safe_reply_text(msg, "📥 Downloading media...")
    task_id = ctx["task_id"] if ctx else f"cmd_dl_{uid}_{time.time_ns()}"

    async def progress(current, total):
        speed = 0
        task = get_task(task_id)
        if task:
            elapsed = max(time.time() - task.get('start_time', time.time()), 0.001)
            speed = int(current / elapsed)
        update_task(task_id, current, total, speed, "downloading", "pyrogram")
        await update_user_progress(client, uid)

    try:
        async with stage_slot(
            "download", task_id, uid, site="command", client=client,
            priority=PRIORITY_INTERACTIVE,
        ):
            set_task_stage(
                task_id, task_type="download", status="downloading",
                engine="pyrogram", reset_timer=True,
                detail="Downloading replied Telegram media",
            )
            await update_user_progress(client, uid, force=True)
            common = {"progress": progress}
            if msg.reply_to_message.video:
                path = await msg.reply_to_message.download(
                    file_name=os.path.join(out_dir, msg.reply_to_message.video.file_name or "video.mp4"),
                    **common,
                )
            elif msg.reply_to_message.document:
                fn = msg.reply_to_message.document.file_name or f"doc_{int(time.time())}"
                path = await msg.reply_to_message.download(
                    file_name=os.path.join(out_dir, safe_filename(fn)), **common,
                )
            elif msg.reply_to_message.audio:
                fn = msg.reply_to_message.audio.file_name or "audio.mp3"
                path = await msg.reply_to_message.download(
                    file_name=os.path.join(out_dir, safe_filename(fn)), **common,
                )
            elif msg.reply_to_message.photo:
                path = await msg.reply_to_message.download(
                    file_name=os.path.join(out_dir, "photo.jpg"), **common,
                )
            elif msg.reply_to_message.animation:
                path = await msg.reply_to_message.download(
                    file_name=os.path.join(out_dir, "anim.gif"), **common,
                )
            else:
                await safe_edit_text(status, Translation.NO_VIDEO_REPLY)
                return None, status
    except Exception as exc:
        await safe_edit_text(status, f"❌ Download failed: <code>{exc}</code>")
        return None, status

    set_task_stage(
        task_id, task_type="download", status="processing", engine="ffmpeg",
        downloaded=0, total_size=0, reset_timer=True,
    )
    await update_user_progress(client, uid, force=True)
    return path, None


# ===================== SCREENSHOTS =====================

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


@Client.on_message(filters.private & _cmd('ss', 'screenshot', 'screens'))
@_interactive_media_task("Screenshot generator")
async def cmd_screenshot(client: Client, message: Message):
    if not message.reply_to_message or not is_media(message.reply_to_message):
        return await safe_reply_text(message, Translation.NO_VIDEO_REPLY)
    uid = message.from_user.id
    parts = (message.text or "").split()
    count = 5
    if len(parts) > 1:
        try:
            count = max(1, min(int(parts[1]), 10))
        except Exception:
            count = 5

    work = user_download_dir(uid) + f"/ss_{int(time.time())}"
    os.makedirs(work, exist_ok=True)
    msg = await _command_proxy(message)
    try:
        path, err = await _download_replied(client, message, uid, work)
        if not path:
            return
        await safe_edit_text(msg, f"🎞️ Generating {count} screenshot(s)...")
        shots = await generate_multiple_screenshots(path, count=count, output_dir=work)
        if not shots:
            return await safe_edit_text(msg, "❌ Screenshots generate nahi ho paye (shayad video nahi hai).")

        await safe_edit_text(msg, f"📤 Uploading {len(shots)} screenshot(s)...")
        media = []
        from pyrogram.types import InputMediaPhoto
        for s in shots:
            media.append(InputMediaPhoto(s))
        # send in batches of 10
        for i in range(0, len(media), 10):
            await _priority_send(message, client.send_media_group, message.chat.id, media[i:i+10],
                                          reply_to_message_id=message.id)
        await msg.delete()
    except Exception as e:
        logger.exception("ss error")
        await safe_edit_text(msg, f"❌ Error: <code>{e}</code>")
    finally:
        asyncio.create_task(cleanup_dir(work))


# ===================== SAMPLE VIDEO =====================
@Client.on_message(filters.private & _cmd('sample'))
@_interactive_media_task("Sample video")
async def cmd_sample(client: Client, message: Message):
    if not message.reply_to_message or not (message.reply_to_message.video or message.reply_to_message.document):
        return await safe_reply_text(message, Translation.NO_VIDEO_REPLY)
    uid = message.from_user.id
    parts = (message.text or "").split()
    secs = 60
    if len(parts) > 1:
        try:
            secs = int(parts[1])
        except Exception:
            secs = 60

    work = user_download_dir(uid) + f"/sample_{int(time.time())}"
    os.makedirs(work, exist_ok=True)
    msg = await _command_proxy(message)
    try:
        path, _ = await _download_replied(client, message, uid, work)
        if not path:
            return
        # Sample from 10% position, length = secs
        dur = await get_video_duration(path)
        start = max(0, int(dur * 0.1))
        if start + secs > dur:
            start = max(0, int(dur - secs))
        out = os.path.join(work, "sample_" + os.path.basename(path))
        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-ss", str(start), "-i", path, "-t", str(secs),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", out,
        ]
        await safe_edit_text(msg, f"🎬 Cutting {secs}s sample...")
        rc, _o, err = await run_cmd(cmd, timeout=1800)
        if rc != 0 or not os.path.exists(out):
            return await safe_edit_text(msg, f"❌ Sample failed: <code>{err[:500]}</code>")
        sz = os.path.getsize(out)
        await safe_edit_text(msg, "📤 Uploading sample...")
        await _priority_send(message, client.send_video, message.chat.id, video=out,
                                caption=f"🎬 Sample ({secs}s) | {humanbytes(sz)}",
                                supports_streaming=True,
                                reply_to_message_id=message.id)
        await msg.delete()
    except Exception as e:
        logger.exception("sample error")
        await safe_edit_text(msg, f"❌ Error: <code>{e}</code>")
    finally:
        asyncio.create_task(cleanup_dir(work))


# ===================== TRIM =====================
@Client.on_message(filters.private & _cmd('trim', 'cut'))
@_interactive_media_task("Video trim")
async def cmd_trim(client: Client, message: Message):
    if not message.reply_to_message:
        return await safe_reply_text(message, 
            "<b>Usage:</b> Reply to a video with <code>/trim START END</code>\n"
            "Examples:\n"
            "<code>/trim 30 90</code> → from 30s to 90s\n"
            "<code>/trim 01:30 02:00</code> → 1:30 to 2:00"
        )
    parts = (message.text or "").split()
    if len(parts) < 3:
        return await safe_reply_text(message, "❌ <code>/trim START END</code> de do.")
    try:
        s = _to_seconds(parts[1]); e = _to_seconds(parts[2])
    except Exception as ex:
        return await safe_reply_text(message, f"❌ Time parse error: {ex}")
    if e <= s:
        return await safe_reply_text(message, "❌ END must be > START.")
    uid = message.from_user.id
    work = user_download_dir(uid) + f"/trim_{int(time.time())}"
    os.makedirs(work, exist_ok=True)
    msg = await _command_proxy(message)
    try:
        path, _ = await _download_replied(client, message, uid, work)
        if not path:
            return
        out = os.path.join(work, "trimmed_" + os.path.basename(path))
        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-ss", str(s), "-i", path, "-t", str(e - s),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", out,
        ]
        await safe_edit_text(msg, f"✂️ Trimming {s}s → {e}s...")
        rc, _o, err = await run_cmd(cmd, timeout=3600)
        if rc != 0 or not os.path.exists(out):
            return await safe_edit_text(msg, f"❌ Trim failed: <code>{err[:600]}</code>")
        await safe_edit_text(msg, "📤 Uploading...")
        await _priority_send(message, client.send_video, message.chat.id, video=out,
                                caption=f"✂️ Trimmed {time_formatter(s)} → {time_formatter(e)}",
                                supports_streaming=True,
                                reply_to_message_id=message.id)
        await msg.delete()
    except Exception as ex:
        logger.exception("trim error")
        await safe_edit_text(msg, f"❌ Error: <code>{ex}</code>")
    finally:
        asyncio.create_task(cleanup_dir(work))


# ===================== COMPRESS =====================
@Client.on_message(filters.private & _cmd('compress'))
@_interactive_media_task("Video compression")
async def cmd_compress(client: Client, message: Message):
    if not message.reply_to_message:
        return await safe_reply_text(message, "<b>Usage:</b> Reply to video with <code>/compress [low|med|high]</code>")
    parts = (message.text or "").split()
    preset = parts[1].lower() if len(parts) > 1 else "med"
    presets = {
        "low":  ("32", "ultrafast", "64k",  "480"),   # smallest file
        "med":  ("28", "veryfast",  "96k",  "720"),
        "high": ("24", "medium",    "128k", "1080"),
    }
    if preset not in presets:
        preset = "med"
    crf, fp, br, res = presets[preset]
    uid = message.from_user.id
    work = user_download_dir(uid) + f"/cmp_{int(time.time())}"
    os.makedirs(work, exist_ok=True)
    msg = await _command_proxy(message)
    try:
        path, _ = await _download_replied(client, message, uid, work)
        if not path:
            return
        out = os.path.join(work, "compressed_" + os.path.splitext(os.path.basename(path))[0] + ".mp4")
        scale = f"scale=-2:{res}"
        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-i", path,
            "-vf", scale,
            "-c:v", "libx264", "-preset", fp, "-crf", crf,
            "-c:a", "aac", "-b:a", br,
            "-movflags", "+faststart", out,
        ]
        await safe_edit_text(msg, f"🗜️ Compressing ({preset})...")
        rc, _o, err = await run_cmd(cmd, timeout=3600)
        if rc != 0 or not os.path.exists(out):
            return await safe_edit_text(msg, f"❌ Compress failed: <code>{err[:600]}</code>")
        sz_in = os.path.getsize(path); sz_out = os.path.getsize(out)
        pct = 100 - (sz_out * 100 / max(sz_in, 1))
        await safe_edit_text(msg, "📤 Uploading...")
        await _priority_send(message, client.send_video, message.chat.id, video=out,
                                caption=f"🗜️ Compressed ({preset})\n"
                                        f"Before: {humanbytes(sz_in)} → After: {humanbytes(sz_out)} "
                                        f"({pct:.1f}% smaller)",
                                supports_streaming=True,
                                reply_to_message_id=message.id)
        await msg.delete()
    except Exception as ex:
        logger.exception("compress error")
        await safe_edit_text(msg, f"❌ Error: <code>{ex}</code>")
    finally:
        asyncio.create_task(cleanup_dir(work))


# ===================== WATERMARK =====================
@Client.on_message(filters.private & _cmd('wm', 'watermark'))
@_interactive_media_task("Watermark")
async def cmd_watermark(client: Client, message: Message):
    # Usage: /wm "text" [top-left|top-right|bottom-left|bottom-right|center]
    # or reply to an image → use that as watermark
    if not message.reply_to_message:
        return await safe_reply_text(message, 
            "<b>Usage:</b>\n"
            "• Reply to a video/photo with <code>/wm YourText [pos]</code>\n"
            "  pos: top-left, top-right, bottom-left (default), bottom-right, center\n"
            "• Reply to a video AND attach a small image → image watermark."
        )
    parts = (message.text or "").split(None, 1)
    wm_text = ""
    pos = Config.BIMBO_WATERMARK_POSITION or "bottom-right"
    if len(parts) > 1:
        rest = parts[1].strip()
        # try to split last word as position
        toks = rest.rsplit(None, 1)
        if len(toks) == 2 and toks[1].lower() in {"top-left", "top-right", "bottom-left",
                                                   "bottom-right", "center", "tl", "tr", "bl", "br", "c"}:
            wm_text = toks[0].strip(' "')
            pos = {"tl": "top-left", "tr": "top-right", "bl": "bottom-left",
                   "br": "bottom-right", "c": "center"}.get(toks[1].lower(), toks[1].lower())
        else:
            wm_text = rest.strip(' "')
    if not wm_text and Config.BIMBO_WATERMARK_TEXT:
        wm_text = Config.BIMBO_WATERMARK_TEXT

    uid = message.from_user.id
    work = user_download_dir(uid) + f"/wm_{int(time.time())}"
    os.makedirs(work, exist_ok=True)
    msg = await _command_proxy(message)
    try:
        path, _ = await _download_replied(client, message, uid, work)
        if not path:
            return

        is_photo = path.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))
        out = os.path.join(work, "wm_" + os.path.basename(path))

        if is_photo:
            # PIL watermark for images
            await safe_edit_text(msg, "💧 Adding watermark to image...")
            img = Image.open(path).convert("RGBA")
            txt = Image.new("RGBA", img.size, (255, 255, 255, 0))
            fsize = max(24, min(img.size) // 22)
            try:
                font = ImageFont.truetype(Config.BIMBO_WATERMARK_FONT, fsize)
            except Exception:
                font = ImageFont.load_default()
            d = ImageDraw.Draw(txt)
            # measure
            bbox = d.textbbox((0, 0), wm_text, font=font)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            W, H = img.size
            pad = 18
            positions = {
                "top-left": (pad, pad),
                "top-right": (W - tw - pad, pad),
                "bottom-left": (pad, H - th - pad),
                "bottom-right": (W - tw - pad, H - th - pad),
                "center": ((W - tw) // 2, (H - th) // 2),
            }
            x, y = positions.get(pos, positions["bottom-right"])
            # stroke shadow
            d.text((x + 2, y + 2), wm_text, font=font, fill=(0, 0, 0, 180))
            d.text((x, y), wm_text, font=font, fill=(255, 255, 255, 230))
            out2 = Image.alpha_composite(img, txt).convert("RGB")
            out_jpg = os.path.splitext(out)[0] + ".jpg"
            out2.save(out_jpg, "JPEG", quality=92)
            await _priority_send(message, client.send_photo, message.chat.id, out_jpg,
                                    caption=f"💧 Watermarked: {wm_text}",
                                    reply_to_message_id=message.id)
        else:
            # FFmpeg drawtext for videos
            await safe_edit_text(msg, "💧 Adding watermark to video (FFmpeg)...")
            # Escape special chars
            t = wm_text.replace(":", r"\:").replace("'", r"\'").replace("\\", r"\\\\")
            font_path = Config.BIMBO_WATERMARK_FONT
            if not os.path.exists(font_path):
                font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
            # drawtext position
            drawtext_pos = {
                "top-left":     "x=20:y=20",
                "top-right":    "x=w-tw-20:y=20",
                "bottom-left":  "x=20:y=h-th-20",
                "bottom-right": "x=w-tw-20:y=h-th-20",
                "center":       "x=(w-tw)/2:y=(h-th)/2",
            }.get(pos, "x=w-tw-20:y=h-th-20")
            vf = (f"drawtext=fontfile='{font_path}':text='{t}':"
                  f"{drawtext_pos}:"
                  "fontsize=28:fontcolor=white@0.9:"
                  "borderw=3:bordercolor=black@0.7")
            cmd = [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-i", path,
                "-vf", vf,
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                "-c:a", "copy", "-movflags", "+faststart", out,
            ]
            rc, _o, err = await run_cmd(cmd, timeout=3600)
            if rc != 0 or not os.path.exists(out):
                return await safe_edit_text(msg, f"❌ Watermark failed: <code>{err[:600]}</code>")
            await safe_edit_text(msg, "📤 Uploading...")
            await _priority_send(message, client.send_video, message.chat.id, video=out,
                                    caption=f"💧 Watermarked: {wm_text}",
                                    supports_streaming=True,
                                    reply_to_message_id=message.id)
        await msg.delete()
    except Exception as ex:
        logger.exception("wm error")
        await safe_edit_text(msg, f"❌ Error: <code>{ex}</code>")
    finally:
        asyncio.create_task(cleanup_dir(work))


# ===================== MP3 / AUDIO EXTRACT =====================
@Client.on_message(filters.private & _cmd('mp3', 'audio', 'extract_audio'))
@_interactive_media_task("Audio extraction")
async def cmd_mp3(client: Client, message: Message):
    if not message.reply_to_message or not (message.reply_to_message.video or message.reply_to_message.document):
        return await safe_reply_text(message, Translation.NO_VIDEO_REPLY)
    uid = message.from_user.id
    work = user_download_dir(uid) + f"/mp3_{int(time.time())}"
    os.makedirs(work, exist_ok=True)
    msg = await _command_proxy(message)
    try:
        path, _ = await _download_replied(client, message, uid, work)
        if not path:
            return
        await safe_edit_text(msg, "🎵 Extracting audio...")
        out = os.path.join(work, os.path.splitext(os.path.basename(path))[0] + ".mp3")
        out_path = await extract_audio(path, "mp3", "192k")
        if not out_path:
            return await safe_edit_text(msg, "❌ Audio extract failed.")
        await safe_edit_text(msg, "📤 Uploading...")
        await _priority_send(message, client.send_audio, message.chat.id, audio=out_path,
                                caption="🎵 Extracted by BIMBO",
                                reply_to_message_id=message.id)
        await msg.delete()
    except Exception as ex:
        logger.exception("mp3 error")
        await safe_edit_text(msg, f"❌ Error: <code>{ex}</code>")
    finally:
        asyncio.create_task(cleanup_dir(work))


# ===================== ZIP =====================
@Client.on_message(filters.private & _cmd('zip'))
@_interactive_media_task("ZIP creator")
async def cmd_zip(client: Client, message: Message):
    """Download the replied media, create a ZIP, then priority-upload it."""
    if not message.reply_to_message or not is_media(message.reply_to_message):
        return await safe_reply_text(message, "❌ Reply to a file/media with <code>/zip</code>.")
    uid = message.from_user.id
    work = user_download_dir(uid) + f"/zip_{int(time.time())}"
    os.makedirs(work, exist_ok=True)
    msg = await _command_proxy(message)
    try:
        path, _ = await _download_replied(client, message, uid, work)
        if not path:
            return
        await safe_edit_text(msg, "📦 Creating ZIP archive...")
        zip_name = safe_filename(os.path.basename(path)) + ".zip"
        zip_path = os.path.join(work, zip_name)
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(path, arcname=os.path.basename(path))
        await safe_edit_text(msg, "📤 Uploading ZIP...")
        await _priority_send(
            message, client.send_document, message.chat.id, zip_path,
            caption=f"📦 {zip_name}", reply_to_message_id=message.id,
        )
        await msg.delete()
    except Exception as exc:
        logger.exception("zip error")
        await safe_edit_text(msg, f"❌ ZIP error: <code>{exc}</code>")
    finally:
        asyncio.create_task(cleanup_dir(work))


# ===================== UNZIP =====================
@Client.on_message(filters.private & _cmd('unzip', 'extract'))
@_interactive_media_task("ZIP extraction")
async def cmd_unzip(client: Client, message: Message):
    if not message.reply_to_message or not message.reply_to_message.document:
        return await safe_reply_text(message, "❌ Reply to a .zip file.")
    fn = (message.reply_to_message.document.file_name or "").lower()
    if not fn.endswith(".zip"):
        return await safe_reply_text(message, "❌ Only .zip supported for now.")
    uid = message.from_user.id
    work = user_download_dir(uid) + f"/uz_{int(time.time())}"
    os.makedirs(work, exist_ok=True)
    msg = await _command_proxy(message)
    try:
        path, _ = await _download_replied(client, message, uid, work)
        if not path:
            return
        out_dir = os.path.join(work, "extracted")
        os.makedirs(out_dir, exist_ok=True)
        await safe_edit_text(msg, "📦 Extracting zip...")
        try:
            with zipfile.ZipFile(path, "r") as z:
                z.extractall(out_dir)
        except Exception as e:
            return await safe_edit_text(msg, f"❌ Extract failed: <code>{e}</code>")
        files = []
        for root, _, fs in os.walk(out_dir):
            for f in fs:
                files.append(os.path.join(root, f))
        if not files:
            return await safe_edit_text(msg, "❌ Zip khali hai.")
        await safe_edit_text(msg, f"📤 Uploading {min(10, len(files))} file(s)...")
        for f in files[:10]:  # cap 10 files per zip
            try:
                sz = os.path.getsize(f)
                if sz > Config.BIMBO_TG_MAX_FILE_SIZE:
                    continue
                await _priority_send(message, client.send_document, message.chat.id, f,
                                           reply_to_message_id=message.id)
            except Exception as e:
                logger.warning(f"unzip upload fail: {e}")
        if len(files) > 10:
            await safe_reply_text(message, f"ℹ️ Sirf pehle 10 files bheje, total {len(files)} the.")
        await msg.delete()
    except Exception as ex:
        logger.exception("unzip error")
        await safe_edit_text(msg, f"❌ Error: <code>{ex}</code>")
    finally:
        asyncio.create_task(cleanup_dir(work))


# ===================== RENAME =====================
@Client.on_message(filters.private & _cmd('rename', 'rn'))
@_interactive_media_task("File rename")
async def cmd_rename(client: Client, message: Message):
    if not message.reply_to_message:
        return await safe_reply_text(message, "<b>Usage:</b> Reply to a file/video with <code>/rename new_name.mp4</code>")
    parts = (message.text or "").split(None, 1)
    if len(parts) < 2:
        return await safe_reply_text(message, "❌ New name de do: <code>/rename new_name.mp4</code>")
    new_name = safe_filename(parts[1])
    uid = message.from_user.id
    work = user_download_dir(uid) + f"/rn_{int(time.time())}"
    os.makedirs(work, exist_ok=True)
    msg = await _command_proxy(message)
    try:
        path, _ = await _download_replied(client, message, uid, work)
        if not path:
            return
        new_path = os.path.join(work, new_name)
        shutil.copy(path, new_path)
        await safe_edit_text(msg, "📤 Uploading...")
        if new_name.lower().endswith((".mp4", ".mkv", ".webm", ".mov")):
            await _priority_send(message, client.send_video, message.chat.id, new_path,
                                    caption=f"✏️ Renamed: <b>{new_name}</b>",
                                    supports_streaming=True,
                                    reply_to_message_id=message.id)
        else:
            await _priority_send(message, client.send_document, message.chat.id, new_path,
                                       caption=f"✏️ Renamed: <b>{new_name}</b>",
                                       reply_to_message_id=message.id)
        await msg.delete()
    except Exception as ex:
        logger.exception("rename error")
        await safe_edit_text(msg, f"❌ Error: <code>{ex}</code>")
    finally:
        asyncio.create_task(cleanup_dir(work))
