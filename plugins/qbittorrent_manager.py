# BIMBO v4.0 - qBittorrent Integration Plugin
# ============================================
# Features:
# - qBittorrent daemon management
# - Mirror/Leech with torrent selection
# - Seed ratio control
# - Better peer management
# - Web UI integration

import os
import time
import asyncio
import logging
import subprocess
from pathlib import Path
from typing import Optional, Dict, List

from pyrogram import Client, filters, enums
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

from config import Config
from database.adduser import AddUser
from helper_funcs.display_progress import (
    register_task, update_task, remove_task, get_task,
    set_user_message, get_user_message, claim_user_progress_message,
    update_user_progress, finalize_user_progress,
    humanbytes, format_time, format_speed
)
from plugins.media_pipeline import stage_slot

logger = logging.getLogger(__name__)

# qBittorrent API client
qb_client = None
QB_ENABLED = False

# Torrent tracking
qb_torrents = {}  # hash -> task_id mapping


async def init_qbittorrent():
    """Initialize qBittorrent connection"""
    global qb_client, QB_ENABLED
    
    if not Config.QB_ENABLED:
        logger.info("qBittorrent is disabled")
        return False
    
    from urllib.parse import urlparse
    if urlparse(Config.QB_URL).port == 8080 or str(Config.QB_URL).strip().endswith(":8080") or str(Config.QB_URL).strip().endswith(":8080/"):
        logger.warning("Config.QB_URL 8080 conflicts with Stream Server! Overriding to http://localhost:8090")
        Config.QB_URL = "http://localhost:8090"
    
    try:
        import qbittorrentapi as qba
        
        qb_client = qba.Client(
            host=Config.QB_URL,
            username=Config.QB_USERNAME,
            password=Config.QB_PASSWORD,
            VERIFY_WEBUI_CERTIFICATE=False
        )
        
        # Test connection with retry loop for daemon startup
        for attempt in range(1, 10):
            try:
                qb_client.auth_log_in()
                break
            except Exception as login_err:
                if attempt == 9:
                    raise login_err
                logger.info(f"Waiting for qBittorrent-nox WebUI (attempt {attempt}/9)...")
                await asyncio.sleep(2)
        
        qb_client.app_version()
        
        QB_ENABLED = True
        logger.info(f"✅ qBittorrent connected: {Config.QB_URL}")
        
        # Set preferences
        qb_client.app_set_preferences({
            'save_path': Config.BIMBO_DOWNLOAD_LOCATION,
            'temp_path_enabled': True,
            'temp_path': Config.BIMBO_DOWNLOAD_LOCATION + '/.qb_temp',
        })
        
        return True
        
    except Exception as e:
        logger.error(f"qBittorrent init failed: {e}")
        QB_ENABLED = False
        return False


async def start_qbittorrent_daemon():
    """Start qBittorrent-nox daemon"""
    try:
        # Check if already running
        result = subprocess.run(['pgrep', '-f', 'qbittorrent-nox'], 
                              capture_output=True, text=True)
        if result.returncode == 0:
            logger.info("qBittorrent daemon already running")
            return True
        
        # Create config directory and write pre-configured qBittorrent.conf
        qb_config_dir = Path.home() / '.config' / 'qBittorrent'
        qb_config_dir.mkdir(parents=True, exist_ok=True)
        conf_content = """[LegalNotice]
Accepted=true

[Preferences]
WebUI\\Address=*
WebUI\\Port=8090
WebUI\\Username=admin
WebUI\\Password_PBKDF2="@ByteArray(ARQ77eY1NUZaQsuDHbIMCA==:0WmrkYTUWIC9wGtvHzXcFMttYD5g2pT0m/JbbdAt+50J6zZc4K150tXhLwL/K8xVzJd06B0m4Vz22fB6lD1iug==)"
WebUI\\LocalHostAuth=false
WebUI\\AuthSubnetWhitelistEnabled=true
WebUI\\AuthSubnetWhitelist=127.0.0.1/32, ::1/128, 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16
"""
        try:
            (qb_config_dir / 'qBittorrent.conf').write_text(conf_content, encoding="utf-8")
            sub_dir = qb_config_dir / 'qBittorrent'
            sub_dir.mkdir(parents=True, exist_ok=True)
            (sub_dir / 'qBittorrent.conf').write_text(conf_content, encoding="utf-8")
        except Exception as conf_err:
            logger.debug(f"Could not pre-write qBittorrent config: {conf_err}")
        
        from urllib.parse import urlparse
        qb_port = urlparse(Config.QB_URL).port or 8090
        if qb_port == 8080 or str(Config.QB_URL).strip().endswith(":8080") or str(Config.QB_URL).strip().endswith(":8080/"):
            logger.warning("Config.QB_URL is set to port 8080, which conflicts with Stream Server! Forcing qBittorrent to port 8090.")
            qb_port = 8090
            Config.QB_URL = "http://localhost:8090"
        
        # Start daemon
        cmd = [
            'qbittorrent-nox',
            '--profile=' + str(qb_config_dir),
            f'--webui-port={qb_port}'
        ]
        
        subprocess.Popen(cmd, 
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        start_new_session=True)
        
        # Wait for startup
        await asyncio.sleep(3)
        
        logger.info("✅ qBittorrent daemon started")
        return True
        
    except Exception as e:
        logger.error(f"Failed to start qBittorrent daemon: {e}")
        return False


