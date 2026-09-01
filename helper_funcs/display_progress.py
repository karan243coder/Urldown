# ============================================================
# BIMBO Bot v3.0 - ULTIMATE ADVANCED PROGRESS DISPLAY
# Powered by BIMBO | Support: @Bimbo69
# ============================================================
# Features:
# - Per-task engine display (⚡Aria2, 🎬yt-dlp, 🔷Pyrogram)
# - Multi-task in single message
# - Real-time system stats per task
# - Beautiful animated progress bars
# - Live speed graph (text-based)
# - Download/Upload separation
# - Cancel handler per task
# ============================================================

import logging
import math
import re
import time
import psutil
import os
import asyncio
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ===================== GLOBAL TASK TRACKER =====================
# Ek centralized store jisme saare active tasks ka data rahega
_task_store = {}         # task_id -> task_data
_user_tasks = {}         # user_id -> [task_ids]
_task_messages = {}      # user_id -> the ONE canonical dashboard message
_progress_locks = {}      # user_id -> asyncio.Lock (prevents message races)

# Speed tracking for smoothing
speed_history = {}
last_edit_time = {}
last_progress_text = {}

PROGRESS_UPDATE_INTERVAL = 2
DASHBOARD_UPDATE_INTERVAL = 5
SPEED_HISTORY_LIMIT = 15
_cancelled_ids = set()
_user_last_header = {}  # user_id -> last header image path/url


def stall_timeout_seconds():
    """Global dead-download timeout (seconds). Default 6 minutes."""
    try:
        from config import Config
        return max(180, int(getattr(Config, "BIMBO_STALL_TIMEOUT", 360) or 360))
    except Exception:
        return 360


def is_task_cancelled(task_id):
    if not task_id:
        return False
    if task_id in _cancelled_ids:
        return True
    task = _task_store.get(task_id)
    return bool(task and task.get("cancel_flag"))


# ===================== ENGINE DETECTION =====================
ENGINE_ICONS = {
    'aria2': '⚡Aria2',
    'yt-dlp': '🎬yt-dlp', 
    'pyrogram': '🔷Pyro',
    'libtorrent': '🧲Torrent',
    'ffmpeg': '🎞️FFmpeg',
    'requests': '🌐HTTP',
    'direct': '📁Direct',
    'terabox': '📦Terabox',
    'xhamster': '🔞XHams',
    'eporner': '🔞EPorn',
    'unknown': '❓Unknown'
}

ENGINE_COLORS = {
    'aria2': '🟢',
    'yt-dlp': '🔵',
    'pyrogram': '🟣',
    'libtorrent': '🟠',
    'ffmpeg': '🔴',
}


# ===================== TASK MANAGEMENT =====================

def register_task(task_id, user_id, filename="Unknown", total_size=0, 
                  task_type="download", engine="pyrogram", source_url=""):
    """Naya task register karo tracker mein"""
    # task_id is the identity. Two profile videos can legitimately have the
    # same title/filename, so filename-based de-duplication would drop jobs.
    if task_id in _task_store:
        return _task_store[task_id]

    now = time.time()
    task = {
        'id': task_id,
        'user_id': user_id,
        'filename': filename,
        'total_size': total_size,
        'downloaded': 0,
        'speed': 0,
        'avg_speed': 0,
        'percentage': 0,
        'status': 'queued',      # queued, downloading, uploading, completed, failed, cancelled
        'task_type': task_type,   # download, upload
        'engine': engine,
        'source_url': source_url,
        'start_time': now,
        'eta': 0,
        'elapsed': 0,
        'error': None,
        'detail': '',
        'completed': False,
        'speed_samples': [],
        'last_update': now,
        'cancel_flag': False,
    }
    
    _task_store[task_id] = task
    
    if user_id not in _user_tasks:
        _user_tasks[user_id] = []
    if task_id not in _user_tasks[user_id]:
        _user_tasks[user_id].append(task_id)
    
    # Track task start time for timeout
    _task_start_time[user_id] = now
    
    return task


def update_task(task_id, downloaded, total_size=0, speed=0, status=None, engine=None):
    """Task ka progress update karo"""
    task = _task_store.get(task_id)
    if not task:
        return None
    
    now = time.time()
    task['downloaded'] = downloaded
    if total_size > 0:
        task['total_size'] = total_size
    if status in ('waiting', 'queued'):
        task['speed'] = 0
        task['avg_speed'] = 0
        task['speed_samples'].clear()
    elif speed > 0:
        task['speed'] = speed
    
    # Smooth speed (moving average)
    task['speed_samples'].append(speed if speed > 0 else task['speed'])
    if len(task['speed_samples']) > 10:
        task['speed_samples'].pop(0)
    task['avg_speed'] = sum(task['speed_samples']) / len(task['speed_samples']) if task['speed_samples'] else 0
    
    if task['total_size'] > 0:
        task['percentage'] = (task['downloaded'] / task['total_size']) * 100
        remaining = task['total_size'] - task['downloaded']
        task['eta'] = remaining / task['avg_speed'] if task['avg_speed'] > 0 else 0
    else:
        task['percentage'] = 0
        task['eta'] = 0
    
    task['elapsed'] = now - task['start_time']
    task['last_update'] = now
    
    if engine:
        task['engine'] = engine
    if status:
        task['status'] = status
        if status in ['completed', 'failed', 'cancelled']:
            task['completed'] = True
    
    return task


