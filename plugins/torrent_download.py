# BIMBO v4.0 — Torrent/Magnet Download (aria2c + libtorrent)
# Fully integrated with BIMBO unified progress dashboard (2-task system)
# Download task → Upload task in SAME dashboard card

import os
import re
import asyncio
import logging
import time
import shutil
from urllib.parse import urlparse

from pyrogram import filters, Client
from pyrogram.types import Message
from config import Config, BIMBO_DOWNLOAD_LOCATION
from database.adduser import AddUser

from helper_funcs.display_progress import (
    register_task, update_task, remove_task, get_task,
    set_task_stage, set_user_message,
    get_user_message, claim_user_progress_message,
    update_user_progress, finalize_user_progress,
    humanbytes, format_time, format_speed, build_advanced_bar,
    is_task_cancelled, prune_stalled_tasks, reset_idle_dashboard,
    get_user_active_tasks,
)
from plugins.media_pipeline import stage_slot

logger = logging.getLogger(__name__)


async def _get_user_settings(user_id):
    """Get user's pro settings (delete_source, delete_after_upload, notify_complete)"""
    defaults = {
        "delete_source": False,
        "delete_after_upload": True,
        "notify_complete": True,
    }
    try:
        from plugins.pro_settings import _all_settings
        s = await _all_settings(user_id)
        for k in defaults:
            if k in s:
                defaults[k] = s[k]
    except Exception:
        pass
    return defaults

# ──────────────────────────────────────────────────────────
# Libtorrent fallback
# ──────────────────────────────────────────────────────────
try:
    import libtorrent as lt
    LIBTORRENT_AVAILABLE = True
except ImportError:
    lt = None
    LIBTORRENT_AVAILABLE = False

# ──────────────────────────────────────────────────────────
# Aria2c XMLRPC connection
# ──────────────────────────────────────────────────────────
import xmlrpc.client

ARIA2_URI = "http://localhost:6800/jsonrpc"
ARIA2_SECRET = ""

# If aria2c fails once for torrents, skip it next time
_aria2_broken_for_torrents = False


def get_aria2_client():
    """Get aria2c RPC client"""
    try:
        server = xmlrpc.client.ServerProxy(ARIA2_URI, allow_none=True)
        logger.debug("Aria2 RPC proxy created for torrent")
        return server
    except Exception as e:
        logger.debug(f"Aria2 proxy creation failed: {e}")
        return None


def test_aria2_working(server):
    """Test if aria2c is actually responding"""
    for attempt in range(2):
        try:
            ver = server.aria2.getGlobalStat(ARIA2_SECRET)
            logger.info(f"✅ Aria2c working: {ver}")
            return True
        except Exception:
            try:
                ver = server.aria2.getGlobalStat("")
                return True
            except Exception as e2:
                if attempt == 0:
                    time.sleep(1)
                    continue
                logger.debug(f"aria2 test failed: {e2}")
                return False
    return False


# ──────────────────────────────────────────────────────────
# Link detection
# ──────────────────────────────────────────────────────────
def is_torrent_link(url: str) -> bool:
    """Check if URL is a torrent or magnet link"""
    url = url.strip()
    if url.startswith('magnet:'):
        return True
    if url.endswith('.torrent'):
        return True
    torrent_domains = [
        'thepiratebay', '1337x', 'rarbg', 'yts', 'eztv',
        'torrentz', 'limetorrents', 'torlock', 'demonoid'
    ]
    try:
        domain = urlparse(url).netloc.lower()
        return any(t in domain for t in torrent_domains)
    except Exception:
        return False


# ──────────────────────────────────────────────────────────
# Common tracker list
# ──────────────────────────────────────────────────────────
TRACKERS = (
    'udp://tracker.opentrackr.org:1337/announce,'
    'udp://open.demonii.com:1337/announce,'
    'udp://tracker.openbittorrent.com:80,'
    'udp://exodus.desync.com:6969,'
    'udp://tracker.coppersurfer.tk:6969,'
    'udp://tracker.leechers-paradise.org:6969,'
    'udp://9.rarbg.to:2710/announce,'
    'udp://tracker.internetwarriors.net:1337,'
    'udp://tracker.torrent.eu.org:451/announce,'
    'udp://tracker.tiny-vps.com:6969/announce,'
    'udp://opentor.org:2710,'
    'udp://tracker.ds.is:6969/announce,'
    'udp://open.stealth.si:80/announce'
)


