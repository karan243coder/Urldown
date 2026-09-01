# -*- coding: utf-8 -*-
"""
Pornhub Custom Engine for BIMBO Bot
Extracts video URLs from Pornhub.com
"""

import re
import json
import logging
import asyncio
from urllib.parse import urlparse, urljoin
from typing import Optional, Dict, List

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"

QLABEL = {
    144: "144p", 240: "240p", 360: "360p", 480: "480p (SD)",
    720: "720p (HD)", 1080: "1080p (FHD)", 1440: "1440p (2K)", 2160: "2160p (4K UHD)",
}


def is_pornhub(url: str) -> bool:
    """Check if URL is from Pornhub"""
    try:
        host = urlparse(url).hostname.lower()
        return "pornhub" in host
    except:
        return False


def _clean_url(url: str) -> str:
    url = url.strip()
    if not url.startswith("http"):
        url = "https://" + url
    return url


def _extract_video_id(url: str) -> Optional[str]:
    """Extract video ID from Pornhub URL"""
    # Pattern: pornhub.com/view_video.php?viewkey=XXXXX
    match = re.search(r'viewkey=([a-zA-Z0-9]+)', url)
    if match:
        return match.group(1)
    
    # Pattern: pornhub.com/embed/XXXXX
    match = re.search(r'pornhub\.com/embed/([a-zA-Z0-9]+)', url)
    if match:
        return match.group(1)
    
    return None


def extract_video_info(url: str) -> Optional[Dict]:
    """Extract video information from Pornhub"""
    try:
        url = _clean_url(url)
        video_id = _extract_video_id(url)
        
        if not video_id:
            logger.error(f"Could not extract video ID from: {url}")
            return None
        
        logger.info(f"Extracting Pornhub video: {video_id}")
        
        session = requests.Session()
        session.headers.update({
            'User-Agent': UA,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
        })
        
        response = session.get(url, timeout=30, allow_redirects=True)
        
        if response.status_code != 200:
            logger.error(f"Failed to fetch page: {response.status_code}")
            return None
        
        html = response.text
        soup = BeautifulSoup(html, 'html.parser')
        
        # Extract title
        title = None
        title_tag = soup.find('h1', class_='title') or soup.find('title')
        if title_tag:
            title = title_tag.get_text(strip=True)
            title = re.sub(r'\s*-\s*Pornhub.*$', '', title, flags=re.I)
        
        # Extract thumbnail
        thumbnail = None
        og_image = soup.find('meta', property='og:image')
        if og_image:
            thumbnail = og_image.get('content')
        
        # Extract duration
        duration = 0
        duration_match = re.search(r'"duration"\s*:\s*(\d+)', html)
        if duration_match:
            duration = int(duration_match.group(1))
        
        # Extract video URLs
        qualities = []
        
        # Pornhub uses flashvars with media definitions
        # Look for flashvars_XXXXX variable
        flashvars_pattern = r'flashvars_\d+\s*=\s*(\{[^;]+\});'
        match = re.search(flashvars_pattern, html)
        
        if match:
            try:
                flashvars_json = match.group(1)
                # Parse media definitions
                media_pattern = r'"mediaDefinitions"\s*:\s*(\[[^\]]+\])'
                media_match = re.search(media_pattern, flashvars_json)
                
                if media_match:
                    media_json = media_match.group(1)
                    media_list = json.loads(media_json)
                    
                    for media in media_list:
                        video_url = media.get('videoUrl')
                        quality = media.get('quality')
                        
                        if video_url and quality:
                            quality_height = int(quality) if quality.isdigit() else 720
                            quality_label = QLABEL.get(quality_height, f"{quality_height}p")
                            
                            qualities.append({
                                'height': quality_height,
                                'label': quality_label,
                                'url': video_url
                            })
            except Exception as e:
                logger.warning(f"Error parsing flashvars: {e}")
        
        # Fallback: Look for direct video URLs
        if not qualities:
            video_patterns = [
                r'(https?://[^"\']*?\.mp4[^"\']*)',
                r'"videoUrl"\s*:\s*"([^"]+)"',
                r'src="([^"]+\.mp4[^"]*)"',
            ]
            
            for pattern in video_patterns:
                matches = re.findall(pattern, html, re.I)
                for video_url in matches:
                    if video_url and video_url not in [q['url'] for q in qualities]:
                        quality_height = 720
                        
                        if '1080' in video_url:
                            quality_height = 1080
                        elif '720' in video_url:
                            quality_height = 720
                        elif '480' in video_url:
                            quality_height = 480
                        
                        quality_label = QLABEL.get(quality_height, f"{quality_height}p")
                        
                        qualities.append({
                            'height': quality_height,
                            'label': quality_label,
                            'url': video_url
                        })
        
        # Remove duplicates and sort
        seen_urls = set()
        unique_qualities = []
        for q in qualities:
            if q['url'] not in seen_urls:
                seen_urls.add(q['url'])
                unique_qualities.append(q)
        
        unique_qualities.sort(key=lambda x: x['height'], reverse=True)
        
        if not unique_qualities:
            logger.error("No video URLs found")
            return None
        
        logger.info(f"Found {len(unique_qualities)} quality variants")
        
        return {
            'title': title or 'Pornhub Video',
            'thumbnail': thumbnail,
            'duration': duration,
            'qualities': unique_qualities,
            'headers': dict(session.headers),
            'webpage_url': url
        }
        
    except Exception as e:
        logger.error(f"Error extracting Pornhub video: {e}", exc_info=True)
        return None


async def test():
    """Test the engine"""
    print("Pornhub Engine Test")
    print("=" * 50)
    # Note: Real testing requires actual URLs


if __name__ == "__main__":
    asyncio.run(test())
