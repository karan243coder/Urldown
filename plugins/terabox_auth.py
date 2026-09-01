"""
Terabox Auto-Login & Session Management
Automatically handles login, session creation, and cookie refresh
"""

import logging
import time
import requests
import json
from typing import Optional, Dict
from config import BIMBO_TERABOX_COOKIE, BIMBO_TERABOX_EMAIL, BIMBO_TERABOX_PASSWORD

logger = logging.getLogger(__name__)

class TeraboxAuth:
    """Automatic Terabox authentication and session management"""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Origin': 'https://www.terabox.com',
            'Referer': 'https://www.terabox.com/',
        })
        self.email = BIMBO_TERABOX_EMAIL
        self.password = BIMBO_TERABOX_PASSWORD
        self.cookies = {}
        self.last_login_time = 0
        self.session_valid = False
    
    def login(self) -> bool:
        """Perform automatic login to Terabox"""
        try:
            if not self.email or not self.password:
                logger.error("Terabox credentials not configured")
                return False
            
            logger.info(f"Attempting Terabox login for: {self.email}")
            
            # Step 1: Get initial page and CSRF token
            response = self.session.get('https://www.terabox.com/login', timeout=30)
            
            if response.status_code != 200:
                logger.error(f"Failed to load login page: {response.status_code}")
                return False
            
            # Step 2: Extract CSRF token if available
            csrf_token = None
            for cookie in self.session.cookies:
                if cookie.name == 'csrfToken':
                    csrf_token = cookie.value
                    break
            
            # Step 3: Perform login
            login_url = 'https://www.terabox.com/api/login'
            login_data = {
                'email': self.email,
                'password': self.password,
            }
            
            if csrf_token:
                login_data['csrfToken'] = csrf_token
            
            response = self.session.post(
                login_url,
                json=login_data,
                headers={
                    'Content-Type': 'application/json',
                    'X-Requested-With': 'XMLHttpRequest',
                },
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                
                if result.get('errno') == 0 or result.get('success'):
                    logger.info("✅ Terabox login successful!")
                    self.last_login_time = time.time()
                    self.session_valid = True
                    
                    # Save cookies
                    self.cookies = {
                        cookie.name: cookie.value
                        for cookie in self.session.cookies
                    }
                    
                    return True
                else:
                    error_msg = result.get('errmsg', 'Unknown error')
                    logger.error(f"❌ Terabox login failed: {error_msg}")
                    return False
            else:
                logger.error(f"❌ Login request failed: {response.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Login error: {e}", exc_info=True)
            return False
    
    def is_session_valid(self) -> bool:
        """Check if current session is still valid"""
        if not self.session_valid:
            return False
        
        # Session expires after 1 hour
        if time.time() - self.last_login_time > 3600:
            logger.info("Session expired, need to re-login")
            self.session_valid = False
            return False
        
        return True
    
    def ensure_authenticated(self) -> bool:
        """Ensure we have a valid session, login if needed"""
        if self.is_session_valid():
            return True
        
        logger.info("Session invalid, attempting login...")
        return self.login()
    
    def get_cookies_string(self) -> str:
        """Get cookies as string for TeraboxDL"""
        if not self.cookies:
            return ""
        
        return '; '.join([f"{name}={value}" for name, value in self.cookies.items()])
    
    def download_with_session(self, download_url: str, save_path: str) -> Optional[str]:
        """Download file using authenticated session"""
        try:
            if not self.ensure_authenticated():
                logger.error("Cannot download: authentication failed")
                return None
            
            logger.info(f"Downloading file: {download_url}")
            
            response = self.session.get(
                download_url,
                stream=True,
                timeout=300
            )
            
            if response.status_code != 200:
                logger.error(f"Download failed: {response.status_code}")
                return None
            
            # Save file
            with open(save_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            
            logger.info(f"✅ Downloaded successfully: {save_path}")
            return save_path
            
        except Exception as e:
            logger.error(f"❌ Download error: {e}", exc_info=True)
            return None


# Global instance
terabox_auth = TeraboxAuth()
