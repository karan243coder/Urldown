import psutil
import time
from datetime import datetime, timedelta
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import hashlib
import logging
import os

logger = logging.getLogger(__name__)

class AdvancedProgress:
    def __init__(self, user_id, username=None, engine="pyrogram", mode="upload"):
        self.user_id = user_id
        self.username = username or "User"
        self.task_id = self._generate_task_id()
        self.start_time = time.time()
        self.engine = engine  # Real engine: pyrogram, aria2, libtorrent, yt-dlp, requests
        self.mode = mode      # Real mode: upload, download, leech, mirror, clone
        self.cancelled = False
        
    def _generate_task_id(self):
        """Generate unique task ID"""
        timestamp = str(time.time()).encode()
        user_bytes = str(self.user_id).encode()
        return hashlib.md5(timestamp + user_bytes).hexdigest()[:16]
    
    def _format_size(self, size_bytes):
        """Format bytes to human readable"""
        if size_bytes is None or size_bytes == 0:
            return "0B"
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if abs(size_bytes) < 1024.0:
                return f"{size_bytes:.2f}{unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.2f}PB"
    
    def _format_speed(self, speed_bytes):
        """Format speed"""
        if speed_bytes is None or speed_bytes == 0:
            return "0B/s"
        return f"{self._format_size(speed_bytes)}/s"
    
    def _format_time(self, seconds):
        """Format seconds to readable time"""
        if seconds is None or seconds < 0:
            return "∞"
        
        seconds = int(seconds)
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        
        if hours > 0:
            return f"{hours}h{minutes}m{secs}s"
        elif minutes > 0:
            return f"{minutes}m{secs}s"
        else:
            return f"{secs}s"
    
    def _get_progress_bar(self, percentage, length=13):
        """Create fancy progress bar with special characters"""
        percentage = max(0, min(100, percentage))
        filled = int(length * percentage / 100)
        
        if filled == 0:
            bar = "□" * length
        elif filled == length:
            bar = "■" * length
        else:
            bar = "■" * (filled - 1) + "▧" + "□" * (length - filled)
        
        return f"[{bar}] {percentage:.2f}%"
    
    def _get_system_stats(self):
        """Get REAL system statistics"""
        try:
            # CPU usage (real-time)
            cpu_percent = psutil.cpu_percent(interval=0.1)
            
            # Memory usage (real-time)
            memory = psutil.virtual_memory()
            ram_percent = memory.percent
            ram_used = memory.used
            ram_total = memory.total
            
            # Disk usage (real-time)
            disk = psutil.disk_usage('/')
            disk_free = disk.free
            disk_total = disk.total
            disk_used = disk.used
            disk_percent = disk.percent
            
            # Uptime
            boot_time = psutil.boot_time()
            uptime_seconds = time.time() - boot_time
            
            return {
                'cpu': cpu_percent,
                'ram': ram_percent,
                'ram_used': ram_used,
                'ram_total': ram_total,
                'disk_free': disk_free,
                'disk_total': disk_total,
                'disk_used': disk_used,
                'disk_percent': disk_percent,
                'uptime': uptime_seconds
            }
        except Exception as e:
            logger.error(f"System stats error: {e}")
            return {
                'cpu': 0, 'ram': 0, 'ram_used': 0, 'ram_total': 0,
                'disk_free': 0, 'disk_total': 0, 'disk_used': 0,
                'disk_percent': 0, 'uptime': 0
            }
    
    def _get_fancy_username(self, username):
        """Convert username to fancy Unicode font"""
        fancy_map = {
            'a': '𝔞', 'b': '𝔟', 'c': '𝔠', 'd': '𝔡', 'e': '𝔢',
            'f': '𝔣', 'g': '𝔤', 'h': '𝔥', 'i': '𝔦', 'j': '𝔧',
            'k': '𝔨', 'l': '𝔩', 'm': '𝔪', 'n': '𝔫', 'o': '𝔬',
            'p': '𝔭', 'q': '𝔮', 'r': '𝔯', 's': '𝔰', 't': '𝔱',
            'u': '𝔲', 'v': '𝔳', 'w': '𝔴', 'x': '𝔵', 'y': '𝔶',
            'z': '𝔷',
            'A': '𝔄', 'B': '𝔅', 'C': 'ℭ', 'D': '𝔇', 'E': '𝔈',
            'F': '𝔉', 'G': '𝔊', 'H': 'ℌ', 'I': 'ℑ', 'J': '𝔍',
            'K': '𝔎', 'L': '𝔏', 'M': '𝔐', 'N': '𝔑', 'O': '𝔒',
            'P': '𝔓', 'Q': '𝔔', 'R': 'ℜ', 'S': '𝔖', 'T': '𝔗',
            'U': '𝔘', 'V': '𝔙', 'W': '𝔚', 'X': '𝔛', 'Y': '𝔜',
            'Z': 'ℨ'
        }
        
        fancy_name = ""
        for char in username:
            fancy_name += fancy_map.get(char, char)
        
        return fancy_name
    
    def _get_real_engine_name(self):
        """Get real engine name with version"""
        engine_map = {
            'pyrogram': 'Pyrogram',
            'aria2': 'Aria2',
            'libtorrent': 'libtorrent',
            'yt-dlp': 'yt-dlp',
            'requests': 'Requests',
            'aiohttp': 'aiohttp',
            'ffmpeg': 'FFmpeg'
        }
        return engine_map.get(self.engine, self.engine)
    
    def _get_real_mode_name(self):
        """Get real mode name"""
        mode_map = {
            'upload': 'Upload',
            'download': 'Download',
            'leech': 'Leech',
            'mirror': 'Mirror',
            'clone': 'Clone',
            'extract': 'Extract',
            'compress': 'Compress'
        }
        return mode_map.get(self.mode, self.mode)
    
    def build_progress_message(self, 
                               filename, 
                               current, 
                               total, 
                               speed, 
                               status_msg=None,
                               message_link=None,
                               dl_speed=0,
                               ul_speed=None):
        """Build REAL advanced progress message with live stats"""
        
        # Calculate progress
        percentage = (current / total * 100) if total > 0 else 0
        
        # Calculate ETA
        elapsed = time.time() - self.start_time
        if speed > 0:
            eta = (total - current) / speed
        else:
            eta = -1
        
        # Get REAL system stats
        stats = self._get_system_stats()
        
        # Format values
        progress_bar = self._get_progress_bar(percentage)
        processed = f"{self._format_size(current)} of {self._format_size(total)}"
        speed_str = self._format_speed(speed)
        eta_str = self._format_time(eta)
        elapsed_str = self._format_time(elapsed)
        
        # Get REAL engine and mode names
        engine_name = self._get_real_engine_name()
        mode_name = self._get_real_mode_name()
        
        # Fancy username
        fancy_user = self._get_fancy_username(self.username)
        
        # Build status line
        if message_link:
            status_line = f"[{status_msg or self._get_real_mode_name()}]({message_link})"
        else:
            status_line = status_msg or self._get_real_mode_name()
        
        # Calculate upload speed if not provided
        if ul_speed is None:
            ul_speed = speed if self.mode in ['upload', 'leech'] else 0
        
        # Build REAL message with live stats
        message = f"""⌬ ***{filename}***
┃ {progress_bar}
┠ **Processed:** {processed}
┠ **Status:** {status_line} | **ETA:** {eta_str}
┠ **Speed:** {speed_str} | **Elapsed:** {elapsed_str}
┠ **Engine:** {engine_name}
┠ **Mode:** #{mode_name}
┠ **User:** {fancy_user} | **ID:** {self.user_id}
┖ /cancel_{self.task_id}

⌬ ***Bot Stats***
┠ **CPU:** {stats['cpu']:.1f}% | **F:** {self._format_size(stats['disk_free'])} [{100-stats['disk_percent']:.1f}%]
┠ **RAM:** {stats['ram']:.1f}% | **UPTIME:** {self._format_time(stats['uptime'])}
┖ **DL:** {self._format_speed(dl_speed)} | **UL:** {self._format_speed(ul_speed)}"""
        
        return message
    
    def get_cancel_button(self):
        """Get cancel button"""
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_{self.task_id}")]
        ])
    
    def get_task_id(self):
        """Get task ID for cancellation"""
        return self.task_id
    
    def cancel(self):
        """Cancel this task"""
        self.cancelled = True
    
    def is_cancelled(self):
        """Check if task is cancelled"""
        return self.cancelled


# Global task tracker
active_tasks = {}

def create_progress_tracker(user_id, username=None, engine="pyrogram", mode="upload"):
    """Create a new progress tracker with REAL engine and mode"""
    tracker = AdvancedProgress(user_id, username, engine, mode)
    active_tasks[tracker.get_task_id()] = tracker
    return tracker

def get_progress_tracker(task_id):
    """Get existing progress tracker"""
    return active_tasks.get(task_id)

def remove_progress_tracker(task_id):
    """Remove progress tracker"""
    active_tasks.pop(task_id, None)

def cancel_task(task_id):
    """Cancel a task"""
    if task_id in active_tasks:
        active_tasks[task_id].cancel()
        return True
    return False

def is_task_cancelled(task_id):
    """Check if task is cancelled"""
    tracker = active_tasks.get(task_id)
    return tracker.is_cancelled() if tracker else False

def get_all_active_tasks():
    """Get all active tasks"""
    return active_tasks.copy()

def get_task_count():
    """Get number of active tasks"""
    return len(active_tasks)
