# -*- coding: utf-8 -*-
"""
JAV / Japanese Adult Video engine for BIMBO Bot.

Dedicated scrape + HLS quality parse for MissAV / Jable / 123AV / NJAV and
mirrors. If scrape fails, yt-dlp -j is used as a last extract step (download
still goes through the bot's HLS-native path so the file actually arrives).

Does NOT replace existing xHamster/Eporner/Pornhub/etc engines.
"""

import base64
import json
import logging
import re
import subprocess
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

logger = logging.getLogger(__name__)

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

QLABEL = {
    144: "144p", 240: "240p", 360: "360p", 480: "480p (SD)",
    720: "720p (HD)", 1080: "1080p (FHD)", 1440: "1440p (2K)", 2160: "4K",
}

# Actual video hosts (not metadata-only indexers).
JAV_HOST_NEEDLES = (
    "missav.", "jable.", "123av.", "njav.", "javguru", "jav.guru",
    "thisav.", "avgle.", "netflav", "supjav.", "javmost", "hpjav.",
    "javfinder", "7mmtv", "javseen.", "memojav", "javtiful",
    "javgg.", "bestjavporn", "tktube.", "avjoy.", "playno1",
    "javplayer", "javhdporn", "javhd.", "avdanyu", "javfree",
    "javfull", "javopen", "jav.sb", "javmix.", "surrit.com",
    "fourhoi.com", "missavtv", "missav1", "missav2",
    "jable.tv", "jableone",
    "caribbeancom.com", "1pondo.tv", "heyzo.com", "tokyo-hot",
    "10musume", "pacopacomama",
)

# Index / listing sites — try embed, else leave to torrent/yt-dlp fallback.
JAV_INDEX_NEEDLES = (
    "javbus.", "javdb.", "javlibrary", "jav321.", "r18.dev", "r18.com",
)

_AD_HOST = (
    "mayzaent", "pemsrv", "doubleclick", "googlesyndication", "about:blank",
    "dead-put.com", "waust.at", "frozenpayer",
)

_M3U8_RE = re.compile(
    r'(?:https?:)?//[^\s"\'<>\\]+?\.m3u8(?:\?[^\s"\'<>\\]*)?',
    re.I,
)
_MP4_RE = re.compile(
    r'(?:https?:)?//[^\s"\'<>\\]+?\.mp4(?:\?[^\s"\'<>\\]*)?',
    re.I,
)
_HLS_VAR_RE = re.compile(
    r'(?:hlsUrl|hls_url|m3u8Url|m3u8_url|videoSrc|video_src|source\.src|'
    r'playlistUrl|playlist_url|videoUrl|video_url|hls2|hls3|hls4)\s*[:=]\s*[\'"]([^\'"]+)',
    re.I,
)


def _host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""


def is_jav(url: str) -> bool:
    h = _host(url)
    if not h:
        return False
    return any(n in h for n in JAV_HOST_NEEDLES + JAV_INDEX_NEEDLES)


def _abs(base: str, link: str) -> str:
    if not link:
        return link
    link = link.strip().strip("'\"")
    if link.startswith("//"):
        return "https:" + link
    return urljoin(base, link)


def _height_from_text(text: str, default: int = 720) -> int:
    m = re.search(r"(2160|1440|1080|720|480|360|240|144)\s*[pP]?", text or "")
    if m:
        try:
            return int(m.group(1))
        except Exception:
            pass
    return default


def _hdr(referer: str = "") -> dict:
    h = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9,ja;q=0.8"}
    if referer:
        h["Referer"] = referer
        p = urlparse(referer)
        if p.scheme and p.hostname:
            h["Origin"] = f"{p.scheme}://{p.hostname}"
    return h


def _fetch_html(url: str, referer: str = "") -> Optional[str]:
    html = None
    headers = _hdr(referer)
    try:
        from curl_cffi import requests as creq
        r = creq.get(
            url,
            headers=headers,
            impersonate="chrome",
            timeout=25,
            allow_redirects=True,
            verify=False,
        )
        if r.status_code == 200 and len(r.text or "") > 200:
            html = r.text
    except Exception as e:
        logger.debug("jav curl_cffi fetch: %s", e)
    if html:
        return html
    try:
        import requests
        r = requests.get(
            url,
            headers=headers,
            timeout=25,
            allow_redirects=True,
            verify=False,
        )
        if r.status_code == 200:
            return r.text
    except Exception as e:
        logger.debug("jav requests fetch: %s", e)
    return None


