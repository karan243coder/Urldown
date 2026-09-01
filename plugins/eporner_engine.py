# -*- coding: utf-8 -*-
# ============================================================
#  Eporner custom engine for Telegram bot (100% Bulletproof)
#  - Session-based pre-warming (visits homepage first for cookies)
#  - Multi-pattern hash extractor & AJAX XHR headers
# ============================================================

import re
import json
import html as html_lib
import logging
import string
import random
from urllib.parse import urlparse, urljoin, quote

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# US IP addresses for header spoofing (bypasses EU age gate on Koyeb)
_US_IPS = [
    "104.16.0.1", "151.101.1.1", "76.76.2.0", "98.137.11.163",
    "204.79.197.200", "13.107.42.14", "199.232.69.194", "142.250.80.46",
]

def _get_us_ip():
    return random.choice(_US_IPS)

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

QLABEL = {
    144: "144p", 240: "240p", 360: "360p", 480: "480p (SD)",
    720: "720p (HD)", 1080: "1080p (FHD)", 1440: "1440p (2K)", 2160: "4K UHD",
}


def _encode_base_n(num, n):
    chars = string.digits + string.ascii_lowercase
    if num == 0:
        return chars[0]
    result = []
    while num > 0:
        result.append(chars[num % n])
        num //= n
    return "".join(reversed(result))


def _calc_hash(s):
    return "".join(_encode_base_n(int(s[lb:lb + 8], 16), 36) for lb in range(0, 32, 8))


def is_eporner(url: str) -> bool:
    try:
        host = (urlparse(str(url)).hostname or "").lower()
    except Exception:
        host = str(url or "").lower()
    host = re.sub(r"^(www|m|mobile|de|fr|es|it|pt|nl|ru|jp|en)\.", "", host)
    if "eporner" in host:
        return True
    return False


def _clean_eporner_page_url(url: str) -> str:
    url = html_lib.unescape(str(url or "").strip())
    m = re.search(r"https?://[^\s<>\"']+", url)
    if m:
        url = m.group(0)
    url = url.strip().strip("`'\"<>[]()")
    try:
        p = urlparse(url)
        return p._replace(query="", fragment="").geturl()
    except Exception:
        return url.split("?", 1)[0].split("#", 1)[0]


def _base_of(url: str) -> str:
    try:
        p = urlparse(url)
        return f"{p.scheme}://{p.hostname}"
    except Exception:
        return "https://www.eporner.com"


def _clean_title(title, page_url):
    if not title:
        return "eporner_video"
    t = re.sub(r"\s*[-|]\s*(EPORNER|Eporner).*$", "", title, flags=re.I)
    t = re.sub(r'[\\/:*?"<>|]+', ' ', t).strip()
    return t[:100] or "eporner_video"


def _parse_duration_sec(dur: str) -> int:
    if not dur:
        return 999999
    s = str(dur).strip().lower()
    try:
        if ":" in s:
            parts = [int(p) for p in s.split(":") if p.strip().isdigit()]
            if len(parts) == 3:
                return parts[0]*3600 + parts[1]*60 + parts[2]
            if len(parts) == 2:
                return parts[0]*60 + parts[1]
            if len(parts) == 1:
                return parts[0]
        total = 0
        hm = re.match(r"(?:(\d+)\s*h)?\s*(?:(\d+)\s*m)?\s*(?:(\d+)\s*s)?", s)
        if hm:
            h, m, sec = hm.groups()
            total = (int(h or 0))*3600 + (int(m or 0))*60 + int(sec or 0)
            if total > 0:
                return total
    except Exception:
        pass
    return 999999


def _get_video_id(url: str):
    """Extract video ID from any eporner URL format."""
    for pat in [r'/(?:hd-porn|embed)/([a-zA-Z0-9]+)', r'/video-([a-zA-Z0-9]+)']:
        m = re.search(pat, url)
        if m:
            return m.group(1)
    return None