# ──────────────────────────────────────────────────────────
# Download via aria2c (PRIMARY)
# ──────────────────────────────────────────────────────────
async def _download_torrent_aria2(url, download_path, task_id, user_id, client):
    """Download torrent/magnet using aria2c. Returns result dict or None."""
    global _aria2_broken_for_torrents

    if _aria2_broken_for_torrents:
        return None

    server = get_aria2_client()
    if not server:
        return None

    if not test_aria2_working(server):
        _aria2_broken_for_torrents = True
        logger.info("aria2c not responding for torrents — will use libtorrent directly next time")
        return None

    os.makedirs(download_path, exist_ok=True)

    options = {
        'dir': download_path,
        'max-connection-per-server': '16',
        'split': '16',
        'min-split-size': '10M',
        'continue': 'true',
        'allow-overwrite': 'true',
        'auto-file-renaming': 'false',
        'file-allocation': 'none',
        'bt-max-peers': '100',
        'bt-stop-timeout': '300',
        'seed-ratio': '0',
        'seed-time': '0',
        'follow-torrent': 'true',
        'bt-tracker': TRACKERS,
        'enable-dht': 'true',
        'enable-peer-exchange': 'true',
    }

    gid = None
    is_magnet = url.strip().startswith('magnet:')

    try:
        if is_magnet:
            logger.info("🧲 Adding magnet to aria2c...")
            await asyncio.to_thread(
                server.aria2.addUri, ARIA2_SECRET, [url.strip()], options
            )
            # Find our GID
            for _ in range(15):
                active = server.aria2.tellActive(ARIA2_SECRET, ['gid', 'bittorrent'])
                waiting = server.aria2.tellWaiting(ARIA2_SECRET, -10, 10, ['gid', 'bittorrent'])
                for dl in (active + waiting):
                    gid = dl.get('gid')
                    if gid:
                        break
                if gid:
                    break
                await asyncio.sleep(2)
        elif url.strip().endswith('.torrent'):
            import requests
            resp = await asyncio.to_thread(requests.get, url.strip(), timeout=30)
            if resp.status_code != 200:
                return {'success': False, 'error': f'HTTP {resp.status_code}'}
            torrent_path = os.path.join(download_path, '_temp.torrent')
            with open(torrent_path, 'wb') as f:
                f.write(resp.content)
            gid = await asyncio.to_thread(
                server.aria2.addTorrent, ARIA2_SECRET, torrent_path, [], options
            )
            try:
                os.remove(torrent_path)
            except Exception:
                pass
        else:
            import requests
            resp = await asyncio.to_thread(requests.get, url.strip(), timeout=30)
            if resp.status_code != 200:
                return {'success': False, 'error': f'HTTP {resp.status_code}'}
            torrent_path = os.path.join(download_path, '_temp.torrent')
            with open(torrent_path, 'wb') as f:
                f.write(resp.content)
            gid = await asyncio.to_thread(
                server.aria2.addTorrent, ARIA2_SECRET, torrent_path, [], options
            )
            try:
                os.remove(torrent_path)
            except Exception:
                pass

        if not gid:
            return {'success': False, 'error': 'Could not get GID from aria2c'}

        logger.info(f"✅ Torrent added to aria2c: GID={gid}")

        # ── Progress loop ──
        filename = "Fetching metadata..."
        total_size = 0
        metadata_wait = 0
        max_metadata_wait = 180

        last_progress_at = time.time()
        last_completed = -1
        stall_limit = int(getattr(Config, "BIMBO_STALL_TIMEOUT", 360) or 360)
        while True:
            if is_task_cancelled(task_id):
                try:
                    server.aria2.forceRemove(ARIA2_SECRET, gid)
                except Exception:
                    pass
                return {'success': False, 'error': f'Dead torrent — no progress for {stall_limit // 60} min'}
            try:
                status = await asyncio.to_thread(
                    server.aria2.tellStatus, ARIA2_SECRET, gid,
                    ['gid', 'status', 'totalLength', 'completedLength',
                     'downloadSpeed', 'uploadSpeed', 'connections',
                     'dir', 'files', 'bittorrent', 'errorCode',
                     'errorMessage', 'numSeeders']
                )
            except Exception:
                await asyncio.sleep(3)
                continue

            cur = status.get('status', '')
            completed = int(status.get('completedLength', 0))
            total = int(status.get('totalLength', 0))
            speed = int(status.get('downloadSpeed', 0))
            connections = int(status.get('connections', 0))
            seeders = status.get('numSeeders', '0')

            # Update filename
            bt = status.get('bittorrent', {})
            if bt and bt.get('info', {}).get('name'):
                filename = bt['info']['name']
            files = status.get('files', [])
            if files and filename == "Fetching metadata...":
                for f in files:
                    p = f.get('path', '')
                    if p:
                        filename = os.path.basename(p)
                        break

            # Update dashboard task
            if total > 0:
                update_task(task_id, completed, total, speed, 'downloading', 'aria2')
                total_size = total
            else:
                update_task(task_id, 0, 0, 0, 'downloading', 'aria2')
                # Show peers info in detail
                update_task(task_id, 0, 0, 0, status='downloading')
                task = get_task(task_id)
                if task:
                    task['detail'] = f"Peers: {connections} | Seeds: {seeders}"

            await update_user_progress(client, user_id)

            # Metadata timeout
            if total == 0:
                metadata_wait += 3
                if metadata_wait > max_metadata_wait:
                    try:
                        server.aria2.forceRemove(ARIA2_SECRET, gid)
                    except Exception:
                        pass
                    return {'success': False, 'error': 'Metadata timeout — no peers'}

            if cur == 'complete':
                update_task(task_id, total, total, 0, 'completed', 'aria2')
                # Find file
                if files:
                    file_path = files[0].get('path', download_path) if len(files) == 1 else download_path
                else:
                    found = []
                    for root, dirs, fnames in os.walk(download_path):
                        dirs[:] = [d for d in dirs if not d.startswith('.')]
                        for fn in fnames:
                            if not fn.startswith('.'):
                                found.append(os.path.join(root, fn))
                    file_path = found[0] if len(found) == 1 else download_path
                return {
                    'success': True, 'file_path': file_path,
                    'file_name': filename, 'size': total_size, 'engine': 'aria2c'
                }

            if cur == 'error':
                return {'success': False, 'error': status.get('errorMessage', 'Aria2 error')}
            if cur == 'removed':
                return {'success': False, 'error': 'Download removed'}

            await asyncio.sleep(3)

    except Exception as e:
        logger.error(f"Torrent aria2 error: {e}", exc_info=True)
        return {'success': False, 'error': str(e)}