def get_task(task_id):
    return _task_store.get(task_id)


def set_task_stage(task_id, task_type=None, status=None, engine=None,
                   downloaded=None, total_size=None, reset_timer=False,
                   detail=None):
    """Change download → processing/upload without creating a second card."""
    task = _task_store.get(task_id)
    if not task:
        return None
    if task_type:
        task['task_type'] = task_type
    if status:
        task['status'] = status
    if engine:
        task['engine'] = engine
    if detail is not None:
        task['detail'] = str(detail)[:160]
    if downloaded is not None:
        task['downloaded'] = max(0, int(downloaded))
    if total_size is not None:
        task['total_size'] = max(0, int(total_size))
    if reset_timer:
        task['start_time'] = time.time()
        task['elapsed'] = 0
        task['speed'] = 0
        task['avg_speed'] = 0
        task['speed_samples'].clear()
    if task['total_size'] > 0:
        task['percentage'] = min(100, task['downloaded'] / task['total_size'] * 100)
    else:
        task['percentage'] = 0
    task['last_update'] = time.time()
    return task


def remove_task(task_id):
    task = _task_store.pop(task_id, None)
    if task:
        uid = task['user_id']
        if uid in _user_tasks and task_id in _user_tasks[uid]:
            _user_tasks[uid].remove(task_id)
    return task


def prune_stalled_tasks(user_id=None, max_age=None):
    """Mark + drop download tasks with no progress for stall_timeout.

    Waiting/queued jobs are waiting for a slot — not dead.
    Uploads are left alone (Telegram can be slow without being dead).
    """
    max_age = int(max_age or stall_timeout_seconds())
    now = time.time()
    removed = []
    if user_id is None:
        candidates = list(_task_store.items())
    else:
        candidates = [
            (tid, _task_store.get(tid))
            for tid in list(_user_tasks.get(user_id, []))
        ]
    for tid, task in candidates:
        if not task or task.get("completed"):
            continue
        status = task.get("status") or ""
        if status in ("queued", "waiting", "uploading"):
            if status == "queued" and task.get("downloaded", 0) == 0:
                age = now - (task.get("start_time") or now)
                if age <= max_age:
                    continue
            else:
                continue
        last = task.get("last_update") or task.get("start_time") or now
        if (now - last) < max_age:
            continue
        task["cancel_flag"] = True
        task["status"] = "failed"
        task["error"] = f"Dead / no progress for {max_age // 60} min"
        task["completed"] = True
        _cancelled_ids.add(tid)
        logger.info("Pruning stalled task %s user=%s status=%s idle=%.0fs",
                    tid, task.get("user_id"), status, now - last)
        remove_task(tid)
        removed.append(tid)
    return removed


def get_user_active_tasks(user_id):
    """Ek user ke saare active tasks lao"""
    prune_stalled_tasks(user_id)
    active = []
    stale_ids = []
    now = time.time()
    max_age = stall_timeout_seconds()
    for tid in _user_tasks.get(user_id, []):
        t = _task_store.get(tid)
        if not t:
            continue
        if (t.get('status') == 'queued' and
            t.get('percentage', 0) == 0 and
            t.get('downloaded', 0) == 0 and
            (now - t.get('start_time', now)) > max_age):
            stale_ids.append(tid)
            continue
        if not t.get('completed'):
            active.append(t)
    for tid in stale_ids:
        logger.info(f"Removing stale queued task: {tid}")
        _cancelled_ids.add(tid)
        remove_task(tid)
    return active


def get_user_all_tasks(user_id):
    """User ke saare tasks (completed bhi)"""
    all_t = []
    for tid in _user_tasks.get(user_id, []):
        t = _task_store.get(tid)
        if t:
            all_t.append(t)
    return all_t


def _message_identity(message):
    """Stable identity for comparing two Pyrogram Message objects."""
    if message is None:
        return None
    chat = getattr(message, 'chat', None)
    chat_id = getattr(chat, 'id', None)
    message_id = getattr(message, 'id', None)
    if message_id is None:
        message_id = getattr(message, 'message_id', None)
    return chat_id, message_id


def _progress_lock(user_id):
    lock = _progress_locks.get(user_id)
    if lock is None:
        lock = asyncio.Lock()
        _progress_locks[user_id] = lock
    return lock


