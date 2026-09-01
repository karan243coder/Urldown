import os
import psutil
import platform
from datetime import datetime
from pyrogram import filters, Client
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from database.access import bimbo
from config import BIMBO_OWNER_ID
import logging

logger = logging.getLogger(__name__)

# Track active downloads
active_downloads = {}

def add_active_download(user_id: int, file_name: str, total_size: int):
    """Add an active download to tracking"""
    active_downloads[user_id] = {
        'file_name': file_name,
        'total_size': total_size,
        'start_time': datetime.now()
    }

def remove_active_download(user_id: int):
    """Remove an active download from tracking"""
    active_downloads.pop(user_id, None)

def get_active_download(user_id: int):
    """Get active download info for a user"""
    return active_downloads.get(user_id)

def get_system_info():
    """Get system information"""
    try:
        # CPU
        cpu_percent = psutil.cpu_percent(interval=1)
        cpu_count = psutil.cpu_count()
        
        # Memory
        memory = psutil.virtual_memory()
        memory_percent = memory.percent
        memory_used = memory.used / (1024**3)  # GB
        memory_total = memory.total / (1024**3)  # GB
        
        # Disk
        disk = psutil.disk_usage('/')
        disk_percent = disk.percent
        disk_used = disk.used / (1024**3)  # GB
        disk_total = disk.total / (1024**3)  # GB
        
        # Network
        net_io = psutil.net_io_counters()
        net_sent = net_io.bytes_sent / (1024**2)  # MB
        net_recv = net_io.bytes_recv / (1024**2)  # MB
        
        # Uptime
        boot_time = datetime.fromtimestamp(psutil.boot_time())
        uptime = datetime.now() - boot_time
        
        return {
            'cpu_percent': cpu_percent,
            'cpu_count': cpu_count,
            'memory_percent': memory_percent,
            'memory_used': memory_used,
            'memory_total': memory_total,
            'disk_percent': disk_percent,
            'disk_used': disk_used,
            'disk_total': disk_total,
            'net_sent': net_sent,
            'net_recv': net_recv,
            'uptime': str(uptime).split('.')[0],
            'platform': platform.system(),
            'python_version': platform.python_version()
        }
    except Exception as e:
        logger.error(f"System info error: {e}")
        return None

def create_progress_bar(percent, length=10):
    """Create a text progress bar"""
    filled = int(length * percent / 100)
    bar = '█' * filled + '░' * (length - filled)
    return f"[{bar}] {percent:.1f}%"

@Client.on_message(filters.command("status"))
async def system_status(client: Client, message: Message):
    """Show system status"""
    # Get system info
    sys_info = get_system_info()
    
    if not sys_info:
        await message.reply_text("❌ Failed to get system information")
        return
    
    # Get user count
    try:
        total_users = await bimbo.total_users_count()
    except:
        total_users = "N/A"
    
    # Get active downloads
    active_count = len(active_downloads)
    
    # Build status message
    status_text = (
        f"📊 **System Status**\n\n"
        f"🖥️ **Server Info:**\n"
        f"├ 💻 OS: {sys_info['platform']}\n"
        f"├ 🐍 Python: {sys_info['python_version']}\n"
        f"└ ⏱️ Uptime: {sys_info['uptime']}\n\n"
        
        f"📈 **Resource Usage:**\n"
        f"├ 🧠 CPU: {create_progress_bar(sys_info['cpu_percent'])}\n"
        f"├ 💾 RAM: {create_progress_bar(sys_info['memory_percent'])}\n"
        f"│  └ {sys_info['memory_used']:.2f} GB / {sys_info['memory_total']:.2f} GB\n"
        f"└ 💿 Disk: {create_progress_bar(sys_info['disk_percent'])}\n"
        f"   └ {sys_info['disk_used']:.2f} GB / {sys_info['disk_total']:.2f} GB\n\n"
        
        f"🌐 **Network:**\n"
        f"├ ⬆️ Sent: {sys_info['net_sent']:.2f} MB\n"
        f"└ ⬇️ Received: {sys_info['net_recv']:.2f} MB\n\n"
        
        f"📊 **Bot Stats:**\n"
        f"├ 👥 Total Users: {total_users}\n"
        f"├ 📥 Active Downloads: {active_count}\n"
        f"└ 🤖 Status: ✅ Online\n\n"
    )
    
    # Add active downloads details
    if active_downloads:
        status_text += "🔄 **Active Downloads:**\n"
        for user_id, download in list(active_downloads.items())[:5]:  # Show max 5
            file_name = download['file_name'][:40]
            size_mb = download['total_size'] / (1024 * 1024)
            status_text += f"├ 👤 User {user_id}: {file_name} ({size_mb:.1f} MB)\n"
    
    # Add buttons
    buttons = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔄 Refresh", callback_data="refresh_status")
        ]
    ])
    
    await message.reply_text(status_text, reply_markup=buttons)

