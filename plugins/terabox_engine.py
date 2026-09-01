import logging
import re
from urllib.parse import urlparse
from typing import Optional, Dict, Any, List
from config import BIMBO_TERABOX_COOKIE, BIMBO_TERABOX_EMAIL, BIMBO_TERABOX_PASSWORD
from plugins.terabox_auth import terabox_auth

logger = logging.getLogger(__name__)

# Terabox domain patterns
TERABOX_DOMAINS = [
    'terabox.com', 'teraboxapp.com', '1024tera.com', '1024terabox.com',
    'terasharefile.com', 'terashare.net', 'terabox.app', 'teraboxlink.com',
    'teraboxshare.com', 'terafileshare.com', 'mirrobox.com', 'nephobox.com',
    '4funbox.com', 'momerybox.com', 'tibibox.com', 'freeterabox.com',
    'terafile.co', 'dubox.com', 'terabox.hn', 'terabox.club', 'terabox.fun',
    'terabox.news', 'terabox.site', 'terabox.online', 'terabox.space',
    'terabox.tech', 'terabox.work', 'terabox.world', 'terabox.xyz'
]

def is_terabox(url: str) -> bool:
    """Check if URL is a Terabox link"""
    try:
        domain = urlparse(url).netloc.lower()
        # Remove www. prefix
        domain = re.sub(r'^www\.', '', domain)
        
        for terabox_domain in TERABOX_DOMAINS:
            if terabox_domain in domain:
                return True
        return False
    except Exception as e:
        logger.error(f"Error checking if URL is Terabox: {e}")
        return False

def extract_terabox_info(url: str) -> Optional[Dict[str, Any]]:
    """
    Extract file information from Terabox URL using auto-login
    
    Args:
        url: Terabox share link
        
    Returns:
        Dict with file info or None if failed
    """
    try:
        # Import TeraboxDL
        try:
            from TeraboxDL import TeraboxDL
        except ImportError:
            logger.error("TeraboxDL package not installed. Run: pip install terabox-downloader")
            return {
                'error': 'TeraboxDL package not installed',
                'error_type': 'package_missing'
            }
        
        # Try with existing cookies first
        cookie_to_use = BIMBO_TERABOX_COOKIE
        
        if not cookie_to_use:
            # No cookies, try auto-login
            logger.info("No cookies found, attempting auto-login...")
            if not terabox_auth.ensure_authenticated():
                return {
                    'error': 'Auto-login failed. Please check credentials.',
                    'error_type': 'auth_failed'
                }
            cookie_to_use = terabox_auth.get_cookies_string()
        
        # Initialize TeraboxDL with cookie
        logger.info(f"Initializing TeraboxDL for URL: {url}")
        terabox = TeraboxDL(cookie=cookie_to_use)
        
        # Get file info
        logger.info("Fetching file info from Terabox...")
        file_info = terabox.get_file_info(url)
        
        if not file_info:
            logger.error("TeraboxDL returned empty file info")
            return {
                'error': 'Failed to get file information from Terabox',
                'error_type': 'api_error'
            }
        
        # Check for error in response
        if 'error' in file_info:
            error_msg = file_info['error'].lower()
            
            # If "need verify" error, try auto-login and retry
            if 'need verify' in error_msg or 'login' in error_msg:
                logger.info("Session expired or needs verification, attempting auto-login...")
                
                if terabox_auth.ensure_authenticated():
                    cookie_to_use = terabox_auth.get_cookies_string()
                    logger.info("Retrying with fresh cookies...")
                    
                    # Retry with new cookies
                    terabox = TeraboxDL(cookie=cookie_to_use)
                    file_info = terabox.get_file_info(url)
                    
                    if not file_info or 'error' in file_info:
                        logger.error("Retry failed even after auto-login")
                        return {
                            'error': file_info.get('error', 'Failed after retry') if file_info else 'Failed after retry',
                            'error_type': 'auth_retry_failed'
                        }
                else:
                    return {
                        'error': 'Auto-login failed. Please check credentials.',
                        'error_type': 'auth_failed'
                    }
            else:
                logger.error(f"TeraboxDL error: {file_info['error']}")
                return {
                    'error': file_info['error'],
                    'error_type': 'api_error'
                }
        
        # Log success
        logger.info(f"Successfully extracted Terabox file info: {file_info.get('file_name', 'Unknown')}")
        
        return {
            'success': True,
            'file_name': file_info.get('file_name', 'Unknown'),
            'file_size': file_info.get('file_size', 0),
            'download_link': file_info.get('download_link', ''),
            'thumbnail': file_info.get('thumbnail', ''),
            'teraboxdl_instance': terabox  # Pass instance for download
        }
        
    except Exception as e:
        logger.error(f"Error extracting Terabox info: {e}", exc_info=True)
        return {
            'error': str(e),
            'error_type': 'exception'
        }

def download_terabox_file(terabox_instance, file_info: Dict[str, Any], download_dir: str) -> Optional[str]:
    """
    Download file from Terabox
    
    Args:
        terabox_instance: TeraboxDL instance
        file_info: File info dict from extract_terabox_info
        download_dir: Directory to save file
        
    Returns:
        Path to downloaded file or None if failed
    """
    try:
        logger.info(f"Downloading Terabox file to: {download_dir}")
        
        # Download file
        result = terabox_instance.download(file_info, save_path=download_dir)
        
        if 'error' in result:
            logger.error(f"Download error: {result['error']}")
            return None
        
        file_path = result.get('file_path')
        if file_path:
            logger.info(f"Successfully downloaded to: {file_path}")
            return file_path
        else:
            logger.error("Download succeeded but no file path returned")
            return None
            
    except Exception as e:
        logger.error(f"Error downloading Terabox file: {e}", exc_info=True)
        return None

# Alias for compatibility with plugins/youtube_dl_echo.py
extract = extract_terabox_info