def set_user_message(user_id, message, replace=False):
    """Set the canonical dashboard without silently replacing a live one.

    Historically each concurrent task overwrote this mapping with its own
    message. Both task loops then edited different messages, creating duplicate
    BIMBO PROGRESS cards. The first live dashboard now stays canonical.
    """
    if message is None:
        return _task_messages.get(user_id)
    current = _task_messages.get(user_id)
    if (
        current is None
        or replace
        or _message_identity(current) == _message_identity(message)
    ):
        _task_messages[user_id] = message
        return message
    return current


def get_user_message(user_id):
    return _task_messages.get(user_id)


async def claim_user_progress_message(user_id, candidate, delete_duplicate=True):
    """Atomically claim one dashboard message for a user.

    If two downloads start together, both may create a candidate reply before
    either stores it. The per-user lock picks exactly one and deletes the extra
    candidate, so only one live dashboard remains in the chat.
    """
    if candidate is None:
        return get_user_message(user_id)
    async with _progress_lock(user_id):
        current = _task_messages.get(user_id)
        if current is None:
            _task_messages[user_id] = candidate
            return candidate
        if _message_identity(current) == _message_identity(candidate):
            return current
        if delete_duplicate:
            try:
                await candidate.delete()
            except Exception as exc:
                logger.debug("Could not delete duplicate progress message: %s", exc)
        return current


def clear_user_message(user_id, message=None):
    """Clear mapping only when it still points at the expected message."""
    current = _task_messages.get(user_id)
    if current is None:
        return None
    if message is not None and _message_identity(current) != _message_identity(message):
        return current
    _task_messages.pop(user_id, None)
    _last_progress_update.pop(user_id, None)
    _progress_flood_until.pop(user_id, None)
    return current


def _clear_dashboard_state(user_id):
    _task_messages.pop(user_id, None)
    _last_progress_update.pop(user_id, None)
    _progress_flood_until.pop(user_id, None)
    _dashboard_is_photo.pop(user_id, None)
    _photo_update_count.pop(user_id, None)
    _user_sticker_msg.pop(user_id, None)
    _task_start_time.pop(user_id, None)


async def reset_idle_dashboard(client, user_id):
    """Delete the old progress card so the next job gets a NEW header image.

    Only runs when this user has no other live tasks. Concurrent live jobs
    keep the same canonical dashboard (no duplicate cards).
    """
    prune_stalled_tasks(user_id)
    live = [
        t for t in get_user_active_tasks(user_id)
        if t.get("status") not in ("queued", "waiting")
    ]
    # If anything is actually downloading/uploading, keep the live card.
    if live:
        return get_user_message(user_id)

    async with _progress_lock(user_id):
        current = _task_messages.get(user_id)
        photo = _user_sticker_msg.get(user_id)
        _clear_dashboard_state(user_id)
        for msg in (photo, current):
            if msg is None:
                continue
            try:
                await msg.delete()
            except Exception as exc:
                logger.debug("Old progress card delete skipped: %s", exc)
        return None


async def finalize_user_progress(client, user_id, message=None, delete_if_idle=True):
    """Delete dashboard only after the user's LAST active task finishes."""
    async with _progress_lock(user_id):
        current = _task_messages.get(user_id)
        active = get_user_active_tasks(user_id)
        pipeline_pending = 0
        try:
            from plugins.media_pipeline import get_pipeline_stats
            pipeline_pending = get_pipeline_stats(user_id).get('total_pending', 0)
        except Exception:
            pass
        
        # If there are still active tasks, just update the message
        if active or pipeline_pending:
            if current is not None:
                try:
                    text = await build_advanced_progress_text(user_id)
                    if text:
                        is_photo = _dashboard_is_photo.get(user_id, False)
                        if is_photo:
                            try:
                                await current.edit_caption(text[:1024])
                            except Exception:
                                await current.edit_text(text)
                        else:
                            await current.edit_text(text)
                except Exception as exc:
                    if "MESSAGE_NOT_MODIFIED" not in str(exc).upper():
                        logger.debug("Final progress refresh skipped: %s", exc)
            return False

        # No active tasks - clean up and delete
        if current is None:
            _dashboard_is_photo.pop(user_id, None)
            _photo_update_count.pop(user_id, None)
            _user_sticker_msg.pop(user_id, None)
            return True

        # Clear all tracking
        _task_messages.pop(user_id, None)
        _last_progress_update.pop(user_id, None)
        _progress_flood_until.pop(user_id, None)
        _dashboard_is_photo.pop(user_id, None)
        _photo_update_count.pop(user_id, None)
        _user_sticker_msg.pop(user_id, None)
        
        if delete_if_idle:
            try:
                await current.delete()
                logger.info(f"Progress dashboard deleted for user {user_id}")
            except Exception as exc:
                logger.debug(f"Could not delete finished progress dashboard: {exc}")
                # Fallback: try to edit with completion message
                try:
                    await current.edit_text("✅ Task Complete!\n\n_Message will auto-delete in 10 seconds_")
                except Exception:
                    pass
        return True