# ──────────────────────────────────────────────────────────
# Download via libtorrent (FALLBACK)
# ──────────────────────────────────────────────────────────
async def _download_torrent_libtorrent(url, download_path, task_id, user_id, client):
    """Download using libtorrent. Returns result dict."""
    if not LIBTORRENT_AVAILABLE:
        return {'success': False, 'error': 'libtorrent not installed'}

    try:
        session = lt.session({
            'user_agent': 'BIMBO-Bot/1.0',
            'listen_interfaces': '0.0.0.0:6881,[::]:6881',
            'download_rate_limit': 0,
            'upload_rate_limit': 0,
            'connections_limit': 200,
            'alert_mask': lt.alert.category_t.status_notification | lt.alert.category_t.error_notification,
        })
        try:
            session.add_dht_router('router.bittorrent.com', 6881)
            session.add_dht_router('router.utorrent.com', 6881)
            session.add_dht_router('dht.transmissionbt.com', 6881)
        except Exception:
            pass

        os.makedirs(download_path, exist_ok=True)

        # Parse magnet or torrent file
        if url.startswith('magnet:'):
            try:
                params = lt.parse_magnet_uri(url)
                params.save_path = download_path
                handle = session.add_torrent(params)
            except AttributeError:
                handle = lt.add_magnet_uri(session, url, {'save_path': download_path})
        elif url.strip().endswith('.torrent'):
            import requests
            response = await asyncio.to_thread(requests.get, url.strip(), timeout=30)
            torrent_data = lt.bdecode(response.content)
            info = lt.torrent_info(torrent_data)
            handle = session.add_torrent({'ti': info, 'save_path': download_path})
        else:
            import requests
            response = await asyncio.to_thread(requests.get, url.strip(), timeout=30)
            torrent_data = lt.bdecode(response.content)
            info = lt.torrent_info(torrent_data)
            handle = session.add_torrent({'ti': info, 'save_path': download_path})

        # Extra trackers
        for tracker in TRACKERS.split(','):
            tracker = tracker.strip()
            if tracker:
                try:
                    handle.add_tracker({'url': tracker, 'tier': 0})
                except Exception:
                    pass

        # Wait for metadata
        logger.info("Torrent (libtorrent): Waiting for metadata...")
        metadata_wait = 0
        while not handle.has_metadata() and metadata_wait < 120:
            await asyncio.sleep(1)
            metadata_wait += 1
            s = handle.status()
            task = get_task(task_id)
            if task:
                task['detail'] = f"Finding peers... {120 - metadata_wait}s | Peers: {s.num_peers}"
            await update_user_progress(client, user_id)

        if not handle.has_metadata():
            return {'success': False, 'error': 'Metadata timeout — no peers (libtorrent)'}

        torrent_info = handle.torrent_file()
        file_name = torrent_info.name()
        total_size = torrent_info.total_size()
        logger.info(f"Torrent (libtorrent): {file_name} ({total_size / (1024*1024):.1f} MB)")

        # Update task with real name + size
        update_task(task_id, 0, total_size, 0, 'downloading', 'libtorrent')
        task = get_task(task_id)
        if task:
            task['filename'] = file_name
        await update_user_progress(client, user_id, force=True)

        # Download with progress
        last_done = -1
        last_progress_at = time.time()
        stall_limit = int(getattr(Config, "BIMBO_STALL_TIMEOUT", 360) or 360)
        while not handle.is_seed():
            if is_task_cancelled(task_id):
                return {'success': False, 'error': f'Dead torrent — no progress for {stall_limit // 60} min'}
            status = handle.status()
            downloaded = status.total_done
            speed = status.download_rate
            connections = status.num_peers
            seeders = status.num_seeds
            if downloaded > last_done:
                last_done = downloaded
                last_progress_at = time.time()
            elif time.time() - last_progress_at >= stall_limit:
                return {'success': False, 'error': f'Dead torrent — no progress for {stall_limit // 60} min'}

            update_task(task_id, downloaded, total_size, speed, 'downloading', 'libtorrent')
            task = get_task(task_id)
            if task:
                task['detail'] = f"Peers: {connections} | Seeds: {seeders}"

            await update_user_progress(client, user_id)
            await asyncio.sleep(2)

        file_path = os.path.join(download_path, file_name)
        update_task(task_id, total_size, total_size, 0, 'completed', 'libtorrent')
        return {
            'success': True, 'file_path': file_path,
            'file_name': file_name, 'size': total_size, 'engine': 'libtorrent'
        }

    except Exception as e:
        logger.error(f"libtorrent download error: {e}", exc_info=True)
        return {'success': False, 'error': str(e)}