@Client.on_callback_query(filters.regex("^refresh_status$"))
async def refresh_status_callback(client: Client, callback_query):
    """Refresh status on button click"""
    await callback_query.answer("Refreshing...")
    
    # Get updated info
    sys_info = get_system_info()
    
    if not sys_info:
        await callback_query.message.edit_text("❌ Failed to refresh")
        return
    
    # Get user count
    try:
        total_users = await bimbo.total_users_count()
    except:
        total_users = "N/A"
    
    # Get active downloads
    active_count = len(active_downloads)
    
    # Build updated status
    status_text = (
        f"📊 **System Status** (Updated)\n\n"
        f"🖥️ **Server Info:**\n"
        f"├ 💻 OS: {sys_info['platform']}\n"
        f"├ 🐍 Python: {sys_info['python_version']}\n"
        f"└ ⏱️ Uptime: {sys_info['uptime']}\n\n"
        
        f"📈 **Resource Usage:**\n"
        f"├ 🧠 CPU: {create_progress_bar(sys_info['cpu_percent'])}\n"
        f"├ 💾 RAM: {create_progress_bar(sys_info['memory_percent'])}\n"
        f"│  └ {sys_info['memory_used']:.2f} GB / {sys_info['memory_total']:.2f} GB\n"
        f"└ 💿 Disk: {create_progress_bar(sys_info['disk_percent'])}\n"
        f"   └ {sys_info['disk_used']:.2f} GB / {sys_info['disk_total']:.2f} GB\n\n"
        
        f"🌐 **Network:**\n"
        f"├ ⬆️ Sent: {sys_info['net_sent']:.2f} MB\n"
        f"└ ⬇️ Received: {sys_info['net_recv']:.2f} MB\n\n"
        
        f"📊 **Bot Stats:**\n"
        f"├ 👥 Total Users: {total_users}\n"
        f"├ 📥 Active Downloads: {active_count}\n"
        f"└ 🤖 Status: ✅ Online\n"
    )
    
    buttons = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔄 Refresh", callback_data="refresh_status")
        ]
    ])
    
    try:
        await callback_query.message.edit_text(status_text, reply_markup=buttons)
    except Exception as e:
        if "MESSAGE_NOT_MODIFIED" not in str(e):
            logger.error(f"Status refresh error: {e}")

@Client.on_message(filters.command("stats") & filters.user(BIMBO_OWNER_ID))
async def admin_stats(client: Client, message: Message):
    """Admin stats command"""
    try:
        total_users = await bimbo.total_users_count()
    except:
        total_users = "N/A"
    
    # Get all users
    try:
        all_users = await bimbo.get_all_users()
        user_list = []
        async for user in all_users:
            user_list.append(user['id'])
    except:
        user_list = []
    
    stats_text = (
        f"📊 **Admin Statistics**\n\n"
        f"👥 **Users:**\n"
        f"├ Total: {total_users}\n"
        f"├ Active Downloads: {len(active_downloads)}\n"
        f"└ User IDs: {', '.join(map(str, user_list[:10]))}{'...' if len(user_list) > 10 else ''}\n\n"
        
        f"📥 **Downloads:**\n"
        f"├ Active: {len(active_downloads)}\n"
        f"└ Queue: 0\n\n"
        
        f"💾 **Storage:**\n"
        f"└ Download folder: {BIMBO_DOWNLOAD_LOCATION if 'BIMBO_DOWNLOAD_LOCATION' in globals() else './downloads'}\n"
    )
    
    await message.reply_text(stats_text)