def cancel_task(task_id):
    """Task cancel karo"""
    task = _task_store.get(task_id)
    if task:
        task['cancel_flag'] = True
        task['status'] = 'cancelled'
        task['completed'] = True
        return True
    return False


# ===================== UI HELPERS =====================

def trim_text(text, limit=35):
    text = str(text or "Unknown File").strip()
    text = re.sub(r'\s+', ' ', text)
    if len(text) <= limit:
        return text
    return text[:limit-3] + "..."


def humanbytes(size):
    if size is None or size <= 0:
        return "0B"
    labels = ['B', 'KB', 'MB', 'GB', 'TB']
    for i, label in enumerate(labels):
        if size < 1024 or i == len(labels)-1:
            return f"{size:.2f}{label}" if i > 0 else f"{int(size)}{label}"
        size /= 1024


def format_speed(bytes_per_sec):
    if not bytes_per_sec or bytes_per_sec <= 0:
        return "0B/s"
    return f"{humanbytes(bytes_per_sec)}/s"


def format_time(seconds=None, milliseconds=None):
    """Unified time formatter - accepts seconds (positional) or milliseconds (keyword)"""
    # Support: format_time(seconds_value) and TimeFormatter(milliseconds=X)
    if seconds is not None:
        ms = seconds * 1000
    elif milliseconds is not None:
        ms = milliseconds
    else:
        return "0s"
    
    if ms is None or ms < 0:
        return "∞"
    
    ms = int(ms)
    seconds = ms // 1000
    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if days:
        return f"{days}d {hours:02d}h {minutes:02d}m"
    if hours:
        return f"{hours}h {minutes:02d}m {secs:02d}s"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def build_advanced_bar(percentage, width=14):
    """
    Super advanced progress bar:
    [████████░░░░] 67.3%
    """
    percentage = max(0, min(100, percentage))
    filled = int(width * percentage / 100)
    empty = width - filled
    
    if percentage >= 100:
        bar = "█" * width
    elif percentage > 80:
        bar = "█" * filled + "░" * empty
    elif percentage > 50:
        bar = "▓" * filled + "░" * empty
    elif percentage > 20:
        bar = "▒" * filled + "░" * empty
    else:
        bar = "░" * width
    
    return f"`[{bar}]`"


def get_speed_indicator(speed_bytes):
    """Speed ke hisaab se emoji indicator"""
    mbps = speed_bytes / (1024 * 1024)
    if mbps > 10:
        return "🚀"  # Very fast
    elif mbps > 5:
        return "⚡"   # Fast
    elif mbps > 1:
        return "🔸"   # Medium
    elif mbps > 0.1:
        return "🐢"   # Slow
    else:
        return "⏸️"   # Stalled


def get_status_emoji(status):
    emojis = {
        'queued': '⏳',
        'waiting': '⏸️',
        'downloading': '📥',
        'uploading': '📤',
        'processing': '⚙️',
        'splitting': '✂️',
        'completed': '✅',
        'failed': '❌',
        'cancelled': '🚫',
        'starting': '🔄',
    }
    return emojis.get(status, '❓')


def get_system_stats_advanced():
    """Advanced system statistics"""
    try:
        cpu = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        boot_seconds = time.time() - psutil.boot_time()
        uptime = format_time(seconds=boot_seconds)
        
        # CPU bar
        cpu_bar = "█" * int(cpu/10) + "░" * (10 - int(cpu/10))
        
        # Memory bar
        mem_bar = "█" * int(mem.percent/10) + "░" * (10 - int(mem.percent/10))
        
        # Active means actually consuming a stage slot. Queued/waiting jobs are
        # reported separately by the unified media pipeline footer.
        active_count = sum(
            1 for t in _task_store.values()
            if not t['completed'] and t.get('status') not in ('queued', 'waiting')
        )
        total_count = sum(1 for t in _task_store.values() if not t['completed'])
        
        # Total speeds
        total_dl = sum(t.get('avg_speed', 0) for t in _task_store.values() 
                      if not t['completed'] and t['task_type'] == 'download')
        total_ul = sum(t.get('avg_speed', 0) for t in _task_store.values()
                      if not t['completed'] and t['task_type'] == 'upload')
        
        return {
            'cpu': cpu,
            'cpu_bar': cpu_bar,
            'ram': mem.percent,
            'ram_bar': mem_bar,
            'ram_used': mem.used,
            'ram_total': mem.total,
            'disk_free': disk.free,
            'disk_total': disk.total,
            'disk_percent': disk.percent,
            'uptime': uptime,
            'active_tasks': active_count,
            'total_tasks': total_count,
            'total_dl_speed': total_dl,
            'total_ul_speed': total_ul,
        }
    except:
        return {'cpu': 0, 'cpu_bar': '░'*10, 'ram': 0, 'ram_bar': '░'*10,
                'disk_free': 0, 'disk_percent': 0, 'uptime': '0s',
                'active_tasks': 0, 'total_tasks': 0,
                'total_dl_speed': 0, 'total_ul_speed': 0}