def _unescape(html: str) -> str:
    if not html:
        return html
    out = html.replace("\\/", "/").replace('\\"', '"').replace("\\'", "'")
    out = re.sub(r"\\u002[fF]", "/", out)
    return out


def _is_junk_media(u: str) -> bool:
    low = (u or "").lower()
    return any(x in low for x in (
        "thumb", "preview", "sprite", "poster", "ads.",
        "_s_sample", "/sample/", "sample_", "trailer",
        "huntrexus.com",
    ))


def _collect_media(html: str, page_url: str) -> List[str]:
    found: List[str] = []

    def add(u: str):
        u = _abs(page_url, (u or "").strip().rstrip("\\").rstrip(","))
        if not u.startswith("http"):
            return
        if _is_junk_media(u):
            return
        low = u.lower()
        if (".m3u8" in low or ".mp4" in low) and u not in found:
            found.append(u)

    blob = _unescape(html)
    for m in _HLS_VAR_RE.finditer(blob):
        add(m.group(1))
    for m in _M3U8_RE.finditer(blob):
        add(m.group(0))
    for m in _MP4_RE.finditer(blob):
        add(m.group(0))
    return found


def _unpack_packed(html: str) -> str:
    """Dean Edwards packer used by StreamWish / FileMoon / javclan players."""
    m = re.search(
        r"eval\(function\(p,a,c,k,e,d\)\{[\s\S]*?\}\('(.*)',(\d+),(\d+),'(.*)'\.split\('\|'\)",
        html or "",
    )
    if not m:
        return ""
    payload, a, c, k = m.group(1), int(m.group(2)), int(m.group(3)), m.group(4).split("|")
    alphabet = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"

    def enc(n: int) -> str:
        if n == 0:
            return alphabet[0]
        s = ""
        while n:
            s = alphabet[n % a] + s
            n //= a
        return s

    out = payload
    for i in range(c - 1, -1, -1):
        if i < len(k) and k[i]:
            out = re.sub(r"\b" + re.escape(enc(i)) + r"\b", k[i], out)
    return _unescape(out)


def _searcho_real(html: str) -> Optional[str]:
    """jav.guru click-to-play gateway -> real /searcho/?xr=TOKEN iframe."""
    if "activate_real_stream" not in (html or ""):
        return None
    base = re.search(r"base:\s*'([^']+)'", html)
    rtype = re.search(r"rtype:\s*'([^']+)'", html)
    cid = re.search(r"cid:\s*'([^']+)'", html)
    km = re.search(r"keys:\s*\[([^\]]+)\]", html)
    if not (base and rtype and cid and km):
        return None
    keys = re.findall(r"'([^']+)'", km.group(1))
    dm = re.search(r'<div id="%s"([^>]*)>' % re.escape(cid.group(1)), html)
    if not dm:
        return None
    attrs = dict(re.findall(r'(data-[a-z0-9]+)="([^"]*)"', dm.group(1)))
    token = "".join(attrs.get(k, "") for k in keys)
    if not token:
        return None
    return base.group(1) + "?" + rtype.group(1) + "r=" + token[::-1]


def _parse_master(m3u8_url: str, referer: str = "") -> List[Dict]:
    text = ""
    ref = referer or m3u8_url
    try:
        from curl_cffi import requests as creq
        r = creq.get(
            m3u8_url,
            headers=_hdr(ref),
            impersonate="chrome",
            timeout=20,
            verify=False,
        )
        if r.status_code == 200:
            text = r.text or ""
    except Exception:
        try:
            import requests
            r = requests.get(
                m3u8_url,
                headers=_hdr(ref),
                timeout=20,
                verify=False,
            )
            if r.status_code == 200:
                text = r.text or ""
        except Exception:
            text = ""
    if not text or "#EXT-X-STREAM-INF" not in text:
        h = _height_from_text(m3u8_url, 720)
        return [{"height": h, "label": QLABEL.get(h, f"{h}p"), "url": m3u8_url}]

    qualities = []
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if "EXT-X-STREAM-INF" not in line:
            continue
        h = 720
        m = re.search(r"RESOLUTION=\d+x(\d+)", line)
        if m:
            h = int(m.group(1))
        if i + 1 < len(lines) and lines[i + 1] and not lines[i + 1].startswith("#"):
            u = urljoin(m3u8_url, lines[i + 1].strip())
            qualities.append({"height": h, "label": QLABEL.get(h, f"{h}p"), "url": u})
    if not qualities:
        h = _height_from_text(m3u8_url, 720)
        return [{"height": h, "label": QLABEL.get(h, f"{h}p"), "url": m3u8_url}]
    by_h = {}
    for q in qualities:
        by_h.setdefault(q["height"], q)
    return sorted(by_h.values(), key=lambda x: -x["height"])