# ──────────────────────────────────────────────────────────
# Upload to Telegram with progress tracking
# ──────────────────────────────────────────────────────────
async def _upload_to_telegram(client, chat_id, file_path, filename, file_size,
                               upload_task_id, user_id, progress_msg):
    """Upload file(s) to Telegram with BIMBO dashboard progress."""

    async def _pyro_progress(current, total):
        """Progress callback for Pyrogram upload — feeds BIMBO dashboard."""
        update_task(upload_task_id, current, total, 0, 'uploading', 'pyrogram')
        await update_user_progress(client, user_id)

    if os.path.isdir(file_path):
        uploaded = 0
        files_list = []
        for root, dirs, files in os.walk(file_path):
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            for f in files:
                if not f.startswith('.'):
                    files_list.append(os.path.join(root, f))

        total_files = len(files_list)
        for idx, fpath in enumerate(files_list, 1):
            fname = os.path.basename(fpath)
            fsize = os.path.getsize(fpath)
            ext = os.path.splitext(fname)[1].lower()

            # Update task for each file
            update_task(upload_task_id, 0, fsize, 0, 'uploading', 'pyrogram')
            task = get_task(upload_task_id)
            if task:
                task['filename'] = fname
                task['detail'] = f"File {idx}/{total_files}"
            await update_user_progress(client, user_id, force=True)

            try:
                if ext in ['.mp4', '.mkv', '.webm', '.avi', '.mov', '.flv', '.m4v']:
                    await client.send_video(
                        chat_id=chat_id, video=fpath,
                        caption=f"🧲 {fname}\n✅ BIMBO Bot",
                        supports_streaming=True,
                        progress=_pyro_progress
                    )
                elif ext in ['.mp3', '.m4a', '.wav', '.flac', '.ogg', '.aac']:
                    await client.send_audio(
                        chat_id=chat_id, audio=fpath,
                        caption=f"🧲 {fname}\n✅ BIMBO Bot",
                        progress=_pyro_progress
                    )
                else:
                    await client.send_document(
                        chat_id=chat_id, document=fpath,
                        caption=f"🧲 {fname}\n✅ BIMBO Bot",
                        progress=_pyro_progress
                    )
                uploaded += 1
            except Exception as e:
                logger.error(f"Upload error for {fname}: {e}")
                try:
                    await client.send_document(
                        chat_id=chat_id, document=fpath,
                        caption=f"🧲 {fname}\n✅ BIMBO Bot",
                        progress=_pyro_progress
                    )
                    uploaded += 1
                except Exception as e2:
                    logger.error(f"Document upload also failed: {e2}")

        return uploaded
    else:
        # Single file
        ext = os.path.splitext(file_path)[1].lower()
        update_task(upload_task_id, 0, file_size, 0, 'uploading', 'pyrogram')
        task = get_task(upload_task_id)
        if task:
            task['filename'] = filename
        await update_user_progress(client, user_id, force=True)

        try:
            if ext in ['.mp4', '.mkv', '.webm', '.avi', '.mov', '.flv', '.m4v']:
                await client.send_video(
                    chat_id=chat_id, video=file_path,
                    caption=f"🧲 {filename}\n✅ BIMBO Bot",
                    supports_streaming=True,
                    progress=_pyro_progress
                )
            elif ext in ['.mp3', '.m4a', '.wav', '.flac', '.ogg', '.aac']:
                await client.send_audio(
                    chat_id=chat_id, audio=file_path,
                    caption=f"🧲 {filename}\n✅ BIMBO Bot",
                    progress=_pyro_progress
                )
            else:
                await client.send_document(
                    chat_id=chat_id, document=file_path,
                    caption=f"🧲 {filename}\n✅ BIMBO Bot",
                    progress=_pyro_progress
                )
            return 1
        except Exception as e:
            logger.error(f"Single file upload error: {e}")
            try:
                await client.send_document(
                    chat_id=chat_id, document=file_path,
                    caption=f"🧲 {filename}\n✅ BIMBO Bot",
                    progress=_pyro_progress
                )
                return 1
            except Exception as e2:
                logger.error(f"Document fallback failed: {e2}")
                return 0