# ===================== MAIN PROGRESS BUILDER =====================

async def build_advanced_progress_text(user_id):
    """Premium compact, mobile-first, single-message live dashboard."""
    user_tasks = get_user_active_tasks(user_id)
    all_tasks = get_user_all_tasks(user_id)

    running_tasks = [
        task for task in user_tasks
        if task.get('status') not in ('queued', 'waiting')
    ]
    waiting_tasks = [
        task for task in user_tasks
        if task.get('status') in ('queued', 'waiting')
    ]
    tasks = running_tasks[:4]
    if not tasks and waiting_tasks:
        tasks = waiting_tasks[:1]

    try:
        from plugins.media_pipeline import get_pipeline_stats
        mine = get_pipeline_stats(user_id)
        global_q = get_pipeline_stats()
    except Exception:
        mine = global_q = {
            'download_active': 0, 'download_waiting': 0, 'download_limit': 2,
            'upload_active': 0, 'upload_waiting': 0, 'upload_limit': 2,
            'bulk_pending': 0, 'interactive': 0, 'total_pending': 0,
        }

    if not all_tasks and mine.get('total_pending', 0) <= 0:
        return None

    active_now = len(running_tasks)
    stall_m = stall_timeout_seconds() // 60
    clock = datetime.now().strftime("%H:%M")
    text = (
        f"⚡ **BIMBO LIVE**  •  `{active_now} active`  •  `{clock}`\n"
        f"🛡️ dead-link auto-drop `{stall_m}m`\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
    )

    for index, task in enumerate(tasks, 1):
        is_upload = task.get('task_type') == 'upload'
        stage_icon = '⬆️' if is_upload else '⬇️'
        stage_name = 'UPLOAD' if is_upload else 'DOWNLOAD'
        name = trim_text(task.get('filename'), 29)
        pct = max(0.0, min(100.0, float(task.get('percentage', 0))))
        bar_width = 12
        filled = int(bar_width * pct / 100)
        bar = '▰' * filled + '▱' * (bar_width - filled)
        done = humanbytes(task.get('downloaded', 0))
        total = humanbytes(task.get('total_size', 0)) if task.get('total_size', 0) else '?'
        speed = format_speed(task.get('avg_speed', 0))
        eta = format_time(task.get('eta', 0))
        elapsed = format_time(task.get('elapsed', 0))
        engine = ENGINE_ICONS.get(task.get('engine'), task.get('engine', 'unknown'))
        status = task.get('status', 'queued')

        text += f"\n{stage_icon} **{index} · {stage_name}**\n"
        text += f"`{name}`\n"
        text += f"`{bar}`  **{pct:.1f}%**\n"
        if status in ('queued', 'waiting'):
            text += f"⏳ {status_text(task)}\n"
        else:
            stalled_hint = ""
            if status in ("downloading", "starting") and float(task.get("avg_speed") or 0) <= 0 and float(task.get("elapsed") or 0) >= 45:
                stalled_hint = "  •  ⚠️ no speed"
            text += f"📦 {done} / {total}  •  ⚡ {speed}{stalled_hint}\n"
            text += f"⏱ {eta} left  •  🕒 {elapsed}\n"
        detail = trim_text(task.get('detail', ''), 42)
        if detail:
            text += f"🔄 {detail}\n"
        text += f"{engine}  •  {get_status_emoji(status)} `{status.upper()}`\n"

    hidden = max(0, len(user_tasks) - len(tasks))
    if hidden:
        text += f"\n⏳ **+{hidden} task(s) queued below**\n"

    text += (
        "\n🧭 **PIPELINE QUEUE**\n"
        f"⬇️ DL  `{global_q['download_active']}/{global_q['download_limit']}`"
        f"  •  wait `{global_q['download_waiting']}`\n"
        f"⬆️ UL  `{global_q['upload_active']}/{global_q['upload_limit']}`"
        f"  •  wait `{global_q['upload_waiting']}`\n"
        f"📚 Bulk left `{global_q['bulk_pending']}`"
        f"  •  👤 Yours `{mine['total_pending']}`\n"
        f"🚀 Priority jobs `{global_q.get('interactive', 0)}`\n"
    )

    stats = get_system_stats_advanced()
    text += (
        "\n🖥️ **SYSTEM HEALTH**\n"
        f"CPU `{stats['cpu']:.0f}%`  •  RAM `{stats['ram']:.0f}%`"
        f"  •  Free `{humanbytes(stats['disk_free'])}`\n"
        f"Net ⬇️ `{format_speed(stats['total_dl_speed'])}`"
        f"  ⬆️ `{format_speed(stats['total_ul_speed'])}`\n"
    )
    warnings = []
    if stats['ram'] >= 85:
        warnings.append('High RAM')
    if stats['disk_free'] and stats['disk_free'] < 2 * 1024**3:
        warnings.append('Low disk')
    if stats['cpu'] >= 90:
        warnings.append('High CPU')
    if warnings:
        text += f"⚠️ **{' • '.join(warnings)}**\n"
    text += "━━━━━━━━━━━━━━━━━━━━"
    return text


