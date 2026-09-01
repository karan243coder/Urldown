# -*- coding: utf-8 -*-
"""
Sxyprn Custom Engine for BIMBO Bot — CDN direct-download (FULL WORKING)

sxyprn.com apne asli video URL ko `data-vnfo` attribute me obfuscate karke
rakhta hai. Real CDN link paane ke liye wahi algorithm chahiye jo site ki
main2.js use karti hai:

    tmp = path.split("/")
    tmp[1] = tmp[1] + "8/" + boo(ssut51(tmp[6]), ssut51(tmp[7]))   # cdn -> cdn8/<boo>
    tmp[5] = tmp[5] - (ssut51(tmp[6]) + ssut51(tmp[7]))            # preda()
    url  = urljoin(page_url, "/".join(tmp))

    ssut51(s) = us string me saare digits ka sum
    boo(a,b)  = base64(a + "-" + host + "-" + b) with +→- /→_ =→.
    host      = "sxyprn.com" (page ka location.host)

Ye URL HTTP Range support karta hai (yt-dlp/aria2 se seedha download).
NOTE: link me timestamp hota hai jo har page-load pe badalta hai — isliye
      download se theek pehle fresh extract karna zaroori hai (bot yahi karta hai).
"""

import re
import json
import base64
import logging
from urllib.parse import urlparse, urljoin
from typing import Optional, Dict

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")

QLABEL = {
    144: "144p", 240: "240p", 360: "360p", 480: "480p (SD)",
    720: "720p (HD)", 1080: "1080p (FHD)", 1440: "1440p (2K)", 2160: "2160p (4K UHD)",
}


def is_sxyprn(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
        return "sxyprn" in host
    except Exception:
        return False


def _clean_url(url: str) -> str:
    url = (url or "").strip()
    if not url.startswith("http"):
        url = "https://" + url
    return url


# ---------------- sxyprn URL de-obfuscation (mirrors main2.js) ----------------
def _ssut51(arg: str) -> int:
    """Sum of all numeric digits in the string."""
    return sum(int(c) for c in re.sub(r"[^0-9]", "", arg or ""))


def _boo(ss: int, es: int, host: str) -> str:
    """base64(ss + '-' + host + '-' + es) with url-safe-ish replacements."""
    raw = f"{ss}-{host}-{es}".encode("utf-8")
    b = base64.b64encode(raw).decode("ascii")
    return b.replace("+", "-").replace("/", "_").replace("=", ".")


def _decode_vnfo_path(raw_path: str, host: str) -> Optional[str]:
    """
    Given the raw encoded path from data-vnfo, return the real CDN path.
    Mirrors getvsrc()/preda() from sxyprn's main2.js.
    """
    try:
        # JSON me path escaped hota hai (\/ -> /)
        raw_path = raw_path.replace("\\/", "/")
        tmp = raw_path.split("/")
        if len(tmp) < 8:
            logger.error("sxyprn: unexpected path layout: %s", raw_path)
            return None
        # tmp[1]: "cdn" -> "cdn8/<boo(...)>"
        tmp[1] = tmp[1] + "8/" + _boo(_ssut51(tmp[6]), _ssut51(tmp[7]), host)
        # preda(): tmp[5] -= ssut51(tmp[6]) + ssut51(tmp[7])
        tmp[5] = str(int(tmp[5]) - (_ssut51(tmp[6]) + _ssut51(tmp[7])))
        return "/".join(tmp)
    except Exception as e:
        logger.error("sxyprn decode error: %s", e)
        return None


def _guess_quality(html: str, video_url: str) -> int:
    """
    sxyprn ek hi quality serve karta hai aur URL me random digits hote hain,
    isliye URL se guess karna galat label deta hai. Page ke title/description
    me "1080p"/"720p" jaisa hint ho to wahi use karo, warna default 720.
    """
    m = re.search(r"(2160|1440|1080|720|480|360|240)\s*p\b", html, re.I)
    if m:
        try:
            return int(m.group(1))
        except Exception:
            pass
    return 720


def extract_video_info(url: str) -> Optional[Dict]:
    try:
        url = _clean_url(url)
        host = (urlparse(url).hostname or "sxyprn.com")
        # "www." hata do — site JS location.host use karta hai jo bina www hota
        # hai; warna boo() galat base64 banata hai aur CDN 404/expire deta hai.
        if host.startswith("www."):
            host = host[4:]
            url = url.replace("://www.", "://", 1)

        session = requests.Session()
        session.headers.update({
            "User-Agent": UA,
            "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
                       "image/avif,image/webp,*/*;q=0.8"),
            "Accept-Language": "en-US,en;q=0.9",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Referer": f"https://{host}/",
        })

        logger.info("Extracting Sxyprn video: %s", url)
        response = session.get(url, timeout=30, allow_redirects=True)
        if response.status_code != 200:
            logger.error("sxyprn: failed to fetch page: %s", response.status_code)
            return None

        html = response.text
        soup = BeautifulSoup(html, "html.parser")

        # ---- Title ----
        title = None
        t = soup.find("meta", property="og:title")
        if t and t.get("content"):
            title = t["content"].strip()
        if not title:
            tt = soup.find("h1") or soup.find("title")
            if tt:
                title = tt.get_text(strip=True)
        if title:
            title = re.sub(r"\s*-?\s*Sxyprn.*$", "", title, flags=re.I).strip()

        # ---- Thumbnail ----
        thumbnail = None
        og_image = soup.find("meta", property="og:image")
        if og_image and og_image.get("content"):
            thumbnail = og_image["content"]

        # ---- data-vnfo (real source, obfuscated) ----
        video_url = None
        # non-empty vnfo JSON object anywhere in the page
        for m in re.finditer(r"data-vnfo=(['\"])(\{.+?\})\1", html, re.S):
            raw_json = m.group(2)
            try:
                d = json.loads(raw_json)
            except Exception:
                continue
            if not isinstance(d, dict) or not d:
                continue
            # value is the encoded path; key is the post id
            raw_path = next(iter(d.values()))
            decoded = _decode_vnfo_path(raw_path, host)
            if decoded:
                video_url = urljoin(url, decoded)
                break

        if not video_url:
            logger.error("sxyprn: no playable data-vnfo found (page layout changed?)")
            return None

        quality_height = _guess_quality(html, video_url)
        quality_label = QLABEL.get(quality_height, f"{quality_height}p")

        # Headers the CDN needs (Referer = the post page)
        dl_headers = {
            "User-Agent": UA,
            "Referer": url,
        }

        logger.info("sxyprn: resolved CDN url OK (%s)", quality_label)
        return {
            "title": title or "Sxyprn Video",
            "thumbnail": thumbnail,
            "duration": 0,
            "qualities": [{
                "height": quality_height,
                "label": quality_label,
                "url": video_url,
            }],
            "headers": dl_headers,
            "webpage_url": url,
        }

    except Exception as e:
        logger.error("Error extracting Sxyprn video: %s", e, exc_info=True)
        return None
