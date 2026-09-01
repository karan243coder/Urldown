from datetime import datetime, timedelta
from typing import Dict, Optional
import json
import os
from config import BIMBO_OWNER_ID

# Premium limits
FREE_LIMITS = {
    'daily_downloads': 50,
    'daily_size': 5 * 1024 * 1024 * 1024,  # 5 GB (5000 MB)
    'max_file_size': 2 * 1024 * 1024 * 1024,    # 2 GB
    'max_concurrent': 2,
    'queue_priority': 0,
    'torrent_enabled': False,
    'video_conversion': False,
    'screenshot_generation': False
}

PREMIUM_LIMITS = {
    'daily_downloads': 200,
    'daily_size': 80 * 1024 * 1024 * 1024,  # 80 GB
    'max_file_size': 4 * 1024 * 1024 * 1024, # 4 GB
    'max_concurrent': 4,
    'queue_priority': 10,
    'torrent_enabled': True,
    'video_conversion': True,
    'screenshot_generation': True
}

VIP_LIMITS = {
    'daily_downloads': -1,  # Unlimited
    'daily_size': -1,        # Unlimited
    'max_file_size': 10 * 1024 * 1024 * 1024, # 10 GB
    'max_concurrent': 8,
    'queue_priority': 100,
    'torrent_enabled': True,
    'video_conversion': True,
    'screenshot_generation': True
}

class PremiumManager:
    def __init__(self):
        self.premium_file = 'data/premium_users.json'
        self.load_premium_users()
    
    def load_premium_users(self):
        """Load premium users from file"""
        if os.path.exists(self.premium_file):
            with open(self.premium_file, 'r') as f:
                self.premium_users = json.load(f)
        else:
            self.premium_users = {}
    
    def save_premium_users(self):
        """Save premium users to file"""
        os.makedirs(os.path.dirname(self.premium_file), exist_ok=True)
        with open(self.premium_file, 'w') as f:
            json.dump(self.premium_users, f, indent=2)
    
    def is_premium(self, user_id: int) -> bool:
        """Check if user is premium"""
        user_id_str = str(user_id)
        if user_id_str not in self.premium_users:
            return False
        
        user_data = self.premium_users[user_id_str]
        
        # Check if premium is expired
        if user_data.get('expiry'):
            expiry = datetime.fromisoformat(user_data['expiry'])
            if datetime.now() > expiry:
                return False
        
        return True
    
    def get_user_tier(self, user_id: int) -> str:
        """Get user's premium tier"""
        user_id_str = str(user_id)
        if user_id_str not in self.premium_users:
            return 'free'
        
        user_data = self.premium_users[user_id_str]
        
        # Check if premium is expired
        if user_data.get('expiry'):
            expiry = datetime.fromisoformat(user_data['expiry'])
            if datetime.now() > expiry:
                return 'free'
        
        return user_data.get('tier', 'premium')
    
    def add_premium_user(self, user_id: int, tier: str = 'premium', days: int = 30):
        """Add premium user"""
        user_id_str = str(user_id)
        
        expiry = datetime.now() + timedelta(days=days)
        
        self.premium_users[user_id_str] = {
            'tier': tier,
            'added': datetime.now().isoformat(),
            'expiry': expiry.isoformat()
        }
        
        self.save_premium_users()
    
    def remove_premium_user(self, user_id: int):
        """Remove premium user"""
        user_id_str = str(user_id)
        if user_id_str in self.premium_users:
            del self.premium_users[user_id_str]
            self.save_premium_users()
    
    def extend_premium(self, user_id: int, days: int = 30):
        """Extend premium subscription"""
        user_id_str = str(user_id)
        
        if user_id_str not in self.premium_users:
            self.add_premium_user(user_id, days=days)
            return
        
        user_data = self.premium_users[user_id_str]
        
        # Get current expiry or now
        if user_data.get('expiry'):
            current_expiry = datetime.fromisoformat(user_data['expiry'])
            if current_expiry < datetime.now():
                current_expiry = datetime.now()
        else:
            current_expiry = datetime.now()
        
        new_expiry = current_expiry + timedelta(days=days)
        user_data['expiry'] = new_expiry.isoformat()
        
        self.save_premium_users()
    
    def get_premium_info(self, user_id: int) -> Optional[Dict]:
        """Get premium user information"""
        user_id_str = str(user_id)
        
        if user_id_str not in self.premium_users:
            return None
        
        user_data = self.premium_users[user_id_str]
        
        # Check if expired
        if user_data.get('expiry'):
            expiry = datetime.fromisoformat(user_data['expiry'])
            if datetime.now() > expiry:
                return {
                    'tier': 'free',
                    'expired': True,
                    'expiry': expiry.isoformat()
                }
            
            days_remaining = (expiry - datetime.now()).days
            
            return {
                'tier': user_data.get('tier', 'premium'),
                'expired': False,
                'expiry': expiry.isoformat(),
                'days_remaining': days_remaining,
                'added': user_data.get('added')
            }
        
        return {
            'tier': user_data.get('tier', 'premium'),
            'expired': False,
            'expiry': None,
            'days_remaining': -1,  # Lifetime
            'added': user_data.get('added')
        }
    
    def get_all_premium_users(self) -> Dict:
        """Get all premium users"""
        return self.premium_users.copy()

# Global instance
premium_manager = PremiumManager()

def is_premium_user(user_id: int) -> bool:
    """Check if user is premium"""
    if user_id == BIMBO_OWNER_ID:
        return True
    return premium_manager.is_premium(user_id)

def get_user_tier(user_id: int) -> str:
    """Get user's tier"""
    return premium_manager.get_user_tier(user_id)

def get_user_limits(user_id: int) -> Dict:
    """Get user's limits based on tier"""
    if user_id == BIMBO_OWNER_ID:
        return VIP_LIMITS
    
    tier = get_user_tier(user_id)
    
    if tier == 'vip':
        return VIP_LIMITS
    elif tier == 'premium':
        return PREMIUM_LIMITS
    else:
        return FREE_LIMITS

def add_premium_user(user_id: int, tier: str = 'premium', days: int = 30):
    """Add premium user"""
    premium_manager.add_premium_user(user_id, tier, days)

def remove_premium_user(user_id: int):
    """Remove premium user"""
    premium_manager.remove_premium_user(user_id)

def extend_premium(user_id: int, days: int = 30):
    """Extend premium"""
    premium_manager.extend_premium(user_id, days)

def get_premium_info(user_id: int) -> Optional[Dict]:
    """Get premium info"""
    if user_id == BIMBO_OWNER_ID:
        return {'tier': 'vip', 'expired': False, 'expiry': 'Lifetime', 'days_remaining': -1}
    return premium_manager.get_premium_info(user_id)

def check_feature_access(user_id: int, feature: str) -> bool:
    """Check if user has access to a feature"""
    if user_id == BIMBO_OWNER_ID:
        return True
    limits = get_user_limits(user_id)
    return limits.get(feature, False)