def status_text(task):
    """Human readable status"""
    s = task['status']
    if s == 'downloading':
        return "⬇️ Downloading..."
    elif s == 'waiting':
        return "⏸️ Waiting for safe download slot..."
    elif s == 'uploading':
        return "⬆️ Uploading..."
    elif s == 'processing':
        return "⚙️ Processing..."
    elif s == 'splitting':
        return "✂️ Splitting large file..."
    elif s == 'queued':
        return "⏳ Queued..."
    elif s == 'completed':
        return "✅ Completed"
    elif s == 'failed':
        return f"❌ Failed: {task.get('error', 'Unknown')}"
    elif s == 'cancelled':
        return "🚫 Cancelled"
    return s.capitalize()


_last_progress_update = {}  # user_id -> timestamp
_progress_flood_until = {}   # user_id -> hard Telegram cooldown timestamp
_dashboard_is_photo = {}     # user_id -> True if current dashboard is a photo
_photo_update_count = {}     # user_id -> count of photo updates
_user_sticker_msg = {}       # user_id -> sticker message (kept for entire task)
_task_start_time = {}        # user_id -> timestamp when task started (for timeout)
_user_header_image = {}      # user_id -> current header image (kept for entire task)

def _collect_header_images():
    sources = []
    try:
        from plugins.admin_panel import get_progress_images, get_image_folder
        sources.extend(get_progress_images() or [])
        folder = get_image_folder()
        if folder and os.path.isdir(folder):
            files = [
                os.path.join(folder, f) for f in os.listdir(folder)
                if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))
                and not f.startswith('.')
            ]
            sources.extend(files)
    except Exception as e:
        logger.debug(f"Failed to list header images: {e}")
    try:
        from config import Config
        pic_config = getattr(Config, 'BIMBO_PROGRESS_PIC', '')
        if pic_config:
            sources.extend([img.strip() for img in pic_config.split(',') if img.strip()])
    except Exception:
        pass
    seen = set()
    unique = []
    for item in sources:
        if item and item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


def _get_random_header_image(user_id=None):
    """Get a random header image, avoiding the last one used for this user."""
    import random
    images = _collect_header_images()
    if not images:
        try:
            from plugins.admin_panel import get_random_progress_image
            return get_random_progress_image()
        except Exception as e:
            logger.debug(f"Failed to get header image from admin: {e}")
            return None
    last = _user_last_header.get(user_id) if user_id is not None else None
    pool = [img for img in images if img != last] or images
    chosen = random.choice(pool)
    if user_id is not None:
        _user_last_header[user_id] = chosen
    return chosen


async def _send_progress_with_caption(client, chat_id, caption, reply_to_msg_id=None, user_id=None):
    """Send photo with caption (WZML style - image + text together)."""
    try:
        image_path = _get_random_header_image(user_id if user_id is not None else chat_id)
        if not image_path:
            return None
        
        # Photo + Caption ek sath (WZML style)
        sent = await client.send_photo(
            chat_id=chat_id,
            photo=image_path,
            caption=caption[:1024] if caption else None,
            reply_to_message_id=reply_to_msg_id
        )
        logger.debug(f"Sent progress photo with caption: {image_path}")
        return sent
    except Exception as e:
        logger.debug(f"Progress photo send failed: {e}")
        return None