def format_torrent_status(torrent) -> Dict:
    """Format torrent info for display"""
    return {
        'hash': torrent.hash,
        'name': torrent.name,
        'size': torrent.size,
        'progress': torrent.progress * 100,
        'dl_speed': torrent.dlspeed,
        'up_speed': torrent.upspeed,
        'downloaded': torrent.downloaded,
        'uploaded': torrent.uploaded,
        'ratio': torrent.ratio,
        'state': torrent.state,
        'num_seeds': torrent.num_seeds,
        'num_leechs': torrent.num_leechs,
        'eta': torrent.eta,
        'added_on': torrent.added_on,
        'completion_on': torrent.completion_on,
    }


# ═════════════════════════════════════════════════════════
# COMMANDS
# ═════════════════════════════════════════════════════════

@Client.on_message(filters.command("qbmirror") & filters.private)
async def qb_mirror_cmd(client: Client, message: Message):
    """Mirror using qBittorrent"""
    await AddUser(client, message)
    
    if not QB_ENABLED:
        return await message.reply_text(
            "❌ **qBittorrent is not enabled!**\n\n"
            "Set `QB_ENABLED=true` in your environment variables."
        )
    
    # Check if link is provided
    if len(message.command) < 2:
        return await message.reply_text(
            "**Usage:** `/qbmirror <torrent_link_or_magnet>`\n\n"
            "Examples:\n"
            "- `/qbmirror magnet:?xt=urn:btih:...`\n"
            "- `/qbmirror https://example.com/file.torrent`"
        )
    
    link = message.command[1]
    user_id = message.from_user.id
    
    # Register task
    task_id = f"qb_{user_id}_{int(time.time())}"
    register_task(
        task_id=task_id,
        user_id=user_id,
        filename="Torrent Download",
        total_size=0,
        task_type='download',
        engine='qbittorrent'
    )
    
    # Create progress message
    progress_msg = await message.reply_text(
        "🧲 **qBittorrent Download**\n\n"
        "⏳ Adding torrent..."
    )
    set_user_message(user_id, progress_msg)
    
    # Enter download stage
    dl_stage_ctx = stage_slot("download", task_id, user_id, site="qbittorrent", client=client)
    await dl_stage_ctx.__aenter__()
    
    try:
        # Add torrent
        try:
            qb_client.torrents_add(urls=link)
            logger.info(f"Torrent added: {link[:50]}...")
        except Exception as e:
            await progress_msg.edit_text(f"❌ **Failed to add torrent:**\n`{e}`")
            remove_task(task_id)
            return
        
        # Wait for torrent to appear
        await asyncio.sleep(2)
        
        # Find the torrent
        torrents = qb_client.torrents_info(sort='added_on', reverse=True, limit=1)
        if not torrents:
            await progress_msg.edit_text("❌ **Torrent not found after adding!**")
            remove_task(task_id)
            return
        
        torrent = torrents[0]
        torrent_hash = torrent.hash
        qb_torrents[torrent_hash] = task_id
        
        # Update task with real info
        update_task(task_id, 0, torrent.size, 0, 'downloading', 'qbittorrent')
        task = get_task(task_id)
        if task:
            task['filename'] = torrent.name
        
        await update_user_progress(client, user_id, force=True)
        
        # Monitor progress
        while True:
            # Get torrent info
            torrent_info = qb_client.torrents_info(torrent_hashes=torrent_hash)
            if not torrent_info:
                break
            
            torrent = torrent_info[0]
            downloaded = torrent.downloaded
            total = torrent.size
            speed = torrent.dlspeed
            progress = torrent.progress * 100
            
            # Update task
            update_task(task_id, downloaded, total, speed, 'downloading', 'qbittorrent')
            
            # Check completion
            if torrent.state in ['completed', 'pausedUP', 'uploading']:
                update_task(task_id, total, total, 0, 'completed', 'qbittorrent')
                break
            
            await asyncio.sleep(2)
            await update_user_progress(client, user_id)
        
        # Download complete - now upload
        file_path = os.path.join(Config.BIMBO_DOWNLOAD_LOCATION, torrent.name)
        
        # Release download slot
        await dl_stage_ctx.__aexit__(None, None, None)
        
        # Start upload
        await upload_to_telegram(client, message, file_path, torrent.name, torrent.size, task_id, user_id)
        
        # Cleanup torrent
        try:
            qb_client.torrents_delete(torrent_hashes=torrent_hash, delete_files=True)
        except Exception as e:
            logger.error(f"Failed to delete torrent: {e}")
        
    except Exception as e:
        logger.error(f"qBittorrent mirror error: {e}")
        await progress_msg.edit_text(f"❌ **Error:**\n`{e}`")
        remove_task(task_id)
    finally:
        await dl_stage_ctx.__aexit__(None, None, None)