def _find_hash(html: str):
    """Find 32-char hex hash in page HTML using multiple patterns."""
    # Priority 1: EP.video.player.hash (most reliable)
    m = re.search(r'EP\.video\.player\.hash\s*=\s*["\']([\da-f]{32})["\']', html)
    if m:
        return m.group(1)
    # Priority 2: generic hash= or hash: assignment
    m = re.search(r'hash\s*[:=]\s*["\']([\da-f]{32})["\']', html)
    if m:
        # Make sure it's not EP.user.hash (which can be 'false')
        pos = m.start()
        before = html[max(0, pos-40):pos]
        if "user.hash" not in before:
            return m.group(1)
    # Priority 3: any standalone 32-hex in a JS context (careful: skip user.hash lines)
    for m in re.finditer(r'["\']([\da-f]{32})["\']', html):
        pos = m.start()
        before = html[max(0, pos-50):pos]
        if "user.hash" in before or "csrfToken" in before:
            continue
        return m.group(1)
    return None


def _is_age_gate(html: str) -> bool:
    """Check if the page is an Eporner Age Verification gate."""
    if not html:
        return False
    return ("Age Verification" in html or "ageVerif" in html[:2000]) and len(html) < 10000


def _set_age_cookies(session):
    """Set age verification cookies to bypass EU age gate."""
    # REAL cookie from user's browser - THIS is the actual bypass!
    for domain in [".eporner.com", "www.eporner.com", "de.eporner.com"]:
        session.cookies.set("ageverif_accepted", "T", domain=domain)
        session.cookies.set("cookies_accepted", "T", domain=domain)
        session.cookies.set("EPRNS", "181ed4670f475f2d3572821c2d538f72", domain=domain)
        session.cookies.set("epcolor", "black", domain=domain)
    # PHPSESSID on www specifically
    session.cookies.set("PHPSESSID", "9739ea4899ee2e0f22ebacc4c0e4eb02", domain="www.eporner.com")
    session.cookies.set("PHPSESSID", "9739ea4899ee2e0f22ebacc4c0e4eb02", domain=".eporner.com")
    logger.info("eporner: age verification cookies set (ageverif_accepted=T)")