async def update_user_progress(client, user_id, force=False):
    """Edit exactly one canonical dashboard with race/FloodWait protection.
    Photo + Caption ek sath (WZML style)."""
    from pyrogram.errors import FloodWait

    now = time.time()
    if now < _progress_flood_until.get(user_id, 0):
        return
    last = _last_progress_update.get(user_id, 0)
    if not force and now - last < DASHBOARD_UPDATE_INTERVAL:
        return

    async with _progress_lock(user_id):
        now = time.time()
        if now < _progress_flood_until.get(user_id, 0):
            return
        last = _last_progress_update.get(user_id, 0)
        if not force and now - last < DASHBOARD_UPDATE_INTERVAL:
            return

        message = get_user_message(user_id)
        if not message:
            return

        text = await build_advanced_progress_text(user_id)
        if not text:
            _task_messages.pop(user_id, None)
            _last_progress_update.pop(user_id, None)
            _progress_flood_until.pop(user_id, None)
            _dashboard_is_photo.pop(user_id, None)
            _photo_update_count.pop(user_id, None)
            try:
                await message.delete()
            except Exception:
                pass
            return

        # Send photo + caption ONCE per task (WZML style)
        photo_msg = _user_sticker_msg.get(user_id)
        if photo_msg is None and not _dashboard_is_photo.get(user_id, False):
            # No photo yet - send photo with caption
            try:
                old_msg = _task_messages.get(user_id)
                photo_msg = await _send_progress_with_caption(
                    client, user_id, text, reply_to_msg_id=None, user_id=user_id
                )
                if photo_msg:
                    _user_sticker_msg[user_id] = photo_msg
                    _dashboard_is_photo[user_id] = True
                    _task_messages[user_id] = photo_msg
                    _last_progress_update[user_id] = now
                    # Auto-clean the initial "Starting Download..." text message so chat remains 100% silent & clean!
                    if old_msg and getattr(old_msg, "id", None) != getattr(photo_msg, "id", None):
                        try:
                            await old_msg.delete()
                        except Exception:
                            pass
                    return
            except Exception as e:
                logger.debug(f"Failed to send photo: {e}")

        #  Update progress ─
        try:
            _last_progress_update[user_id] = now

            is_photo = _dashboard_is_photo.get(user_id, False)
            
            if is_photo and photo_msg:
                # Photo hai - caption edit karo (WZML style - image same, text update)
                try:
                    await photo_msg.edit_caption(caption=text[:1024])
                    _photo_update_count[user_id] = _photo_update_count.get(user_id, 0) + 1
                    _progress_flood_until.pop(user_id, None)
                    return
                except Exception as e:
                    logger.debug(f"Caption edit failed: {e}")
                    # Fallback to text
                    _dashboard_is_photo[user_id] = False

            # Text dashboard - edit text
            await message.edit_text(text)
            _progress_flood_until.pop(user_id, None)
        except FloodWait as exc:
            wait_seconds = max(1, int(getattr(exc, 'value', 3)))
            _progress_flood_until[user_id] = now + wait_seconds + 1
            _last_progress_update[user_id] = now
            logger.warning("⏳ FloodWait: %ss - dashboard hard cooldown enabled", wait_seconds)
        except Exception as exc:
            error_text = str(exc)
            if "MESSAGE_NOT_MODIFIED" in error_text.upper() or "same content" in error_text.lower():
                return
            gone_markers = ("MESSAGE_ID_INVALID", "MessageIdInvalid", "message to edit not found", "MESSAGE_EMPTY")
            if not any(marker in error_text for marker in gone_markers):
                logger.error("Progress update error: %s", exc)
                return
            # Dashboard deleted, recreate
            _task_messages.pop(user_id, None)
            _last_progress_update.pop(user_id, None)
            _progress_flood_until.pop(user_id, None)
            _dashboard_is_photo.pop(user_id, None)
            _photo_update_count.pop(user_id, None)
            _user_sticker_msg.pop(user_id, None)
            if client is not None:
                try:
                    replacement = await client.send_message(user_id, text)
                    _task_messages[user_id] = replacement
                    _last_progress_update[user_id] = time.time()
                except Exception as recreate_exc:
                    logger.error("Could not recreate progress dashboard: %s", recreate_exc)
            # mapping and recreate one once, under the same lock.
            _task_messages.pop(user_id, None)
            _last_progress_update.pop(user_id, None)
            _progress_flood_until.pop(user_id, None)
            if client is not None:
                try:
                    replacement = await client.send_message(user_id, text)
                    _task_messages[user_id] = replacement
                    _last_progress_update[user_id] = time.time()
                except Exception as recreate_exc:
                    logger.error("Could not recreate progress dashboard: %s", recreate_exc)


# ===================== LEGACY SUPPORT =====================
# Purane progress_for_pyrogram function ko bhi support karo

def cleanup_progress_state(msg_id):
    speed_history.pop(msg_id, None)
    last_edit_time.pop(msg_id, None)
    last_progress_text.pop(msg_id, None)


async def cleanup_stuck_tasks(client, max_age_seconds=None):
    """Drop dead downloads from the dashboard after stall_timeout (default 6 min)."""
    max_age = int(max_age_seconds or stall_timeout_seconds())
    prune_stalled_tasks(max_age=max_age)

    user_ids = set(_task_messages.keys()) | set(_user_tasks.keys()) | set(_task_start_time.keys())
    for user_id in list(user_ids):
        prune_stalled_tasks(user_id, max_age=max_age)
        active = get_user_active_tasks(user_id)
        if active:
            continue
        try:
            await finalize_user_progress(client, user_id, delete_if_idle=True)
        except Exception as e:
            logger.debug(f"Failed to cleanup stuck dashboard: {e}")
            _clear_dashboard_state(user_id)