@Client.on_message(filters.command("qbleech") & filters.private)
async def qb_leech_cmd(client: Client, message: Message):
    """Leech using qBittorrent (same as mirror for now)"""
    await qb_mirror_cmd(client, message)


@Client.on_message(filters.command("btsel") & filters.private)
async def qb_select_cmd(client: Client, message: Message):
    """Select files from torrent"""
    await AddUser(client, message)
    
    if not QB_ENABLED:
        return await message.reply_text("❌ qBittorrent is not enabled!")
    
    if len(message.command) < 2:
        return await message.reply_text(
            "**Usage:** `/btsel <torrent_hash>`\n\n"
            "Get hash from `/qbstatus` command."
        )
    
    torrent_hash = message.command[1]
    
    try:
        # Get torrent info
        torrent_info = qb_client.torrents_info(torrent_hashes=torrent_hash)
        if not torrent_info:
            return await message.reply_text("❌ **Torrent not found!**")
        
        torrent = torrent_info[0]
        
        # Get files
        files = qb_client.torrents_files(torrent_hash=torrent_hash)
        
        if not files:
            return await message.reply_text("❌ **No files found in torrent!**")
        
        # Build selection buttons
        buttons = []
        for i, file in enumerate(files[:20]):  # Limit to 20 files
            checked = "✅" if file.progress == 1 else "⬜"
            btn_text = f"{checked} {file.name[:30]}"
            buttons.append([InlineKeyboardButton(
                btn_text, 
                callback_data=f"qb_select_{torrent_hash}_{i}"
            )])
        
        buttons.append([InlineKeyboardButton("✅ Done Selecting", callback_data=f"qb_done_{torrent_hash}")])
        buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="qb_cancel")])
        
        await message.reply_text(
            f"📁 **Select Files**\n\n"
            f"**Torrent:** {torrent.name[:40]}\n"
            f"**Files:** {len(files)}\n\n"
            f"Tap files to select/deselect:",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        
    except Exception as e:
        await message.reply_text(f"❌ **Error:**\n`{e}`")


@Client.on_message(filters.command("qbstatus") & filters.private)
async def qb_status_cmd(client: Client, message: Message):
    """Show qBittorrent status"""
    await AddUser(client, message)
    
    if not QB_ENABLED:
        return await message.reply_text("❌ qBittorrent is not enabled!")
    
    try:
        # Get all torrents
        torrents = qb_client.torrents_info()
        
        if not torrents:
            return await message.reply_text("📊 **No active torrents!**")
        
        text = " **Active Torrents**\n\n"
        
        for torrent in torrents[:10]:  # Show max 10
            state_emoji = {
                'downloading': '️',
                'uploading': '️',
                'completed': '✅',
                'pausedDL': '⏸️',
                'pausedUP': '⏸️',
            }.get(torrent.state, '❓')
            
            text += (
                f"{state_emoji} **{torrent.name[:40]}**\n"
                f"   Hash: `{torrent.hash[:16]}...`\n"
                f"   Progress: {torrent.progress*100:.1f}%\n"
                f"   Size: {humanbytes(torrent.size)}\n"
                f"   Speed: ⬇️ {humanbytes(torrent.dlspeed)}/s ️ {humanbytes(torrent.upspeed)}/s\n"
                f"   Ratio: {torrent.ratio:.2f}\n\n"
            )
        
        await message.reply_text(text)
        
    except Exception as e:
        await message.reply_text(f"❌ **Error:**\n`{e}`")


@Client.on_message(filters.command("qbdelete") & filters.private)
async def qb_delete_cmd(client: Client, message: Message):
    """Delete torrent"""
    await AddUser(client, message)
    
    if not QB_ENABLED:
        return await message.reply_text("❌ qBittorrent is not enabled!")
    
    if len(message.command) < 2:
        return await message.reply_text(
            "**Usage:** `/qbdelete <torrent_hash>`\n\n"
            "Get hash from `/qbstatus` command."
        )
    
    torrent_hash = message.command[1]
    
    try:
        qb_client.torrents_delete(torrent_hashes=torrent_hash, delete_files=True)
        await message.reply_text(f"✅ **Torrent deleted!**\n\nHash: `{torrent_hash[:16]}...`")
    except Exception as e:
        await message.reply_text(f"❌ **Error:**\n`{e}`")


@Client.on_message(filters.command("qbpause") & filters.private)
async def qb_pause_cmd(client: Client, message: Message):
    """Pause torrent"""
    await AddUser(client, message)
    
    if not QB_ENABLED:
        return await message.reply_text(" qBittorrent is not enabled!")
    
    if len(message.command) < 2:
        return await message.reply_text(
            "**Usage:** `/qbpause <torrent_hash>`"
        )
    
    torrent_hash = message.command[1]
    
    try:
        qb_client.torrents_pause(torrent_hashes=torrent_hash)
        await message.reply_text(f"⏸️ **Torrent paused!**\n\nHash: `{torrent_hash[:16]}...`")
    except Exception as e:
        await message.reply_text(f"❌ **Error:**\n`{e}`")


@Client.on_message(filters.command("qbresume") & filters.private)
async def qb_resume_cmd(client: Client, message: Message):
    """Resume torrent"""
    await AddUser(client, message)
    
    if not QB_ENABLED:
        return await message.reply_text("❌ qBittorrent is not enabled!")
    
    if len(message.command) < 2:
        return await message.reply_text(
            "**Usage:** `/qbresume <torrent_hash>`"
        )
    
    torrent_hash = message.command[1]
    
    try:
        qb_client.torrents_resume(torrent_hashes=torrent_hash)
        await message.reply_text(f"▶️ **Torrent resumed!**\n\nHash: `{torrent_hash[:16]}...`")
    except Exception as e:
        await message.reply_text(f" **Error:**\n`{e}`")


@Client.on_message(filters.command("qbratio") & filters.private)
async def qb_ratio_cmd(client: Client, message: Message):
    """Set seed ratio"""
    await AddUser(client, message)
    
    if not QB_ENABLED:
        return await message.reply_text("❌ qBittorrent is not enabled!")
    
    if len(message.command) < 3:
        return await message.reply_text(
            "**Usage:** `/qbratio <torrent_hash> <ratio>`\n\n"
            "Example: `/qbratio abc123 2.0`"
        )
    
    torrent_hash = message.command[1]
    ratio = float(message.command[2])
    
    try:
        qb_client.torrents_set_share_limits(
            torrent_hashes=torrent_hash,
            ratio_limit=ratio,
            seeding_time_limit=-1
        )
        await message.reply_text(
            f"✅ **Seed ratio set to {ratio}**\n\n"
            f"Hash: `{torrent_hash[:16]}...`"
        )
    except Exception as e:
        await message.reply_text(f"❌ **Error:**\n`{e}`")


# ══════════════════════════════════════════════════════════
# UPLOAD HELPER
# ═════════════════════════════════════════════════════════

async def upload_to_telegram(client, message, file_path, filename, file_size, task_id, user_id):
    """Upload file to Telegram"""
    try:
        # Check if file exists
        if not os.path.exists(file_path):
            raise Exception(f"File not found: {file_path}")
        
        # Create upload task
        upload_task_id = f"upload_{task_id}"
        register_task(
            task_id=upload_task_id,
            user_id=user_id,
            filename=filename,
            total_size=file_size,
            task_type='upload',
            engine='pyrogram'
        )
        
        # Upload
        progress_msg = get_user_message(user_id)
        
        async def progress_callback(current, total):
            update_task(upload_task_id, current, total, 0, 'uploading', 'pyrogram')
            await update_user_progress(client, user_id)
        
        await client.send_document(
            chat_id=message.chat.id,
            document=file_path,
            caption=f"🧲 {filename}\n\n✅ Downloaded by BIMBO Bot (qBittorrent)",
            progress=progress_callback
        )
        
        # Complete
        update_task(upload_task_id, file_size, file_size, 0, 'completed', 'pyrogram')
        remove_task(task_id)
        remove_task(upload_task_id)
        
        await finalize_user_progress(client, user_id)
        
        logger.info(f"Upload complete: {filename}")
        
    except Exception as e:
        logger.error(f"Upload failed: {e}")
        update_task(task_id, 0, file_size, 0, 'failed', 'pyrogram')
        task = get_task(task_id)
        if task:
            task['error'] = str(e)
        await update_user_progress(client, user_id, force=True)


# ══════════════════════════════════════════════════════════
# CALLBACK HANDLERS
# ═════════════════════════════════════════════════════════

@Client.on_callback_query(filters.regex(r"^qb_(select|done|cancel)"))
async def qb_callback(client: Client, callback_query: CallbackQuery):
    """Handle torrent selection callbacks"""
    data = callback_query.data.split('_')
    
    if data[0] == 'qb' and data[1] == 'cancel':
        await callback_query.message.delete()
        await callback_query.answer("Cancelled!")
        return
    
    if data[0] == 'qb' and data[1] == 'done':
        torrent_hash = data[2]
        try:
            qb_client.torrents_resume(torrent_hashes=torrent_hash)
            await callback_query.message.edit_text("✅ **Selection complete! Downloading...**")
            await callback_query.answer("Download started!")
        except Exception as e:
            await callback_query.answer(f"Error: {e}", show_alert=True)
        return
    
    if data[0] == 'qb' and data[1] == 'select':
        torrent_hash = data[2]
        file_index = int(data[3])
        
        try:
            # Get current file priority
            files = qb_client.torrents_files(torrent_hash=torrent_hash)
            if file_index < len(files):
                file = files[file_index]
                new_priority = 0 if file.priority > 0 else 1
                
                # Set file priority
                qb_client.torrents_file_priority(
                    torrent_hash=torrent_hash,
                    file_ids=[file_index],
                    priority=new_priority
                )
                
                await callback_query.answer(
                    f"{'✅ Selected' if new_priority > 0 else '⬜ Deselected'}: {file.name[:30]}"
                )
                
                # Refresh the message
                await callback_query.message.delete()
                await qb_select_cmd(client, callback_query.message.reply_to_message or callback_query.message)
                
        except Exception as e:
            await callback_query.answer(f"Error: {e}", show_alert=True)


# ══════════════════════════════════════════════════════════
# INITIALIZATION
# ══════════════════════════════════════════════════════════

logger.info("✅ qBittorrent plugin loaded")