def extract(url: str, cookies_file: str = None):
    desktop = _clean_eporner_page_url(url)
    base = _base_of(desktop)
    us_ip = _get_us_ip()
    headers = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": base + "/",
        "Origin": base,
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "X-Forwarded-For": us_ip,
        "X-Real-IP": us_ip,
    }

    session = requests.Session()
    session.headers.update(headers)
    _set_age_cookies(session)  # Always set age cookies (EU bypass)

    # --- Step 1: Extract video ID from URL (always available) ---
    video_id = _get_video_id(desktop)

    # --- Step 2: Fetch main page and try to get hash ---
    html = ""
    final_url = desktop
    title = None
    duration = None

    try:
        session.get(base + "/", timeout=15)
        r = session.get(desktop, timeout=25, allow_redirects=True)
        html = r.text
        final_url = r.url
        # Try video ID from final URL too (in case of redirect)
        if not video_id:
            video_id = _get_video_id(final_url)
    except Exception as e:
        logger.warning("eporner page fetch fail: %s", e)

    if not video_id:
        logger.warning("eporner: video id not found in url %s", final_url)
        return None

    # --- Step 3: Extract title and duration from main page ---
    # Priority: JSON-LD > og:title > <title> tag (skip age verification pages)
    _BAD_TITLES = {"age verification", "eporner age", "access denied", "please verify", "18+"}

    def _title_is_bad(t):
        if not t:
            return True
        tl = t.lower().strip()
        return any(bad in tl for bad in _BAD_TITLES) or len(tl) < 3

    # Try JSON-LD first (most reliable, works even on age-gate pages)
    json_ld = re.search(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, re.I | re.S)
    if json_ld:
        try:
            ld_data = json.loads(json_ld.group(1))
            if isinstance(ld_data, dict):
                title = ld_data.get("name") or title
        except Exception:
            pass

    # Then og:title
    if _title_is_bad(title):
        og_m = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\'](.*?)["\']', html, re.I)
        if og_m:
            t = re.sub(r"\s+", " ", og_m.group(1)).strip()
            if not _title_is_bad(t):
                title = t

    # Then <title> tag (last resort, skip if it says "age verification")
    if _title_is_bad(title):
        tm = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
        if tm:
            t = re.sub(r"\s+", " ", tm.group(1)).strip()
            if not _title_is_bad(t):
                title = t

    # Last resort: build title from URL slug
    if _title_is_bad(title):
        try:
            from urllib.parse import unquote
            slug = urlparse(desktop).path.rstrip('/').split('/')[-1]
            if slug:
                slug = unquote(slug).replace('-', ' ')
                slug = re.sub(r'\s+', ' ', slug).strip()
                if slug and len(slug) > 3:
                    title = slug.title()
        except Exception:
            pass

    dm = re.search(r'<meta[^>]+property=["\']video:duration["\'][^>]+content=["\'](\d+)["\']', html, re.I)
    if dm:
        try:
            duration = int(dm.group(1))
        except Exception:
            pass

    thumbnail = None
    if json_ld:
        try:
            ld_data = json.loads(json_ld.group(1))
            if isinstance(ld_data, dict):
                thumbnail = ld_data.get("thumbnailUrl") or ld_data.get("thumbnail")
                if isinstance(thumbnail, list) and thumbnail:
                    thumbnail = thumbnail[0]
        except Exception:
            pass
    if not thumbnail and html:
        tm_img = (
            re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\'](.*?)["\']', html, re.I)
            or re.search(r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\'](.*?)["\']', html, re.I)
            or re.search(r'<meta[^>]+itemprop=["\']thumbnailUrl["\'][^>]+content=["\'](.*?)["\']', html, re.I)
        )
        if tm_img:
            thumbnail = tm_img.group(1)

    # --- Step 4: Find hash — try main page first ---
    vid_hash = _find_hash(html) if html else None

    # --- Step 5: FALLBACK — try embed URL if hash not found ---
    if not vid_hash:
        embed_url = f"{base}/embed/{video_id}/"
        logger.info("eporner: hash not on main page, trying embed URL: %s", embed_url)
        try:
            r_embed = session.get(embed_url, timeout=20, allow_redirects=True)
            embed_html = r_embed.text
            vid_hash = _find_hash(embed_html)
            if vid_hash:
                logger.info("eporner: hash found via embed URL: %s", vid_hash[:8] + "...")
            # Also grab title from embed if missing or bad
            if _title_is_bad(title):
                # Try og:title from embed
                og_embed = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\'](.*?)["\']', embed_html, re.I)
                if og_embed:
                    t = re.sub(r"\s+", " ", og_embed.group(1)).strip()
                    if not _title_is_bad(t):
                        title = t
                # Fallback: <title> tag
                if _title_is_bad(title):
                    tm2 = re.search(r"<title[^>]*>(.*?)</title>", embed_html, re.I | re.S)
                    if tm2:
                        t = re.sub(r"\s+", " ", tm2.group(1)).strip()
                        if not _title_is_bad(t):
                            title = t
        except Exception as e:
            logger.warning("eporner: embed fetch fail: %s", e)

    # --- Step 6: FALLBACK — try hd-porn URL format ---
    if not vid_hash:
        alt_url = f"{base}/hd-porn/{video_id}/"
        logger.info("eporner: hash still not found, trying hd-porn URL: %s", alt_url)
        try:
            r_alt = session.get(alt_url, timeout=20, allow_redirects=True)
            alt_html = r_alt.text
            vid_hash = _find_hash(alt_html)
            if vid_hash:
                logger.info("eporner: hash found via hd-porn URL: %s", vid_hash[:8] + "...")
            if _title_is_bad(title):
                og_alt = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\'](.*?)["\']', alt_html, re.I)
                if og_alt:
                    t = re.sub(r"\s+", " ", og_alt.group(1)).strip()
                    if not _title_is_bad(t):
                        title = t
                if _title_is_bad(title):
                    tm3 = re.search(r"<title[^>]*>(.*?)</title>", alt_html, re.I | re.S)
                    if tm3:
                        t = re.sub(r"\s+", " ", tm3.group(1)).strip()
                        if not _title_is_bad(t):
                            title = t
                dm3 = re.search(r'<meta[^>]+property=["\']video:duration["\'][^>]+content=["\'](\d+)["\']', alt_html, re.I)
                if dm3:
                    try:
                        duration = int(dm3.group(1))
                    except Exception:
                        pass
        except Exception as e:
            logger.warning("eporner: hd-porn fetch fail: %s", e)

    if not vid_hash:
        logger.warning("eporner: hash not found in webpage or embed (video_id=%s)", video_id)
        return None

    ch = _calc_hash(vid_hash)

    api_url = f"{base}/xhr/video/{video_id}"
    api_headers = dict(session.headers)
    api_headers["Accept"] = "application/json, text/javascript, */*; q=0.01"
    api_headers["X-Requested-With"] = "XMLHttpRequest"
    api_headers["Referer"] = desktop

    try:
        api_res = session.get(
            api_url,
            params={
                "hash": ch,
                "device": "generic",
                "domain": urlparse(base).netloc,
                "fallback": "true",  # Use fallback CDN nodes (FR instead of DE — DE blocked on Koyeb)
            },
            headers=api_headers,
            timeout=20,
        )
        if api_res.status_code != 200:
            logger.warning("eporner API status code %s", api_res.status_code)
            return None
        video_data = api_res.json()
    except Exception as e:
        logger.warning("eporner API fetch error: %s", e)
        return None

    if video_data.get("available") is False:
        logger.warning("eporner video not available: %s", video_data.get("message"))
        return None

    sources = video_data.get("sources", {})
    mp4_sources = sources.get("mp4", {})
    if not mp4_sources and not sources:
        logger.warning("eporner: no sources found in API response")
        return None

    qualities = []
    found_heights = []
    for fmt_key, fmt_dict in mp4_sources.items():
        if not isinstance(fmt_dict, dict):
            continue
        src = fmt_dict.get("src")
        if not src or not src.startswith("http"):
            continue
        hm = re.search(r'(\d{3,4})[pP]', fmt_key)
        h = int(hm.group(1)) if hm else 720
        found_heights.append((h, fmt_key, src))

    found_heights.sort(key=lambda x: x[0], reverse=True)
    seen_h = set()
        
    for h, fk, src in found_heights:
        if h in seen_h:
            continue
        seen_h.add(h)
        lbl = QLABEL.get(h, f"{h}p")
        if "60fps" in fk.lower():
            lbl += " 60fps"
        qualities.append({
            "height": h,
            "label": lbl,
            "m3u8": src,
            "url": src,
        })

    if not qualities:
        return None

    return {
        "title": _clean_title(title, desktop),
        "duration": duration,
        "thumbnail": thumbnail,
        "webpage_url": desktop,
        "master_m3u8": qualities[0]["url"],
        "qualities": qualities,
        "headers": {"User-Agent": UA, "Referer": desktop, "Origin": base},
    }