# ──────────────────────────────────────────────────────────
# MAIN HANDLER — magnet links + .torrent URLs
# ──────────────────────────────────────────────────────────
@Client.on_message(filters.private & filters.regex(r'(?i)^magnet:\?|^https?://.*\.torrent'))
async def handle_torrent(client: Client, message: Message):
    """Handle torrent/magnet links — full BIMBO dashboard integration (2-task system)"""
    await AddUser(client, message)

    url = message.text.strip()
    if not is_torrent_link(url):
        return

    user_id = message.from_user.id
    download_path = os.path.join(BIMBO_DOWNLOAD_LOCATION, f"torrent_{user_id}_{int(time.time())}")

    # Get user's pro settings
    settings = await _get_user_settings(user_id)
    delete_source = settings.get('delete_source', False)
    notify_complete = settings.get('notify_complete', True)

    # ── Create the ONE canonical dashboard message ──
    display_name = "Torrent Download"
    if url.startswith('magnet:'):
        # Try to extract name from magnet
        dn_match = re.search(r'dn=([^&]+)', url)
        if dn_match:
            from urllib.parse import unquote
            display_name = unquote(dn_match.group(1))[:60]
    elif url.endswith('.torrent'):
        display_name = os.path.basename(urlparse(url).path)[:60]

    # ── Register DOWNLOAD task ──
    dl_task_id = f"torrent_dl_{user_id}_{time.time_ns()}"
    register_task(
        task_id=dl_task_id,
        user_id=user_id,
        filename=display_name,
        total_size=0,
        task_type='download',
        engine='libtorrent',
        source_url=url[:200],
    )

    # ONE canonical dashboard per user
    progress_msg = get_user_message(user_id)
    if progress_msg is None:
        candidate = await message.reply_text(
            f"🧲 **Torrent Detected**\n\n"
            f"📁 File: {display_name}\n"
            f"🔄 Status: Connecting to peers..."
        )
        progress_msg = await claim_user_progress_message(
            user_id, candidate, delete_duplicate=True
        )
    set_user_message(user_id, progress_msg)
    await update_user_progress(client, user_id, force=True)

    # Auto-delete source message if user has delete_source enabled
    if delete_source:
        try:
            await message.delete()
        except Exception:
            pass

    # ── Enter download stage slot (2 concurrent downloads for whole bot) ──
    dl_stage_ctx = stage_slot(
        "download", dl_task_id, user_id,
        site="torrent", client=client,
    )
    await dl_stage_ctx.__aenter__()

    os.makedirs(download_path, exist_ok=True)

    # ─ Try qBittorrent first if enabled ──
    qb_used = False
    if Config.QB_ENABLED:
        try:
            from plugins.qbittorrent_manager import qb_client, QB_ENABLED
            
            if QB_ENABLED and qb_client:
                logger.info("Using qBittorrent for torrent download...")
                
                # Add torrent to qBittorrent
                try:
                    qb_client.torrents_add(urls=url)
                    await asyncio.sleep(2)
                    
                    # Find the torrent
                    torrents = qb_client.torrents_info(sort='added_on', reverse=True, limit=1)
                    if torrents:
                        torrent = torrents[0]
                        torrent_hash = torrent.hash
                        
                        # Update task info
                        update_task(dl_task_id, 0, torrent.size, 0, 'downloading', 'qbittorrent')
                        task = get_task(dl_task_id)
                        if task:
                            task['filename'] = torrent.name
                        
                        # Monitor progress
                        while True:
                            torrent_info = qb_client.torrents_info(torrent_hashes=torrent_hash)
                            if not torrent_info:
                                break
                            
                            torrent = torrent_info[0]
                            downloaded = torrent.downloaded
                            total = torrent.size
                            speed = torrent.dlspeed
                            
                            update_task(dl_task_id, downloaded, total, speed, 'downloading', 'qbittorrent')
                            
                            if torrent.state in ['completed', 'pausedUP', 'uploading']:
                                update_task(dl_task_id, total, total, 0, 'completed', 'qbittorrent')
                                qb_used = True
                                break
                            
                            await asyncio.sleep(2)
                            await update_user_progress(client, user_id)
                except Exception as e:
                    logger.warning(f"qBittorrent failed: {e}")
        except Exception as e:
            logger.debug(f"qBittorrent not available: {e}")
    
    # If qBittorrent didn't work, fallback to aria2c/libtorrent
    if not qb_used:
        result = None
        try:
            # Try aria2c first
            result = await _download_torrent_aria2(url, download_path, dl_task_id, user_id, client)
            
            # Fallback to libtorrent
            if result is None or (isinstance(result, dict) and not result.get('success')):
                if LIBTORRENT_AVAILABLE:
                    err = result.get('error', 'aria2c unavailable') if result else 'aria2c returned None'
                    logger.info(f"aria2c failed ({err}), switching to libtorrent")
                    task = get_task(dl_task_id)
                    if task:
                        task['detail'] = f"Switching engine..."
                        task['engine'] = 'libtorrent'
                    await update_user_progress(client, user_id, force=True)
                    await asyncio.sleep(1)
                    
                    result = await _download_torrent_libtorrent(url, download_path, dl_task_id, user_id, client)
                else:
                    result = result or {'success': False, 'error': 'aria2c failed and libtorrent not installed'}
        except Exception as e:
            logger.error(f"Torrent download exception: {e}", exc_info=True)
            result = {'success': False, 'error': str(e)}

    # Release download slot
    await dl_stage_ctx.__aexit__(None, None, None)

    # ── Handle download failure ──
    if not result or not result.get('success'):
        error = result.get('error', 'Unknown') if result else 'Download failed'
        update_task(dl_task_id, 0, 0, 0, 'failed', 'libtorrent')
        task = get_task(dl_task_id)
        if task:
            task['error'] = error
        await update_user_progress(client, user_id, force=True)

        # Show error to user then clean up
        await asyncio.sleep(3)
        remove_task(dl_task_id)
        await finalize_user_progress(client, user_id, progress_msg)

        await message.reply_text(
            f"❌ **Torrent Download Failed**\n\n"
            f"Error: `{error[:300]}`\n\n"
            f"💡 **Tips:**\n"
            f"• Torrent dead ho sakta hai (no seeders)\n"
            f"• Koyeb/Heroku pe DHT limited hai\n"
            f"• `/ts` se active torrent search karo"
        )
        shutil.rmtree(download_path, ignore_errors=True)
        return

    # ── DOWNLOAD COMPLETE → Transition to UPLOAD task ──
    engine_name = result.get('engine', 'unknown')
    file_name = result.get('file_name', display_name)
    file_size = result.get('size', 0)
    file_path = result.get('file_path', '')

    # Remove download task, register upload task (2-task flow)
    remove_task(dl_task_id)

    ul_task_id = f"torrent_ul_{user_id}_{time.time_ns()}"
    register_task(
        task_id=ul_task_id,
        user_id=user_id,
        filename=file_name,
        total_size=file_size,
        task_type='upload',
        engine='pyrogram',
    )
    update_task(ul_task_id, 0, file_size, 0, 'uploading', 'pyrogram')
    await update_user_progress(client, user_id, force=True)

    # ── Enter upload stage slot ──
    ul_stage_ctx = stage_slot(
        "upload", ul_task_id, user_id,
        site="torrent", client=client,
    )
    await ul_stage_ctx.__aenter__()

    try:
        uploaded = await _upload_to_telegram(
            client, message.chat.id, file_path, file_name, file_size,
            ul_task_id, user_id, progress_msg
        )
    except Exception as e:
        logger.error(f"Upload exception: {e}", exc_info=True)
        uploaded = 0

    # Release upload slot
    await ul_stage_ctx.__aexit__(None, None, None)

    # ── Finalize ──
    if uploaded > 0:
        update_task(ul_task_id, file_size, file_size, 0, 'completed', 'pyrogram')
        await update_user_progress(client, user_id, force=True)
        await asyncio.sleep(2)
        remove_task(ul_task_id)

        # delete_after_upload: finalize deletes the dashboard
        await finalize_user_progress(client, user_id, progress_msg,
                                     delete_if_idle=True)

        # notify_complete: send a success message
        if notify_complete:
            done_msg = await message.reply_text(
                f"✅ **Complete!**\n\n"
                f"📁 `{file_name[:50]}`\n"
                f"💾 {humanbytes(file_size)}\n"
                f"🔧 Engine: {engine_name}"
            )
            # Auto-cleaner will delete this in AUTO_DELETE_SECONDS

    else:
        update_task(ul_task_id, 0, file_size, 0, 'failed', 'pyrogram')
        task = get_task(ul_task_id)
        if task:
            task['error'] = 'Upload to Telegram failed'
        await update_user_progress(client, user_id, force=True)
        await asyncio.sleep(3)
        remove_task(ul_task_id)
        await finalize_user_progress(client, user_id, progress_msg)

    # Cleanup
    shutil.rmtree(download_path, ignore_errors=True)
    logger.info(f"🧹 Cleaned torrent download: {download_path}")


