# -*- coding: utf-8 -*-
"""
SpankBang Custom Engine for BIMBO Bot
Extracts video URLs from SpankBang.com
"""

import re
import json
import logging
import asyncio
from urllib.parse import urlparse, urljoin
from typing import Optional, Dict, List, Tuple

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# User Agent
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"

# Quality Labels
QLABEL = {
    144: "144p",
    240: "240p",
    360: "360p",
    480: "480p (SD)",
    720: "720p (HD)",
    1080: "1080p (FHD)",
    1440: "1440p (2K)",
    2160: "2160p (4K UHD)",
}


def is_spankbang(url: str) -> bool:
    """Check if URL is from SpankBang"""
    try:
        host = urlparse(url).hostname.lower()
        return "spankbang" in host or "sb-cdn" in host
    except:
        return False


def _clean_url(url: str) -> str:
    """Clean and normalize URL"""
    url = url.strip()
    if not url.startswith("http"):
        url = "https://" + url
    return url


def _extract_video_id(url: str) -> Optional[str]:
    """Extract video ID from SpankBang URL"""
    # Pattern: spankbang.com/XXXXX/video/...
    match = re.search(r'spankbang\.com/([a-zA-Z0-9]+)/video/', url)
    if match:
        return match.group(1)
    
    # Pattern: spankbang.com/XXXXX/...
    match = re.search(r'spankbang\.com/([a-zA-Z0-9]+)(?:/|$)', url)
    if match:
        return match.group(1)
    
    return None


def _parse_quality_label(label: str) -> int:
    """Parse quality label to height"""
    label = label.lower().strip()
    
    # Extract number
    match = re.search(r'(\d+)', label)
    if match:
        return int(match.group(1))
    
    # Default mappings
    if '4k' in label or '2160' in label:
        return 2160
    elif '1080' in label or 'fhd' in label:
        return 1080
    elif '720' in label or 'hd' in label:
        return 720
    elif '480' in label or 'sd' in label:
        return 480
    elif '360' in label:
        return 360
    elif '240' in label:
        return 240
    
    return 720  # Default


def extract_video_info(url: str) -> Optional[Dict]:
    """
    Extract video information from SpankBang
    
    Returns:
        Dict with keys:
        - title: Video title
        - thumbnail: Thumbnail URL
        - duration: Duration in seconds
        - qualities: List of quality dicts with 'height', 'label', 'url'
        - headers: Request headers
    """
    try:
        url = _clean_url(url)
        video_id = _extract_video_id(url)
        
        if not video_id:
            logger.error(f"Could not extract video ID from: {url}")
            return None
        
        logger.info(f"Extracting SpankBang video: {video_id}")
        
        # Setup session
        session = requests.Session()
        session.headers.update({
            'User-Agent': UA,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        })
        
        # Fetch page
        response = session.get(url, timeout=30, allow_redirects=True)
        
        if response.status_code != 200:
            logger.error(f"Failed to fetch page: {response.status_code}")
            return None
        
        html = response.text
        soup = BeautifulSoup(html, 'html.parser')
        
        # Extract title
        title = None
        title_tag = soup.find('h1')
        if title_tag:
            title = title_tag.get_text(strip=True)
        
        if not title:
            title_tag = soup.find('title')
            if title_tag:
                title = title_tag.get_text(strip=True)
                # Clean title
                title = re.sub(r'\s*-\s*SpankBang.*$', '', title, flags=re.I)
        
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
        
        # Extract video URLs from page
        qualities = []
        
        # Method 1: Look for video sources in page
        # SpankBang embeds video URLs in JavaScript
        video_urls = []
        
        # Pattern 1: Direct video URLs in script
        patterns = [
            r'["\']?(https?://[^"\']*?\.mp4[^"\']*)["\']?',
            r'file:\s*["\']([^"\']+\.mp4[^"\']*)["\']',
            r'src:\s*["\']([^"\']+\.mp4[^"\']*)["\']',
            r'(https?://[^"\']*?/video/[^"\']*\.mp4[^"\']*)',
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, html, re.I)
            for match in matches:
                if match not in video_urls:
                    video_urls.append(match)
        
        # Method 2: Look for data-video-url attributes
        video_elements = soup.find_all(attrs={'data-video-url': True})
        for elem in video_elements:
            video_url = elem.get('data-video-url')
            if video_url and video_url not in video_urls:
                video_urls.append(video_url)
        
        # Method 3: Look for quality selectors
        quality_selectors = soup.find_all('a', class_=re.compile(r'quality|resolution', re.I))
        for selector in quality_selectors:
            quality_text = selector.get_text(strip=True)
            data_url = selector.get('data-url') or selector.get('href')
            if data_url and data_url not in video_urls:
                video_urls.append(data_url)
        
        # Process found URLs
        for video_url in video_urls:
            try:
                # Clean URL
                video_url = video_url.strip()
                if not video_url.startswith('http'):
                    video_url = urljoin('https://spankbang.com', video_url)
                
                # Determine quality from URL
                quality_height = 720  # Default
                
                # Check URL for quality indicators
                if '2160' in video_url or '4k' in video_url.lower():
                    quality_height = 2160
                elif '1440' in video_url or '2k' in video_url.lower():
                    quality_height = 1440
                elif '1080' in video_url or 'fhd' in video_url.lower():
                    quality_height = 1080
                elif '720' in video_url or 'hd' in video_url.lower():
                    quality_height = 720
                elif '480' in video_url or 'sd' in video_url.lower():
                    quality_height = 480
                elif '360' in video_url:
                    quality_height = 360
                elif '240' in video_url:
                    quality_height = 240
                
                quality_label = QLABEL.get(quality_height, f"{quality_height}p")
                
                qualities.append({
                    'height': quality_height,
                    'label': quality_label,
                    'url': video_url
                })
                
            except Exception as e:
                logger.warning(f"Error processing video URL: {e}")
                continue
        
        # Remove duplicates and sort by quality
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
            'title': title or 'SpankBang Video',
            'thumbnail': thumbnail,
            'duration': duration,
            'qualities': unique_qualities,
            'headers': dict(session.headers),
            'webpage_url': url
        }
        
    except Exception as e:
        logger.error(f"Error extracting SpankBang video: {e}", exc_info=True)
        return None


