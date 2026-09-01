"""
User Statistics & Download History Tracking
Features: Download limits, history, preferences, analytics
"""

import asyncio
import time
import json
import os
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from config import Config
from utils import is_admin, is_premium

logger = logging.getLogger(__name__)

class UserStats:
    """User statistics and download limits"""
    
    def __init__(self):
        self.stats_file = "user_stats.json"
        self.stats: Dict[int, Dict] = {}
        self._load_stats()
    
    def _load_stats(self):
        """Load stats from file"""
        try:
            if os.path.exists(self.stats_file):
                with open(self.stats_file, 'r') as f:
                    self.stats = json.load(f)
                logger.info(f"Loaded stats for {len(self.stats)} users")
        except Exception as e:
            logger.error(f"Failed to load user stats: {e}")
    
    def _save_stats(self):
        """Save stats to file"""
        try:
            with open(self.stats_file, 'w') as f:
                json.dump(self.stats, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save user stats: {e}")
    
    def get_user(self, user_id: int) -> Dict:
        """Get or create user stats"""
        if user_id not in self.stats:
            self.stats[user_id] = {
                "total_downloads": 0,
                "today_downloads": 0,
                "last_download_date": None,
                "total_data": 0,
                "first_seen": time.time(),
                "last_seen": time.time(),
                "preferences": {
                    "default_quality": "best",
                    "auto_thumbnail": True
                },
                "limits": {
                    "daily_limit": 10,
                    "monthly_limit": 200
                }
            }
        return self.stats[user_id]
    
    def record_download(self, user_id: int, file_size: int = 0):
        """Record a download for user"""
        user = self.get_user(user_id)
        
        # Check if it's a new day
        today = datetime.now().date().isoformat()
        if user["last_download_date"] != today:
            user["today_downloads"] = 0
            user["last_download_date"] = today
        
        user["total_downloads"] += 1
        user["today_downloads"] += 1
        user["total_data"] += file_size
        user["last_seen"] = time.time()
        
        self._save_stats()
    
    def check_daily_limit(self, user_id: int) -> tuple[bool, int]:
        """Check if user has reached daily limit
        Returns: (allowed, remaining_downloads)
        """
        user = self.get_user(user_id)
        
        # Check if it's a new day
        today = datetime.now().date().isoformat()
        if user["last_download_date"] != today:
            return True, user["limits"]["daily_limit"]
        
        remaining = user["limits"]["daily_limit"] - user["today_downloads"]
        return remaining > 0, remaining
    
    def set_daily_limit(self, user_id: int, limit: int):
        """Set daily download limit for user"""
        user = self.get_user(user_id)
        user["limits"]["daily_limit"] = limit
        self._save_stats()
    
    def set_default_quality(self, user_id: int, quality: str):
        """Set default quality preference"""
        user = self.get_user(user_id)
        user["preferences"]["default_quality"] = quality
        self._save_stats()
    
    def get_user_stats(self, user_id: int) -> Dict:
        """Get complete user statistics"""
        user = self.get_user(user_id)
        
        # Calculate stats
        account_age = time.time() - user["first_seen"]
        days_old = account_age / 86400
        
        return {
            "user_id": user_id,
            "total_downloads": user["total_downloads"],
            "today_downloads": user["today_downloads"],
            "daily_limit": user["limits"]["daily_limit"],
            "remaining_today": max(0, user["limits"]["daily_limit"] - user["today_downloads"]),
            "total_data": user["total_data"],
            "account_age_days": int(days_old),
            "last_seen": datetime.fromtimestamp(user["last_seen"]).strftime('%Y-%m-%d %H:%M:%S'),
            "is_premium": is_premium(user_id),
            "is_admin": is_admin(user_id),
            "preferences": user["preferences"]
        }
    
    def get_all_users(self) -> List[Dict]:
        """Get all users with their stats"""
        return [
            {
                "user_id": uid,
                "total_downloads": data["total_downloads"],
                "today_downloads": data["today_downloads"],
                "is_premium": is_premium(uid),
                "is_admin": is_admin(uid)
            }
            for uid, data in self.stats.items()
        ]
    
    def reset_daily_counts(self):
        """Reset daily counts for all users (call at midnight)"""
        for user in self.stats.values():
            user["today_downloads"] = 0
        self._save_stats()
        logger.info("Reset daily download counts for all users")


class DownloadHistory:
    """Download history tracking"""
    
    def __init__(self):
        self.history_file = "download_history.json"
        self.history: List[Dict] = []
        self.max_history = 1000
        self._load_history()
    
    def _load_history(self):
        """Load history from file"""
        try:
            if os.path.exists(self.history_file):
                with open(self.history_file, 'r') as f:
                    self.history = json.load(f)
                logger.info(f"Loaded {len(self.history)} download history records")
        except Exception as e:
            logger.error(f"Failed to load download history: {e}")
    
    def _save_history(self):
        """Save history to file"""
        try:
            with open(self.history_file, 'w') as f:
                json.dump(self.history[-self.max_history:], f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save download history: {e}")
    
    def add_record(self, user_id: int, url: str, filename: str, 
                   file_size: int, quality: str, status: str, 
                   duration: float = 0, error: str = None):
        """Add download record"""
        record = {
            "timestamp": time.time(),
            "user_id": user_id,
            "url": url,
            "filename": filename,
            "file_size": file_size,
            "quality": quality,
            "status": status,
            "duration": duration,
            "error": error
        }
        
        self.history.append(record)
        
        # Keep only last max_history records
        if len(self.history) > self.max_history:
            self.history = self.history[-self.max_history:]
        
        self._save_history()
    
    def get_user_history(self, user_id: int, limit: int = 10) -> List[Dict]:
        """Get download history for a user"""
        user_records = [r for r in self.history if r["user_id"] == user_id]
        return user_records[-limit:]
    
    def get_recent_downloads(self, limit: int = 20) -> List[Dict]:
        """Get recent downloads across all users"""
        return self.history[-limit:]
    
    def get_statistics(self) -> Dict:
        """Get overall download statistics"""
        if not self.history:
            return {"total": 0, "successful": 0, "failed": 0}
        
        successful = len([r for r in self.history if r["status"] == "completed"])
        failed = len([r for r in self.history if r["status"] == "failed"])
        
        return {
            "total": len(self.history),
            "successful": successful,
            "failed": failed,
            "success_rate": (successful / len(self.history)) * 100 if self.history else 0
        }


# Global instances
user_stats = UserStats()
download_history = DownloadHistory()
