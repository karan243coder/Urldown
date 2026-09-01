import os
import asyncio
import logging
import time
from typing import Optional, Dict
try:
    import libtorrent as lt
    LIBTORRENT_AVAILABLE = True
except ImportError:
    lt = None
    LIBTORRENT_AVAILABLE = False
from helper_funcs.display_progress import register_task, update_task, set_user_message, update_user_progress

logger = logging.getLogger(__name__)

class TorrentManager:
    def __init__(self):
        self.session = None
        self.active_torrents = {}
        self._init_session()
    
    def _init_session(self):
        """Initialize libtorrent session."""
        self.session = None
        if not LIBTORRENT_AVAILABLE:
            logger.warning("libtorrent not available — torrent download disabled")
            return
        try:
            self.session = lt.session()
            try:
                self.session.listen_on(6881, 6891)
            except Exception:
                pass
            try:
                self.session.add_extension("ut_metadata")
            except Exception:
                pass
            try:
                self.session.set_alert_mask(
                    lt.alert.category_t.status_notification |
                    lt.alert.category_t.error_notification |
                    lt.alert.category_t.storage_notification
                )
            except Exception:
                pass

            settings = {
                'user_agent': 'BIMBO Bot',
                'download_rate_limit': 0,
                'upload_rate_limit': 0,
                'enable_dht': True,
                'enable_lsd': True,
                'enable_natpmp': True,
                'enable_upnp': True,
                'connections_limit': 200,
                'max_peerlist_size': 500,
                'active_downloads': 3,
                'active_seeds': 2,
                'active_limit': 5,
                'announce_to_all_trackers': True,
                'announce_to_all_tiers': True,
                'prefer_udp_trackers': True,
            }
            applied = 0
            for k, v in settings.items():
                try:
                    self.session.apply_settings({k: v})
                    applied += 1
                except Exception as _e:
                    logger.debug(f"libtorrent skip {k}: {_e}")
            logger.info(f"Torrent session initialized ({applied} settings)")
        except Exception as e:
            logger.error(f"Failed to init torrent session: {e}")
            self.session = None
    
    def add_trackers(self, handle):
        """Add public trackers to improve peer discovery"""
        trackers = [
            'udp://tracker.opentrackr.org:1337/announce',
            'udp://open.demonii.com:1337/announce',
            'udp://tracker.openbittorrent.com:80',
            'udp://exodus.desync.com:6969',
            'udp://tracker.coppersurfer.tk:6969',
            'udp://tracker.leechers-paradise.org:6969',
            'udp://9.rarbg.to:2710/announce',
            'udp://9.rarbg.me:2710/announce',
            'http://tracker3.itzmx.com:6961/announce',
            'http://tracker1.itzmx.com:8080/announce',
            'udp://tracker.internetwarriors.net:1337',
            'udp://tracker.cyberia.is:6969/announce',
            'udp://retracker.lanta-net.ru:2710/announce',
            'udp://ipv4.tracker.harry.lu:80/announce',
            'udp://tracker.torrent.eu.org:451/announce',
            'udp://tracker.tiny-vps.com:6969/announce',
            'udp://tracker.moeking.me:6969/announce',
            'udp://tracker.army:6969/announce',
            'http://pow7.com:80/announce',
            'http://tracker2.itzmx.com:6961/announce',
            'udp://opentor.org:2710',
            'udp://tracker.ds.is:6969/announce',
            'udp://valakas.rollo.dnsabr.com:2710/announce',
            'udp://open.stealth.si:80/announce',
            'udp://tracker.birkenwald.de:6969/announce',
        ]
        
        try:
            for tracker in trackers:
                handle.add_tracker({'url': tracker, 'tier': 0})
        except Exception:
            pass  # Silent fail
    
    async def add_torrent(self, magnet_uri: str = None, torrent_file: str = None,
                         save_path: str = './downloads', progress_callback=None, user_id: int = 0) -> Optional[str]:
        """Add torrent from magnet URI or .torrent file"""
        
        if not self.session:
            logger.error("Torrent session not initialized")
            return None
        
        try:
            # Ensure save path exists
            os.makedirs(save_path, exist_ok=True)
            
            params = {
                'save_path': save_path,
                'storage_mode': lt.storage_mode_t.storage_mode_sparse,
            }
            
            if magnet_uri:
                # Validate it's actually a magnet link
                if not magnet_uri.startswith('magnet:'):
                    logger.error(f"Invalid magnet URI (must start with magnet:): {magnet_uri[:50]}...")
                    return None
                
                # Parse magnet URI
                try:
                    params['url'] = magnet_uri
                    logger.info(f"Adding magnet: {magnet_uri[:100]}...")
                except Exception as e:
                    logger.error(f"Failed to parse magnet URI: {e}")
                    return None
                    
            elif torrent_file:
                if not os.path.exists(torrent_file):
                    logger.error(f"Torrent file not found: {torrent_file}")
                    return None
                
                try:
                    with open(torrent_file, 'rb') as f:
                        torrent_data = lt.bdecode(f.read())
                    
                    if not torrent_data:
                        logger.error("Failed to decode torrent file")
                        return None
                    
                    info = lt.torrent_info(torrent_data)
                    params['ti'] = info
                    logger.info(f"Adding torrent file: {info.name()}")
                except Exception as e:
                    logger.error(f"Failed to read torrent file: {e}")
                    return None
            else:
                logger.error("No magnet URI or torrent file provided")
                return None
            
            # Add torrent to session
            try:
                handle = self.session.add_torrent(params)
            except Exception as e:
                logger.error(f"Failed to add torrent to session: {e}")
                return None
            
            # Wait a bit for torrent to initialize
            await asyncio.sleep(2)
            
            # Check if torrent was added successfully
            if not handle.is_valid():
                logger.error("Torrent handle is not valid")
                return None
            
            # Add public trackers for better peer discovery
            self.add_trackers(handle)
            
            # Get torrent info
            info_hash = str(handle.info_hash())
            logger.info(f"Torrent added successfully: {info_hash}")
            
            # Store in active torrents
            self.active_torrents[info_hash] = {
                'handle': handle,
                'progress_callback': progress_callback,
                'save_path': save_path,
                'user_id': user_id,
                'start_time': time.time()
            }
            
            # Resume torrent
            try:
                handle.resume()
                logger.info(f"Torrent resumed: {info_hash}")
            except Exception as e:
                logger.error(f"Failed to resume torrent: {e}")
            
            # Start monitoring in background
            asyncio.create_task(self._monitor_torrent(info_hash, user_id))
            
            return info_hash
        
        except Exception as e:
            logger.error(f"Add torrent error: {e}", exc_info=True)
            return None
    
    async def _monitor_torrent(self, info_hash: str, user_id: int = 0):
        """Monitor torrent progress with unified progress tracker"""
        
        if info_hash not in self.active_torrents:
            return
        
        torrent_data = self.active_torrents[info_hash]
        handle = torrent_data['handle']
        callback = torrent_data.get('progress_callback')
        
        # Register task in unified progress tracker
        task_id = f"torrent_{info_hash}"
        filename = "Fetching metadata..."
        register_task(task_id, user_id, filename, 0, 'download', 'libtorrent')
        
        try:
            check_count = 0
            while info_hash in self.active_torrents:
                try:
                    status = handle.status()
                    check_count += 1
                    
                    # Log status every 30 checks (less verbose)
                    if check_count % 30 == 0:
                        logger.info(f"Torrent {info_hash[:8]}: {self._get_state_name(status.state)} - {status.progress * 100:.1f}%")
                    
                    # Update filename when metadata is available
                    if status.has_metadata and filename == "Fetching metadata...":
                        filename = status.name
                        # Re-register with correct filename
                        register_task(task_id, user_id, filename, status.total_wanted, 'download', 'libtorrent')
                    
                    # Update unified progress tracker
                    update_task(
                        task_id,
                        status.total_wanted_done,
                        status.total_wanted,
                        status.download_rate,
                        'downloading' if status.state == lt.torrent_status.downloading else self._get_state_name(status.state),
                        'libtorrent'
                    )
                    
                    # Update user progress message
                    if user_id > 0:
                        await update_user_progress(None, user_id)
                    
                    # Call progress callback (for backward compatibility)
                    if callback:
                        progress_data = {
                            'info_hash': info_hash,
                            'name': status.name if status.has_metadata else 'Fetching metadata...',
                            'progress': status.progress * 100,
                            'download_rate': status.download_rate,
                            'upload_rate': status.upload_rate,
                            'total_size': status.total_wanted,
                            'downloaded': status.total_wanted_done,
                            'uploaded': status.total_payload_upload,
                            'num_peers': status.num_peers,
                            'num_seeds': status.num_seeds,
                            'state': self._get_state_name(status.state),
                            'is_finished': status.is_seeding or (status.progress == 1.0 and status.has_metadata)
                        }
                        
                        try:
                            await callback(progress_data)
                        except Exception as e:
                            pass  # Silent fail
                    
                    # Check if finished
                    if status.is_seeding or (status.progress >= 1.0 and status.has_metadata):
                        logger.info(f"Torrent completed: {info_hash[:8]}")
                        
                        # Update task as completed
                        update_task(task_id, status.total_wanted, status.total_wanted, 0, 'completed', 'libtorrent')
                        
                        # Get downloaded files
                        if status.has_metadata:
                            torrent_info = handle.torrent_file()
                            files = []
                            
                            try:
                                # Try libtorrent 2.x API
                                file_storage = torrent_info.files()
                                for i in range(torrent_info.num_files()):
                                    try:
                                        file_path = os.path.join(
                                            torrent_data['save_path'],
                                            file_storage.file_path(i)
                                        )
                                    except Exception:
                                        # Fallback
                                        file_path = os.path.join(
                                            torrent_data['save_path'],
                                            f"file_{i}"
                                        )
                                    
                                    files.append({
                                        'path': file_path,
                                        'size': torrent_info.file_size(i)
                                    })
                            except Exception:
                                # Fallback: try to find files in save path
                                for root, dirs, filenames in os.walk(torrent_data['save_path']):
                                    for fname in filenames:
                                        fpath = os.path.join(root, fname)
                                        files.append({
                                            'path': fpath,
                                            'size': os.path.getsize(fpath)
                                        })
                            
                            # Store files in torrent_data
                            torrent_data['files'] = files
                            
                            # Call callback with completion
                            if callback:
                                try:
                                    await callback({
                                        'info_hash': info_hash,
                                        'name': status.name,
                                        'progress': 100,
                                        'is_finished': True,
                                        'files': files
                                    })
                                except Exception:
                                    pass  # Silent fail
                        
                        break
                    
                    await asyncio.sleep(2)  # Check every 2 seconds instead of 1
                    
                except Exception as e:
                    await asyncio.sleep(3)
        
        except Exception:
            pass  # Silent fail
    
    def _get_state_name(self, state) -> str:
        """Get state name"""
        states = {
            lt.torrent_status.checking_files: 'Checking',
            lt.torrent_status.downloading_metadata: 'Fetching metadata',
            lt.torrent_status.downloading: 'Downloading',
            lt.torrent_status.finished: 'Finished',
            lt.torrent_status.seeding: 'Seeding',
            lt.torrent_status.allocating: 'Allocating',
            lt.torrent_status.checking_resume_data: 'Checking resume data'
        }
        return states.get(state, 'Unknown')
    
    async def pause_torrent(self, info_hash: str) -> bool:
        """Pause torrent"""
        if info_hash in self.active_torrents:
            try:
                handle = self.active_torrents[info_hash]['handle']
                handle.pause()
                logger.info(f"Torrent paused: {info_hash}")
                return True
            except Exception as e:
                logger.error(f"Pause torrent error: {e}")
        return False
    
    async def resume_torrent(self, info_hash: str) -> bool:
        """Resume torrent"""
        if info_hash in self.active_torrents:
            try:
                handle = self.active_torrents[info_hash]['handle']
                handle.resume()
                logger.info(f"Torrent resumed: {info_hash}")
                return True
            except Exception as e:
                logger.error(f"Resume torrent error: {e}")
        return False
    
    async def remove_torrent(self, info_hash: str, delete_files: bool = False) -> bool:
        """Remove torrent"""
        if info_hash in self.active_torrents:
            try:
                handle = self.active_torrents[info_hash]['handle']
                
                # Remove from session
                self.session.remove_torrent(handle, 
                    lt.session.delete_files if delete_files else 0)
                
                # Remove from active torrents
                del self.active_torrents[info_hash]
                
                logger.info(f"Torrent removed: {info_hash}")
                return True
            except Exception as e:
                logger.error(f"Remove torrent error: {e}")
        return False
    
    async def get_torrent_status(self, info_hash: str) -> Optional[Dict]:
        """Get torrent status"""
        if info_hash not in self.active_torrents:
            return None
        
        try:
            handle = self.active_torrents[info_hash]['handle']
            status = handle.status()
            
            return {
                'info_hash': info_hash,
                'name': status.name if status.has_metadata else 'Fetching metadata...',
                'progress': status.progress * 100,
                'download_rate': status.download_rate,
                'upload_rate': status.upload_rate,
                'total_size': status.total_wanted,
                'downloaded': status.total_wanted_done,
                'uploaded': status.total_payload_upload,
                'num_peers': status.num_peers,
                'num_seeds': status.num_seeds,
                'state': self._get_state_name(status.state),
                'is_finished': status.is_seeding or (status.progress == 1.0 and status.has_metadata)
            }
        except Exception as e:
            logger.error(f"Get torrent status error: {e}")
            return None
    
    async def get_all_torrents(self) -> Dict:
        """Get all active torrents"""
        torrents = {}
        
        for info_hash in self.active_torrents:
            status = await self.get_torrent_status(info_hash)
            if status:
                torrents[info_hash] = status
        
        return torrents
    
    def get_session_stats(self) -> Dict:
        """Get session statistics"""
        if not self.session:
            return {}
        
        try:
            stats = self.session.status()
            
            return {
                'download_rate': stats.download_rate,
                'upload_rate': stats.upload_rate,
                'total_download': stats.total_download,
                'total_upload': stats.total_upload,
                'num_peers': stats.num_peers,
                'dht_nodes': stats.dht_nodes,
                'active_torrents': len(self.active_torrents)
            }
        except Exception as e:
            logger.error(f"Get session stats error: {e}")
            return {}


# Global instance
torrent_manager = TorrentManager()

# Convenience functions
async def add_torrent(magnet_uri: str = None, torrent_file: str = None, **kwargs) -> Optional[str]:
    """Add torrent"""
    return await torrent_manager.add_torrent(magnet_uri, torrent_file, **kwargs)

async def pause_torrent(info_hash: str) -> bool:
    """Pause torrent"""
    return await torrent_manager.pause_torrent(info_hash)

async def resume_torrent(info_hash: str) -> bool:
    """Resume torrent"""
    return await torrent_manager.resume_torrent(info_hash)

async def remove_torrent(info_hash: str, **kwargs) -> bool:
    """Remove torrent"""
    return await torrent_manager.remove_torrent(info_hash, **kwargs)

async def get_torrent_status(info_hash: str) -> Optional[Dict]:
    """Get torrent status"""
    return await torrent_manager.get_torrent_status(info_hash)

async def get_all_torrents() -> Dict:
    """Get all torrents"""
    return await torrent_manager.get_all_torrents()

def get_torrent_stats() -> Dict:
    """Get torrent stats"""
    return torrent_manager.get_session_stats()