async def download_video(video_info: Dict, quality_height: int = 0, 
                        progress_callback=None) -> Optional[str]:
    """
    Download video from SpankBang
    
    Args:
        video_info: Video info dict from extract_video_info
        quality_height: Desired quality height (0 = best)
        progress_callback: Optional callback for progress updates
    
    Returns:
        Downloaded file path or None
    """
    try:
        qualities = video_info.get('qualities', [])
        
        if not qualities:
            logger.error("No qualities available")
            return None
        
        # Select quality
        if quality_height == 0:
            # Best quality
            selected = qualities[0]
        else:
            # Find closest quality
            selected = min(qualities, key=lambda q: abs(q['height'] - quality_height))
        
        video_url = selected['url']
        title = video_info.get('title', 'video')
        
        # Clean filename
        filename = re.sub(r'[^\w\s-]', '', title)
        filename = re.sub(r'\s+', '_', filename)
        filename = f"{filename}_{selected['height']}p.mp4"
        
        # Setup download
        session = requests.Session()
        session.headers.update(video_info.get('headers', {}))
        session.headers.update({
            'Referer': video_info.get('webpage_url', 'https://spankbang.com'),
        })
        
        # Download with progress
        response = session.get(video_url, stream=True, timeout=60)
        
        if response.status_code != 200:
            logger.error(f"Download failed: {response.status_code}")
            return None
        
        # Get total size
        total_size = int(response.headers.get('content-length', 0))
        
        # Save file
        file_path = filename
        downloaded = 0
        
        with open(file_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    
                    if progress_callback and total_size > 0:
                        progress = (downloaded / total_size) * 100
                        await progress_callback(progress, downloaded, total_size)
        
        logger.info(f"Downloaded: {file_path}")
        return file_path
        
    except Exception as e:
        logger.error(f"Error downloading video: {e}", exc_info=True)
        return None


# Test function
async def test():
    """Test the engine"""
    test_urls = [
        "https://spankbang.com/abc123/video/test",
    ]
    
    for url in test_urls:
        print(f"\nTesting: {url}")
        info = await extract_video_info(url)
        
        if info:
            print(f"✅ Title: {info['title']}")
            print(f"📷 Thumbnail: {info['thumbnail']}")
            print(f"⏱️ Duration: {info['duration']}s")
            print(f"🎬 Qualities: {len(info['qualities'])}")
            for q in info['qualities']:
                print(f"   - {q['label']}: {q['url'][:60]}...")
        else:
            print("❌ Failed to extract")


if __name__ == "__main__":
    asyncio.run(test())
