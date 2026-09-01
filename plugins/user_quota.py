from datetime import datetime, timedelta
from typing import Dict, Optional
import json
import os

class UserQuota:
    def __init__(self):
        self.quotas_file = 'data/user_quotas.json'
        self.load_quotas()
    
    def load_quotas(self):
        """Load quotas from file"""
        if os.path.exists(self.quotas_file):
            with open(self.quotas_file, 'r') as f:
                self.quotas = json.load(f)
        else:
            self.quotas = {}
    
    def save_quotas(self):
        """Save quotas to file"""
        os.makedirs(os.path.dirname(self.quotas_file), exist_ok=True)
        with open(self.quotas_file, 'w') as f:
            json.dump(self.quotas, f, indent=2)
    
    def get_user_quota(self, user_id: int) -> Dict:
        """Get user's quota information"""
        user_id_str = str(user_id)
        
        if user_id_str not in self.quotas:
            self.quotas[user_id_str] = {
                'daily_downloads': 0,
                'daily_size': 0,
                'last_reset': datetime.now().isoformat(),
                'is_premium': False,
                'premium_expiry': None
            }
            self.save_quotas()
        
        quota = self.quotas[user_id_str]
        
        # Check if daily reset is needed
        last_reset = datetime.fromisoformat(quota['last_reset'])
        if datetime.now() - last_reset >= timedelta(days=1):
            quota['daily_downloads'] = 0
            quota['daily_size'] = 0
            quota['last_reset'] = datetime.now().isoformat()
            self.save_quotas()
        
        return quota
    
    def can_download(self, user_id: int, file_size: int = 0) -> tuple[bool, str]:
        """Check if user can download"""
        from plugins.premium import is_premium_user, get_user_limits
        
        quota = self.get_user_quota(user_id)
        limits = get_user_limits(user_id)
        
        # Check daily download limit
        if quota['daily_downloads'] >= limits['daily_downloads']:
            remaining = limits['daily_downloads'] - quota['daily_downloads']
            return False, f"Daily download limit exceeded! Remaining: {remaining}"
        
        # Check daily size limit
        if quota['daily_size'] + file_size > limits['daily_size']:
            remaining_bytes = limits['daily_size'] - quota['daily_size']
            remaining_mb = remaining_bytes / (1024 * 1024)
            return False, f"Daily size limit exceeded! Remaining: {remaining_mb:.2f} MB"
        
        # Check max file size
        if file_size > limits['max_file_size']:
            max_mb = limits['max_file_size'] / (1024 * 1024)
            return False, f"File too large! Max allowed: {max_mb:.2f} MB"
        
        return True, "OK"
    
    def record_download(self, user_id: int, file_size: int):
        """Record a download"""
        quota = self.get_user_quota(user_id)
        quota['daily_downloads'] += 1
        quota['daily_size'] += file_size
        self.save_quotas()
    
    def get_remaining(self, user_id: int) -> Dict:
        """Get remaining quota"""
        from plugins.premium import get_user_limits
        
        quota = self.get_user_quota(user_id)
        limits = get_user_limits(user_id)
        
        return {
            'downloads': limits['daily_downloads'] - quota['daily_downloads'],
            'size': limits['daily_size'] - quota['daily_size'],
            'downloads_limit': limits['daily_downloads'],
            'size_limit': limits['daily_size']
        }
    
    def reset_quota(self, user_id: int):
        """Reset user's daily quota"""
        quota = self.get_user_quota(user_id)
        quota['daily_downloads'] = 0
        quota['daily_size'] = 0
        quota['last_reset'] = datetime.now().isoformat()
        self.save_quotas()

# Global instance
quota_manager = UserQuota()

def can_user_download(user_id: int, file_size: int = 0) -> tuple[bool, str]:
    """Check if user can download"""
    return quota_manager.can_download(user_id, file_size)

def record_user_download(user_id: int, file_size: int):
    """Record user download"""
    quota_manager.record_download(user_id, file_size)

def get_user_remaining(user_id: int) -> Dict:
    """Get user's remaining quota"""
    return quota_manager.get_remaining(user_id)

def reset_user_quota(user_id: int):
    """Reset user's quota"""
    quota_manager.reset_quota(user_id)