def _b64_embeds(html: str) -> List[str]:
    out: List[str] = []

    def add(raw: str):
        raw = re.sub(r"\s+", "", raw or "")
        try:
            u = base64.b64decode(raw).decode("utf-8", "ignore").strip()
        except Exception:
            return
        if "&bg=" in u:
            u = u.split("&bg=")[0]
        if u.startswith("http") and u not in out and not any(a in u.lower() for a in _AD_HOST):
            out.append(u)

    for m in re.finditer(r'data-embed=["\']([A-Za-z0-9+/=\s]+)["\']', html or ""):
        add(m.group(1))
    for m in re.finditer(r'"iframe_url"\s*:\s*"([A-Za-z0-9+/=]+)"', html or ""):
        add(m.group(1))
    return out


def _javplayer_ids(html: str) -> List[str]:
    ids: List[str] = []
    for m in re.finditer(r"javplayer\.cc[/\\]+e[/\\]+([A-Za-z0-9]+)", html or "", re.I):
        if m.group(1) not in ids:
            ids.append(m.group(1))
    return ids


def _javplayer_stream(hash_id: str, referer: str = "") -> List[str]:
    api = f"https://javplayer.cc/stream?id={hash_id}"
    raw = _fetch_html(api, referer=referer or f"https://javplayer.cc/e/{hash_id}")
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except Exception:
        return []
    stream = ((data.get("media") or {}).get("stream") or "")
    return [stream] if str(stream).startswith("http") else []


def _page_embed_urls(html: str, page_url: str) -> List[str]:
    urls: List[str] = []
    for m in re.finditer(r'<iframe[^>]+src=["\']([^"\']+)', html or "", re.I):
        u = _abs(page_url, m.group(1))
        if not u.startswith("http"):
            continue
        if any(a in u.lower() for a in _AD_HOST):
            continue
        if u not in urls:
            urls.append(u)
    parsed = urlparse(page_url)
    m = re.search(r"/(\d{5,})/", parsed.path or "")
    if m and "/embed/" not in (parsed.path or "").lower() and parsed.hostname:
        # javhd.today uses /embed/{id}/; jav.guru does not — still cheap to try.
        urls.append(f"{parsed.scheme}://{parsed.hostname}/embed/{m.group(1)}/")
    for u in _b64_embeds(html or ""):
        if u not in urls:
            urls.append(u)
    return urls


def _media_from_html(html: str, page_url: str) -> List[str]:
    found = _collect_media(html, page_url)
    packed = _unpack_packed(html)
    if packed:
        for u in _collect_media(packed, page_url):
            if u not in found:
                found.append(u)
    return found


def _qualities_from_media(media: List[str], page_url: str) -> List[Dict]:
    m3u8s = [u for u in media if ".m3u8" in u.lower()]
    mp4s = [u for u in media if ".mp4" in u.lower() and ".m3u8" not in u.lower()]
    if m3u8s:
        master = next(
            (u for u in m3u8s if any(k in u.lower() for k in ("playlist", "index", "master", "urlset"))),
            m3u8s[0],
        )
        return _parse_master(master, referer=page_url)
    if mp4s:
        by_h = {}
        for u in mp4s:
            h = _height_from_text(u, 720)
            by_h.setdefault(h, {"height": h, "label": QLABEL.get(h, f"{h}p"), "url": u})
        return sorted(by_h.values(), key=lambda x: -x["height"])
    return []


def _fetch_player(url: str, referer: str) -> Tuple[Optional[str], str]:
    html = _fetch_html(url, referer=referer)
    if not html:
        return None, url
    real = _searcho_real(html)
    if real:
        html2 = _fetch_html(real, referer=referer or url)
        if html2:
            return html2, real
    return html, url


def _title_from_html(html: str, url: str) -> str:
    m = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)', html, re.I)
    if m:
        return m.group(1).strip()[:200]
    m = re.search(r"<title>([^<]+)</title>", html, re.I)
    if m:
        t = re.sub(r"\s*[-|].*$", "", m.group(1)).strip()
        return (t or m.group(1).strip())[:200]
    slug = urlparse(url).path.rstrip("/").split("/")[-1]
    return (slug.replace("-", " ") or "JAV Video")[:200]


