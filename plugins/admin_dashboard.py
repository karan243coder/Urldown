"""
Admin Dashboard - Full Control Commands
Features: Queue management, user control, statistics, system monitoring
"""

import asyncio
import time
import psutil
import logging
from datetime import datetime
from pyrogram import Client, filters
from pyrogram.types import Message
from config import Config
from plugins.queue_manager import queue_manager
from utils import is_admin, humanbytes, time_formatter

logger = logging.getLogger(__name__)

def admin_only(func):
    """Decorator to restrict commands to admins only"""
    async def wrapper(client: Client, message: Message):
        if not is_admin(message.from_user.id):
            await message.reply_text("❌ Sirf admins ke liye hai!")
            return
        return await func(client, message)
    return wrapper


@Client.on_message(filters.command("queue") & filters.private)
@admin_only
async def cmd_queue(client: Client, message: Message):
    """Show current queue status"""
    status = queue_manager.get_queue_status()
    
    text = "📊 **Queue Status**\n\n"
    text += f"🔄 Queued: {status['queued']}\n"
    text += f"⚡ Active: {status['active']}\n"
    text += f"✅ Completed: {status['completed']}\n"
    text += f"❌ Failed: {status['failed']}\n"
    text += f"🎯 Max Concurrent: {status['max_concurrent']}\n"
    
    # Show active downloads
    if queue_manager.active_downloads:
        text += "\n**Active Downloads:**\n"
        for task_id, task in list(queue_manager.active_downloads.items())[:5]:
            text += f"• {task.filename[:30]}... ({task.progress:.1f}%)\n"
    
    # Show queued tasks
    if queue_manager.queue:
        text += "\n**Queued Tasks:**\n"
        for task in queue_manager.queue[:5]:
            text += f"• #{task.position} {task.filename[:30]}...\n"
    
    await message.reply_text(text)


@Client.on_message(filters.command("cancel") & filters.private)
@admin_only
async def cmd_cancel(client: Client, message: Message):
    """Cancel a task by ID"""
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply_text("Usage: /cancel <task_id>")
        return
    
    task_id = args[1].strip()
    if queue_manager.cancel_task(task_id):
        await message.reply_text(f"✅ Task {task_id} cancelled")
    else:
        await message.reply_text(f"❌ Task {task_id} not found")


@Client.on_message(filters.command("pause") & filters.private)
@admin_only
async def cmd_pause(client: Client, message: Message):
    """Pause an active task"""
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply_text("Usage: /pause <task_id>")
        return
    
    task_id = args[1].strip()
    if queue_manager.pause_task(task_id):
        await message.reply_text(f"⏸️ Task {task_id} paused")
    else:
        await message.reply_text(f"❌ Task {task_id} not found or not active")


@Client.on_message(filters.command("resume") & filters.private)
@admin_only
async def cmd_resume(client: Client, message: Message):
    """Resume a paused task"""
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply_text("Usage: /resume <task_id>")
        return
    
    task_id = args[1].strip()
    if queue_manager.resume_task(task_id):
        await message.reply_text(f"▶️ Task {task_id} resumed")
    else:
        await message.reply_text(f"❌ Task {task_id} not found or not paused")


