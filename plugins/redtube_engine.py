# -*- coding: utf-8 -*-
"""
RedTube Custom Engine for BIMBO Bot
Extracts video URLs from RedTube.com
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


def is_redtube(url: str) -> bool:
    """Check if URL is from RedTube"""
    try:
        host = urlparse(url).hostname.lower()
        return "redtube" in host
    except:
        return False


def _clean_url(url: str) -> str:
    url = url.strip()
    if not url.startswith("http"):
        url = "https://" + url
    return url


def _extract_video_id(url: str) -> Optional[str]:
    """Extract video ID from RedTube URL"""
    # Pattern: redtube.com/XXXXX
    match = re.search(r'redtube\.com/(\d+)', url)
    if match:
        return match.group(1)
    return None


def extract_video_info(url: str) -> Optional[Dict]:
    """Extract video information from RedTube"""
    try:
        url = _clean_url(url)
        video_id = _extract_video_id(url)
        
        if not video_id:
            logger.error(f"Could not extract video ID from: {url}")
            return None
        
        logger.info(f"Extracting RedTube video: {video_id}")
        
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
        title_tag = soup.find('h1') or soup.find('title')
        if title_tag:
            title = title_tag.get_text(strip=True)
            title = re.sub(r'\s*-\s*RedTube.*$', '', title, flags=re.I)
        
        # Extract thumbnail
        thumbnail = None
        og_image = soup.find('meta', property='og:image')
        if og_image:
            thumbnail = og_image.get('content')
        
        # Extract duration
        duration = 0
        duration_match = re.search(r'duration["\s:]+(\d+)', html, re.I)
        if duration_match:
            duration = int(duration_match.group(1))
        
        # Extract video URLs
        qualities = []
        
        # RedTube uses player configuration
        video_patterns = [
            r'"mediaDefinitions"\s*:\s*(\[[^\]]+\])',
            r'"sources"\s*:\s*(\[[^\]]+\])',
            r'(https?://[^"\']*?\.mp4[^"\']*)',
        ]
        
        # Try to find media definitions JSON
        media_match = re.search(video_patterns[0], html)
        if media_match:
            try:
                media_json = media_match.group(1)
                media_list = json.loads(media_json)
                
                for media in media_list:
                    video_url = media.get('videoUrl') or media.get('src')
                    quality = media.get('quality')
                    
                    if video_url:
                        quality_height = int(quality) if quality and str(quality).isdigit() else 720
                        quality_label = QLABEL.get(quality_height, f"{quality_height}p")
                        
                        qualities.append({
                            'height': quality_height,
                            'label': quality_label,
                            'url': video_url
                        })
            except Exception as e:
                logger.warning(f"Error parsing media definitions: {e}")
        
        # Fallback: Direct video URLs
        if not qualities:
            for pattern in video_patterns[2:]:
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
            'title': title or 'RedTube Video',
            'thumbnail': thumbnail,
            'duration': duration,
            'qualities': unique_qualities,
            'headers': dict(session.headers),
            'webpage_url': url
        }
        
    except Exception as e:
        logger.error(f"Error extracting RedTube video: {e}", exc_info=True)
        return None


async def test():
    """Test the engine"""
    print("RedTube Engine Test")
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(test())