def extract_video(url: str, cookies_file: str = None):
    return extract(url, cookies_file)


def extract_listing(url: str):
    desktop = _clean_eporner_page_url(url)
    base = _base_of(desktop)
    us_ip = _get_us_ip()
    headers = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": base + "/",
        "Origin": base,
        "X-Forwarded-For": us_ip,
        "X-Real-IP": us_ip,
    }
    session = requests.Session()
    session.headers.update(headers)
    _set_age_cookies(session)  # Always set age cookies (EU bypass)
    
    # Try multiple domains in order of preference
    # Try de.eporner.com first (no EU age gate), then fallback to www
    domains_to_try = ["https://de.eporner.com", "https://www.eporner.com"]
    
    for domain in domains_to_try:
        try:
            # Pre-warm session
            session.get(domain + "/", timeout=15)
            
            # Convert URL to this domain
            parsed = urlparse(desktop)
            domain_parsed = urlparse(domain)
            test_url = desktop.replace(f"{parsed.scheme}://{parsed.netloc}", f"{domain_parsed.scheme}://{domain_parsed.netloc}")
            
            r = session.get(test_url, timeout=25, allow_redirects=True)
            if r.status_code != 200:
                logger.warning("eporner listing: HTTP %s for %s", r.status_code, test_url)
                continue
            
            html = r.text
            
            # Check for age gate
            if _is_age_gate(html):
                logger.info("eporner listing: age gate detected on %s, trying next domain", domain)
                continue
            
            # Success! Use this domain
            base = domain
            desktop = test_url
            logger.info("eporner listing: using domain %s", domain)
            break
            
        except Exception as e:
            logger.warning("eporner listing: error with domain %s: %s", domain, e)
            continue
    else:
        # All domains failed
        return [], None, "age_verification_required"

    if not html or len(html) < 1000:
        logger.warning("eporner listing: empty/short HTML (%d chars)", len(html or ""))
        return [], None, "empty page"

    soup = BeautifulSoup(html, "lxml")
    items = []
    seen = set()

    # Multiple selector strategies (different Eporner page layouts)
    video_links = soup.select("a[href*='/video-']")
    if not video_links:
        video_links = soup.select("a[href*='/hd-porn/']")
    if not video_links:
        video_links = soup.select("a[href*='/embed/']")
    if not video_links:
        # Last resort: find all <a> tags and filter by href pattern
        video_links = [a for a in soup.find_all("a", href=True)
                       if re.search(r'/(?:video-|hd-porn/)[a-zA-Z0-9]', a["href"])]

    logger.info("eporner listing: found %d video links on page (html=%d chars, final_url=%s)",
                len(video_links), len(html), getattr(r, 'url', '?'))

    # Extract next page URL
    next_page = None
    for a in soup.select("a.next, a[rel='next'], .pagination a.ar, a[class*='next']"):
        href = a.get("href")
        if href:
            next_page = urljoin(base, href)
            break

    # If still nothing, try extracting video URLs from raw HTML (anti-bot pages)
    if not video_links:
        raw_urls = re.findall(r'href=["\'](/(?:video-|hd-porn/)[a-zA-Z0-9]+/[^"\']*)["\']', html)
        if raw_urls:
            logger.info("eporner listing: fallback found %d URLs from raw HTML", len(raw_urls))
            for href in raw_urls:
                u = urljoin(base, href)
                if u not in seen:
                    seen.add(u)
                    slug = urlparse(u).path.rstrip("/").split("/")[-1]
                    title = slug.replace("-", " ").strip().title() or "Video"
                    items.append({
                        "title": title[:120],
                        "url": u,
                        "thumb": "",
                        "duration": "",
                        "duration_sec": 999999,
                    })
            if items:
                return items, next_page, None
        logger.warning("eporner listing: NO video links found at all! HTML snippet: %s", html[:500])

    for a in video_links:
        href = a.get("href")
        if not href:
            continue
        u = urljoin(base, href)
        if u in seen:
            continue
        seen.add(u)
        title = a.get("title") or a.get("aria-label") or ""
        if not title:
            img = a.find("img")
            if img:
                title = img.get("alt") or img.get("title") or ""
        if not title:
            txt = a.get_text(" ", strip=True)
            if txt and len(txt) > 3:
                title = txt
        if not title:
            slug = urlparse(u).path.rstrip("/").split("/")[-1]
            title = slug.replace("-", " ").strip().title() or "Video"

        thumb = ""
        img = a.find("img")
        if img:
            thumb = img.get("src") or img.get("data-src") or img.get("data-original") or ""

        dur = ""
        parent = a.parent
        for _ in range(5):
            if parent is None:
                break
            dur_el = parent.select_one(".duration, .mbtim, [class*='duration']")
            if dur_el:
                dur = dur_el.get_text(strip=True)
                break
            parent = parent.parent

        items.append({
            "title": title[:120],
            "url": u,
            "thumb": thumb,
            "duration": dur,
            "duration_sec": _parse_duration_sec(dur),
        })

    return items, next_page, None