@Client.on_message(filters.command("stats") & filters.private)
@admin_only
async def cmd_stats(client: Client, message: Message):
    """Show detailed system statistics"""
    # RAM usage
    ram = psutil.virtual_memory()
    ram_used = humanbytes(ram.used)
    ram_total = humanbytes(ram.total)
    ram_percent = ram.percent
    
    # Disk usage
    disk = psutil.disk_usage('/')
    disk_used = humanbytes(disk.used)
    disk_total = humanbytes(disk.total)
    disk_percent = disk.percent
    
    # Queue stats
    queue_status = queue_manager.get_queue_status()
    
    # Uptime
    uptime = time_formatter(time.time() - psutil.boot_time())
    
    text = "📈 **System Statistics**\n\n"
    text += f"**RAM Usage:**\n"
    text += f"• Used: {ram_used} / {ram_total} ({ram_percent}%)\n"
    text += f"• Available: {humanbytes(ram.available)}\n\n"
    
    text += f"**Disk Usage:**\n"
    text += f"• Used: {disk_used} / {disk_total} ({disk_percent}%)\n"
    text += f"• Free: {humanbytes(disk.free)}\n\n"
    
    text += f"**Queue Stats:**\n"
    text += f"• Queued: {queue_status['queued']}\n"
    text += f"• Active: {queue_status['active']}\n"
    text += f"• Completed: {queue_status['completed']}\n"
    text += f"• Failed: {queue_status['failed']}\n\n"
    
    text += f"**System:**\n"
    text += f"• Uptime: {uptime}\n"
    text += f"• CPU Cores: {psutil.cpu_count()}\n"
    
    await message.reply_text(text)


@Client.on_message(filters.command("clear") & filters.private)
@admin_only
async def cmd_clear(client: Client, message: Message):
    """Clear completed/failed tasks"""
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply_text("Usage: /clear <completed|failed|all>")
        return
    
    action = args[1].strip().lower()
    
    if action == "completed":
        queue_manager.clear_completed()
        await message.reply_text("✅ Completed tasks cleared")
    elif action == "failed":
        queue_manager.clear_failed()
        await message.reply_text("✅ Failed tasks cleared")
    elif action == "all":
        queue_manager.clear_completed()
        queue_manager.clear_failed()
        await message.reply_text("✅ All completed/failed tasks cleared")
    else:
        await message.reply_text("❌ Invalid action. Use: completed, failed, or all")


@Client.on_message(filters.command("task") & filters.private)
@admin_only
async def cmd_task(client: Client, message: Message):
    """Show task details"""
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply_text("Usage: /task <task_id>")
        return
    
    task_id = args[1].strip()
    task = queue_manager.get_task_info(task_id)
    
    if not task:
        await message.reply_text(f"❌ Task {task_id} not found")
        return
    
    text = f"📋 **Task Details**\n\n"
    text += f"**ID:** `{task.task_id}`\n"
    text += f"**User:** `{task.user_id}`\n"
    text += f"**File:** {task.filename}\n"
    text += f"**Status:** {task.status}\n"
    text += f"**Quality:** {task.quality}\n"
    text += f"**Priority:** {task.priority}\n"
    
    if task.position > 0:
        text += f"**Position:** #{task.position}\n"
    
    if task.progress > 0:
        text += f"**Progress:** {task.progress:.1f}%\n"
    
    if task.eta:
        text += f"**ETA:** {time_formatter(task.eta)}\n"
    
    text += f"\n**Created:** {datetime.fromtimestamp(task.created_at).strftime('%Y-%m-%d %H:%M:%S')}\n"
    
    if task.started_at:
        text += f"**Started:** {datetime.fromtimestamp(task.started_at).strftime('%Y-%m-%d %H:%M:%S')}\n"
    
    if task.completed_at:
        text += f"**Completed:** {datetime.fromtimestamp(task.completed_at).strftime('%Y-%m-%d %H:%M:%S')}\n"
    
    if task.error_message:
        text += f"\n**Error:** {task.error_message}\n"
    
    await message.reply_text(text)


@Client.on_message(filters.command("setconcurrent") & filters.private)
@admin_only
async def cmd_set_concurrent(client: Client, message: Message):
    """Set max concurrent downloads"""
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply_text("Usage: /setconcurrent <number>")
        return
    
    try:
        value = int(args[1].strip())
        if value < 1 or value > 10:
            await message.reply_text("❌ Value must be between 1 and 10")
            return
        
        queue_manager.max_concurrent = value
        await message.reply_text(f"✅ Max concurrent downloads set to {value}")
    except ValueError:
        await message.reply_text("❌ Invalid number")