# ──────────────────────────────────────────────────────────
# HANDLER: .torrent file sent as document
# ──────────────────────────────────────────────────────────
@Client.on_message(filters.private & filters.document)
async def handle_torrent_document(client: Client, message: Message):
    """Handle .torrent file sent directly as document"""
    doc = message.document
    if not doc or not doc.file_name or not doc.file_name.lower().endswith('.torrent'):
        return

    await AddUser(client, message)
    user_id = message.from_user.id
    display_name = doc.file_name.replace('.torrent', '')[:60]

    # Get user's pro settings
    settings = await _get_user_settings(user_id)
    delete_source = settings.get('delete_source', False)
    notify_complete = settings.get('notify_complete', True)

    # Register download task
    dl_task_id = f"torrent_dl_{user_id}_{time.time_ns()}"
    register_task(
        task_id=dl_task_id,
        user_id=user_id,
        filename=display_name,
        total_size=doc.file_size,
        task_type='download',
        engine='libtorrent',
    )

    progress_msg = get_user_message(user_id)
    if progress_msg is None:
        candidate = await message.reply_text(
            f"🧲 **Torrent File**\n\n"
            f"📁 {display_name}\n"
            f"🔄 Starting..."
        )
        progress_msg = await claim_user_progress_message(
            user_id, candidate, delete_duplicate=True
        )
    set_user_message(user_id, progress_msg)
    await update_user_progress(client, user_id, force=True)

    # Auto-delete source message if user has delete_source enabled
    if delete_source:
        try:
            await message.delete()
        except Exception:
            pass

    # Download stage
    dl_stage_ctx = stage_slot("download", dl_task_id, user_id, site="torrent", client=client)
    await dl_stage_ctx.__aenter__()

    # Download .torrent file from Telegram
    temp_dir = os.path.join(BIMBO_DOWNLOAD_LOCATION, f"torrent_temp_{user_id}")
    os.makedirs(temp_dir, exist_ok=True)
    download_path = os.path.join(BIMBO_DOWNLOAD_LOCATION, f"torrent_{user_id}_{int(time.time())}")
    os.makedirs(download_path, exist_ok=True)

    try:
        torrent_path = await message.download(file_name=os.path.join(temp_dir, doc.file_name))
    except Exception as e:
        update_task(dl_task_id, 0, 0, 0, 'failed', 'libtorrent')
        task = get_task(dl_task_id)
        if task:
            task['error'] = str(e)
        await update_user_progress(client, user_id, force=True)
        await asyncio.sleep(2)
        remove_task(dl_task_id)
        await finalize_user_progress(client, user_id, progress_msg)
        shutil.rmtree(temp_dir, ignore_errors=True)
        return

    result = None
    try:
        # Try aria2c first
        global _aria2_broken_for_torrents
        if not _aria2_broken_for_torrents:
            server = get_aria2_client()
            if server and test_aria2_working(server):
                options = {
                    'dir': download_path,
                    'max-connection-per-server': '16', 'split': '16',
                    'min-split-size': '10M', 'continue': 'true',
                    'allow-overwrite': 'true',
                    'bt-max-peers': '100', 'bt-stop-timeout': '300',
                    'seed-ratio': '0', 'seed-time': '0',
                    'bt-tracker': TRACKERS,
                    'enable-dht': 'true', 'enable-peer-exchange': 'true',
                }
                try:
                    gid = await asyncio.to_thread(
                        server.aria2.addTorrent, ARIA2_SECRET, torrent_path, [], options
                    )
                    if gid:
                        # Monitor aria2c download
                        filename = display_name
                        total_size = 0
                        metadata_wait = 0
                        while True:
                            try:
                                st = await asyncio.to_thread(
                                    server.aria2.tellStatus, ARIA2_SECRET, gid,
                                    ['status', 'totalLength', 'completedLength',
                                     'downloadSpeed', 'connections', 'bittorrent',
                                     'errorCode', 'numSeeders']
                                )
                            except Exception:
                                await asyncio.sleep(3)
                                continue
                            cur = st.get('status', '')
                            completed = int(st.get('completedLength', 0))
                            total = int(st.get('totalLength', 0))
                            speed = int(st.get('downloadSpeed', 0))
                            bt = st.get('bittorrent', {})
                            if bt and bt.get('info', {}).get('name'):
                                filename = bt['info']['name']
                            if total > 0:
                                update_task(dl_task_id, completed, total, speed, 'downloading', 'aria2')
                                task = get_task(dl_task_id)
                                if task:
                                    task['filename'] = filename
                                total_size = total
                            else:
                                metadata_wait += 3
                                task = get_task(dl_task_id)
                                if task:
                                    task['detail'] = f"Peers: {st.get('connections', 0)}"
                            await update_user_progress(client, user_id)

                            if cur == 'complete':
                                found = []
                                for root, dirs, fnames in os.walk(download_path):
                                    dirs[:] = [d for d in dirs if not d.startswith('.')]
                                    for fn in fnames:
                                        if not fn.startswith('.'):
                                            found.append(os.path.join(root, fn))
                                fp = found[0] if len(found) == 1 else download_path
                                result = {
                                    'success': True, 'file_path': fp,
                                    'file_name': filename, 'size': total_size, 'engine': 'aria2c'
                                }
                                break
                            if cur == 'error':
                                result = {'success': False, 'error': st.get('errorMessage', 'Error')}
                                break
                            if total == 0 and metadata_wait > 180:
                                try:
                                    server.aria2.forceRemove(ARIA2_SECRET, gid)
                                except Exception:
                                    pass
                                result = {'success': False, 'error': 'Metadata timeout'}
                                break
                            await asyncio.sleep(3)
                except Exception as e:
                    logger.debug(f"aria2c torrent file error: {e}")

        # Fallback to libtorrent
        if result is None or (isinstance(result, dict) and not result.get('success')):
            if LIBTORRENT_AVAILABLE:
                task = get_task(dl_task_id)
                if task:
                    task['engine'] = 'libtorrent'
                    task['detail'] = "Switching engine..."
                await update_user_progress(client, user_id, force=True)

                session = lt.session({
                    'listen_interfaces': '0.0.0.0:6881,[::]:6881',
                    'alert_mask': lt.alert.category_t.status_notification | lt.alert.category_t.error_notification,
                })
                try:
                    session.add_dht_router('router.bittorrent.com', 6881)
                    session.add_dht_router('router.utorrent.com', 6881)
                except Exception:
                    pass
                with open(torrent_path, 'rb') as f:
                    torrent_data = lt.bdecode(f.read())
                info = lt.torrent_info(torrent_data)
                handle = session.add_torrent({'ti': info, 'save_path': download_path})
                handle.resume()

                # Wait for metadata
                for _ in range(60):
                    if handle.has_metadata():
                        break
                    s = handle.status()
                    task = get_task(dl_task_id)
                    if task:
                        task['detail'] = f"Peers: {s.num_peers}"
                    await update_user_progress(client, user_id)
                    await asyncio.sleep(1)

                if handle.has_metadata():
                    ti = handle.torrent_file()
                    fname = ti.name()
                    tsize = ti.total_size()
                    update_task(dl_task_id, 0, tsize, 0, 'downloading', 'libtorrent')
                    task = get_task(dl_task_id)
                    if task:
                        task['filename'] = fname
                    await update_user_progress(client, user_id, force=True)

                    while not handle.is_seed():
                        st = handle.status()
                        update_task(dl_task_id, st.total_done, tsize, st.download_rate, 'downloading', 'libtorrent')
                        task = get_task(dl_task_id)
                        if task:
                            task['detail'] = f"Peers: {st.num_peers} | Seeds: {st.num_seeds}"
                        await update_user_progress(client, user_id)
                        await asyncio.sleep(2)

                    fp = os.path.join(download_path, fname)
                    result = {
                        'success': True, 'file_path': fp,
                        'file_name': fname, 'size': tsize, 'engine': 'libtorrent'
                    }
                else:
                    result = {'success': False, 'error': 'Metadata timeout (libtorrent)'}
            else:
                result = result or {'success': False, 'error': 'aria2c failed and libtorrent not available'}
    except Exception as e:
        logger.error(f"Torrent document exception: {e}", exc_info=True)
        result = {'success': False, 'error': str(e)}

    # Release download slot
    await dl_stage_ctx.__aexit__(None, None, None)

    # Handle failure
    if not result or not result.get('success'):
        error = result.get('error', 'Unknown') if result else 'Failed'
        update_task(dl_task_id, 0, 0, 0, 'failed', 'libtorrent')
        task = get_task(dl_task_id)
        if task:
            task['error'] = error
        await update_user_progress(client, user_id, force=True)
        await asyncio.sleep(3)
        remove_task(dl_task_id)
        await finalize_user_progress(client, user_id, progress_msg)
        shutil.rmtree(download_path, ignore_errors=True)
        shutil.rmtree(temp_dir, ignore_errors=True)
        return

    # ── UPLOAD task (2-task system) ──
    file_name = result.get('file_name', display_name)
    file_size = result.get('size', 0)
    file_path = result.get('file_path', '')

    remove_task(dl_task_id)

    ul_task_id = f"torrent_ul_{user_id}_{time.time_ns()}"
    register_task(
        task_id=ul_task_id, user_id=user_id,
        filename=file_name, total_size=file_size,
        task_type='upload', engine='pyrogram',
    )
    update_task(ul_task_id, 0, file_size, 0, 'uploading', 'pyrogram')
    await update_user_progress(client, user_id, force=True)

    ul_stage_ctx = stage_slot("upload", ul_task_id, user_id, site="torrent", client=client)
    await ul_stage_ctx.__aenter__()

    try:
        uploaded = await _upload_to_telegram(
            client, message.chat.id, file_path, file_name, file_size,
            ul_task_id, user_id, progress_msg
        )
    except Exception as e:
        logger.error(f"Upload exception: {e}")
        uploaded = 0

    await ul_stage_ctx.__aexit__(None, None, None)

    if uploaded > 0:
        update_task(ul_task_id, file_size, file_size, 0, 'completed', 'pyrogram')
        await update_user_progress(client, user_id, force=True)
        await asyncio.sleep(2)
        remove_task(ul_task_id)
        await finalize_user_progress(client, user_id, progress_msg, delete_if_idle=True)

        # notify_complete
        if notify_complete:
            done_msg = await message.reply_text(
                f"✅ **Complete!**\n\n"
                f"📁 `{file_name[:50]}`\n"
                f"💾 {humanbytes(file_size)}"
            )
    else:
        update_task(ul_task_id, 0, file_size, 0, 'failed', 'pyrogram')
        task = get_task(ul_task_id)
        if task:
            task['error'] = 'Upload failed'
        await update_user_progress(client, user_id, force=True)
        await asyncio.sleep(3)
        remove_task(ul_task_id)
        await finalize_user_progress(client, user_id, progress_msg)

    # Cleanup
    shutil.rmtree(download_path, ignore_errors=True)
    shutil.rmtree(temp_dir, ignore_errors=True)