def _thumb_from_html(html: str) -> Optional[str]:
    m = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)', html, re.I)
    if m:
        return m.group(1).strip()
    return None


def _ytdlp_extract(url: str) -> Optional[Dict]:
    try:
        cmd = [
            "yt-dlp", "-j", "--no-warnings", "--no-check-certificates",
            "--geo-bypass",
            "--add-header", f"User-Agent:{UA}",
            url,
        ]
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
        if p.returncode != 0 or not (p.stdout or "").strip():
            return None
        line = next((ln for ln in p.stdout.splitlines() if ln.strip().startswith("{")), "")
        if not line:
            return None
        data = json.loads(line)
        qualities = []
        for fmt in data.get("formats") or []:
            u = fmt.get("url") or ""
            proto = (fmt.get("protocol") or "").lower()
            ext = (fmt.get("ext") or "").lower()
            if not u:
                continue
            if "m3u8" not in proto and "m3u8" not in u and ext not in ("mp4", "m4v"):
                continue
            if _is_junk_media(u):
                continue
            h = int(fmt.get("height") or 0) or _height_from_text(u, 720)
            qualities.append({"height": h, "label": QLABEL.get(h, f"{h}p"), "url": u})
        by_h = {}
        for q in qualities:
            by_h.setdefault(q["height"], q)
        out = sorted(by_h.values(), key=lambda x: -x["height"])
        if not out:
            return None
        return {
            "title": (data.get("title") or "JAV Video")[:200],
            "thumbnail": data.get("thumbnail"),
            "duration": int(data.get("duration") or 0),
            "qualities": out,
            "headers": {"User-Agent": UA, "Referer": url, "Origin": f"{urlparse(url).scheme}://{urlparse(url).hostname}"},
            "webpage_url": url,
        }
    except Exception as e:
        logger.debug("jav yt-dlp extract: %s", e)
        return None


def extract_video_info(url: str) -> Optional[Dict]:
    try:
        url = (url or "").strip()
        if not url.startswith("http"):
            url = "https://" + url
        if not is_jav(url):
            return None

        html = _fetch_html(url)
        qualities: List[Dict] = []
        title = "JAV Video"
        thumb = None
        referer = url

        jp = re.search(r"/e/([A-Za-z0-9]+)", urlparse(url).path or "")
        if "javplayer" in _host(url) and jp:
            media = _javplayer_stream(jp.group(1), url)
            qualities = _qualities_from_media(media, url)

        if html:
            title = _title_from_html(html, url)
            thumb = _thumb_from_html(html)
            if not qualities:
                qualities = _qualities_from_media(_media_from_html(html, url), url)

            if not qualities:
                for hid in _javplayer_ids(html)[:3]:
                    media = _javplayer_stream(hid, url)
                    q = _qualities_from_media(media, f"https://javplayer.cc/e/{hid}")
                    if q:
                        qualities = q
                        referer = f"https://javplayer.cc/e/{hid}"
                        break

            if not qualities:
                seen = {url}
                queue = _page_embed_urls(html, url)
                for cand in queue[:8]:
                    if cand in seen:
                        continue
                    seen.add(cand)
                    ehtml, eurl = _fetch_player(cand, referer=url)
                    if not ehtml:
                        continue
                    q = _qualities_from_media(_media_from_html(ehtml, eurl), eurl)
                    if q:
                        qualities = q
                        referer = eurl
                        break
                    for extra in _b64_embeds(ehtml)[:5]:
                        if extra in seen:
                            continue
                        seen.add(extra)
                        shtml, surl = _fetch_player(extra, referer=url)
                        if not shtml:
                            continue
                        q = _qualities_from_media(_media_from_html(shtml, surl), surl)
                        if q:
                            qualities = q
                            referer = surl
                            break
                    if qualities:
                        break

        if not qualities:
            ytd = _ytdlp_extract(url)
            if ytd:
                return ytd
            return None

        parsed = urlparse(referer)
        origin = f"{parsed.scheme}://{parsed.hostname}"
        return {
            "title": title,
            "thumbnail": thumb,
            "duration": 0,
            "qualities": qualities,
            "headers": {"User-Agent": UA, "Referer": referer, "Origin": origin},
            "webpage_url": url,
        }
    except Exception as e:
        logger.error("jav extract error: %s", e, exc_info=True)
        return None