async def progress_for_pyrogram(current, total, ud_type, message, start,
                                file_name="", is_download=False):
    """
    Individual progress callback for uploads/downloads.
    Shows detailed progress card for each task separately.
    """
    if not message or total == 0:
        return
    
    try:
        msg_id = message.id
        chat_id = message.chat.id if hasattr(message, 'chat') else 0
    except:
        return
    
    # CRITICAL: Ignore log channel uploads completely
    from config import Config
    if hasattr(Config, 'BIMBO_LOG_CHANNEL') and Config.BIMBO_LOG_CHANNEL:
        # Convert to int for comparison
        try:
            log_channel_id = int(str(Config.BIMBO_LOG_CHANNEL).replace('-100', ''))
            chat_id_clean = int(str(chat_id).replace('-100', ''))
            if chat_id_clean == log_channel_id or chat_id == Config.BIMBO_LOG_CHANNEL:
                # This is a log channel upload, completely ignore it
                return
        except:
            pass
    
    now = time.time()
    diff = max(now - start, 0.001)
    last_time = last_edit_time.get(msg_id, 0)
    
    if (now - last_time < PROGRESS_UPDATE_INTERVAL) and current not in (0, total) and current != total:
        return
    
    # Smooth speed
    instant_speed = current / diff if diff > 0 else 0
    history = speed_history.setdefault(msg_id, [])
    history.append(instant_speed)
    if len(history) > SPEED_HISTORY_LIMIT:
        history.pop(0)
    avg_speed = sum(history) / len(history) if history else instant_speed
    
    percentage = (current * 100) / total
    percentage = min(max(percentage, 0), 100)
    
    # 1. Update central unified advanced progress card
    try:
        task_id = f"pyro_{msg_id}"
        task = get_task(task_id)
        if not task:
            # Check if there's ALREADY an upload task for this user (from youtube_dl_button)
            # This prevents double registration of the same upload
            existing_active = get_user_active_tasks(chat_id)
            existing_upload = None
            for et in existing_active:
                if et.get('task_type') == 'upload' and not et.get('completed'):
                    existing_upload = et
                    break
            
            if existing_upload:
                # Use existing upload task instead of creating new one
                task_id = existing_upload['id']
            else:
                register_task(
                    task_id=task_id,
                    user_id=chat_id,
                    filename=file_name or ud_type or "File",
                    total_size=total,
                    task_type='upload' if not is_download else 'download',
                    engine='pyrogram'
                )
            set_user_message(chat_id, message)
        
        update_task(
            task_id=task_id,
            downloaded=current,
            total_size=total,
            speed=avg_speed,
            status='uploading' if not is_download else 'downloading'
        )
        await update_user_progress(None, chat_id)
        
        # Cleanup when complete
        if current == total:
            remove_task(task_id)
            cleanup_progress_state(msg_id)
        last_edit_time[msg_id] = now
        return
    except Exception as e:
        logger.error(f"Unified pyro progress error: {e}")

    # Build individual progress card
    task_type = "UPLOAD" if not is_download else "DOWNLOAD"
    status_emoji = "📤" if not is_download else "📥"
    
    # Format sizes
    current_size = humanbytes(current)
    total_size = humanbytes(total)
    speed_text = f"{humanbytes(avg_speed)}/s"
    
    # Calculate ETA
    if avg_speed > 0 and current < total:
        eta_seconds = (total - current) / avg_speed
        eta_text = format_time(eta_seconds)
    else:
        eta_text = "0s"
    
    # Elapsed time
    elapsed_text = format_time(diff)
    
    # Progress bar
    bar_length = 20
    filled = int(bar_length * percentage / 100)
    bar = "█" * filled + "░" * (bar_length - filled)
    
    # Build progress card
    display_name = trim_text(file_name or ud_type or "File", 35)
    
    progress_text = (
        f"╭━━━〔 {status_emoji} {task_type} 〕━━━╮\n"
        f"┃ 📁 File: {display_name}\n"
        f"┃ [{bar}] {percentage:.1f}%\n"
        f"┃ ⚡ Speed: {speed_text}\n"
        f"┃ 📦 Progress: {current_size} / {total_size}\n"
        f"┃ ⏳ ETA: {eta_text}\n"
        f"┃ 🕒 Elapsed: {elapsed_text}\n"
        f"╰━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╯"
    )
    
    # Update message
    try:
        await message.edit_text(progress_text)
        last_edit_time[msg_id] = now
        last_progress_text[msg_id] = progress_text
        
        # Cleanup when complete
        if current == total:
            cleanup_progress_state(msg_id)
    except Exception as e:
        if "MESSAGE_NOT_MODIFIED" not in str(e).upper():
            logger.debug(f"Progress edit error: {e}")
        if current == total:
            cleanup_progress_state(msg_id)


def cleanup_all_progress():
    _task_store.clear()
    _user_tasks.clear()
    _task_messages.clear()
    _progress_locks.clear()
    _last_progress_update.clear()
    _progress_flood_until.clear()
    speed_history.clear()
    last_edit_time.clear()
    last_progress_text.clear()

# ===================== LEGACY ALIASES (for backward compatibility) =====================
# Purane code mein TimeFormatter use hota hai
TimeFormatter = format_time
