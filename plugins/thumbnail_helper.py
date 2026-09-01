# BIMBO v4.0 - Thumbnail Helper (Simple, No PIL)
# ================================================
# Features:
# - Download thumbnail from URL
# - Send with buttons
# - Auto cleanup
# - Fallback to text if thumbnail fails
# - RAM efficient (512MB safe)

import os
import time
import logging
import requests
from typing import Optional

from pyrogram import Client
from pyrogram.types import InlineKeyboardMarkup

logger = logging.getLogger(__name__)

# Thumbnail cache (avoid re-downloading same thumbnail)
_thumb_cache = {}  # url -> local_path
_CACHE_TTL = 300  # 5 minutes


def get_cached_thumbnail(url: str) -> Optional[str]:
    """Get thumbnail from cache if available and not expired"""
    if url in _thumb_cache:
        path, timestamp = _thumb_cache[url]
        if os.path.exists(path) and (time.time() - timestamp) < _CACHE_TTL:
            return path
        # Expired, delete old file
        try:
            os.remove(path)
        except Exception:
            pass
        del _thumb_cache[url]
    return None


def cache_thumbnail(url: str, local_path: str):
    """Cache thumbnail for future use"""
    _thumb_cache[url] = (local_path, time.time())


async def download_thumbnail(url: str, timeout: int = 5) -> Optional[str]:
    """
    Download thumbnail from URL to temp file.
    Returns local path or None if failed.
    """
    if not url:
        return None
    
    # Check cache first
    cached = get_cached_thumbnail(url)
    if cached:
        return cached
    
    try:
        # Create temp filename
        temp_dir = "data/thumbnails"
        os.makedirs(temp_dir, exist_ok=True)
        
        temp_path = os.path.join(temp_dir, f"thumb_{int(time.time() * 1000)}.jpg")
        
        # Download with timeout
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        response = requests.get(url, headers=headers, timeout=timeout)
        response.raise_for_status()
        
        # Save to temp file
        with open(temp_path, 'wb') as f:
            f.write(response.content)
        
        # Verify file exists and has content
        if os.path.exists(temp_path) and os.path.getsize(temp_path) > 0:
            # Cache it
            cache_thumbnail(url, temp_path)
            logger.debug(f"Thumbnail downloaded: {temp_path} ({os.path.getsize(temp_path)} bytes)")
            return temp_path
        else:
            logger.debug(f"Thumbnail download failed (empty file): {url}")
            return None
            
    except requests.exceptions.Timeout:
        logger.debug(f"Thumbnail timeout: {url}")
        return None
    except requests.exceptions.RequestException as e:
        logger.debug(f"Thumbnail request failed: {url} - {e}")
        return None
    except Exception as e:
        logger.debug(f"Thumbnail download error: {url} - {e}")
        return None


async def send_thumbnail_with_buttons(
    client: Client,
    chat_id: int,
    thumbnail_url: str,
    caption: str,
    buttons: InlineKeyboardMarkup,
    reply_to: Optional[int] = None
) -> bool:
    """
    Send thumbnail with buttons.
    Returns True if sent successfully, False if fallback to text.
    """
    if not thumbnail_url:
        return False
    
    try:
        # Download thumbnail
        local_path = await download_thumbnail(thumbnail_url)
        
        if not local_path:
            return False
        
        # Send photo with buttons
        await client.send_photo(
            chat_id=chat_id,
            photo=local_path,
            caption=caption,
            reply_markup=buttons,
            reply_to_message_id=reply_to
        )
        
        # Note: Don't delete immediately - cache will handle it
        # Or delete after 5 minutes via cleanup
        
        return True
        
    except Exception as e:
        logger.debug(f"Failed to send thumbnail: {e}")
        return False


async def send_fallback_text(
    client: Client,
    chat_id: int,
    caption: str,
    buttons: InlineKeyboardMarkup,
    reply_to: Optional[int] = None
):
    """Send text message with buttons (fallback when thumbnail fails)"""
    await client.send_message(
        chat_id=chat_id,
        text=caption,
        reply_markup=buttons,
        reply_to_message_id=reply_to,
        disable_web_page_preview=True
    )


async def send_with_thumbnail_or_text(
    client: Client,
    chat_id: int,
    thumbnail_url: str,
    caption: str,
    buttons: InlineKeyboardMarkup,
    reply_to: Optional[int] = None
):
    """
    Try to send with thumbnail, fallback to text if fails.
    This is the main function to use.
    """
    success = await send_thumbnail_with_buttons(
        client, chat_id, thumbnail_url, caption, buttons, reply_to
    )
    
    if not success:
        # Fallback to text
        await send_fallback_text(client, chat_id, caption, buttons, reply_to)


def cleanup_old_thumbnails(max_age: int = 600):
    """Cleanup old thumbnails from cache (older than max_age seconds)"""
    now = time.time()
    to_remove = []
    
    for url, (path, timestamp) in _thumb_cache.items():
        if (now - timestamp) > max_age:
            to_remove.append(url)
            try:
                os.remove(path)
            except Exception:
                pass
    
    for url in to_remove:
        del _thumb_cache[url]
    
    if to_remove:
        logger.debug(f"Cleaned up {len(to_remove)} old thumbnails")


# Auto cleanup every 10 minutes
_last_cleanup = 0

def check_cleanup():
    """Check if cleanup is needed"""
    global _last_cleanup
    now = time.time()
    if (now - _last_cleanup) > 600:  # 10 minutes
        cleanup_old_thumbnails()
        _last_cleanup = now
