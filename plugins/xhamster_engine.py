# -*- coding: utf-8 -*-
# ============================================================
#  xHamster custom engine for Telegram bot
#  - no-cookie-first extraction with domain-scoped cookie fallback
#  - mirror fallback, request throttling, and HTTP 429 cooldown
#  - optional browser TLS impersonation through curl-cffi
# ============================================================

import re
import json
import html as html_lib
import logging
import os
import random
import threading
import time
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse, unquote, quote

import requests

try:
    from curl_cffi import requests as curl_requests
    HAS_CURL_CFFI = True
except ImportError:
    curl_requests = None
    HAS_CURL_CFFI = False

# Kept as a fallback for deployments that do not have curl-cffi yet.
try:
    import cloudscraper
    HAS_CLOUDSCRAPER = True
except ImportError:
    cloudscraper = None
    HAS_CLOUDSCRAPER = False

logger = logging.getLogger(__name__)

# ============================================================
#  User-Agents pool
# ============================================================
_UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
]

# Keep one identity for an entire extraction. Rotating the User-Agent between
# retries can invalidate an anti-bot session and create even more requests.
UA = _UA_POOL[0]

# ============================================================
#  Cookie policy
# ============================================================
# Never ship browser/session cookies in source code. Public videos are fetched
# without cookies first. An optional, private Netscape cookie file is only used
# as a fallback, and each cookie remains scoped to its original domain/path.

# ============================================================
#  Mirror domains (only real xhamster mirrors that serve same content)
# ============================================================
_MIRROR_HOSTS = [
    # xhamster2 currently uses a separate origin and is a useful fallback when
    # a shared cloud-host IP is throttled on the main Cloudflare hostname.
    "xhamster2.com",
    "xhamster3.com",
    "xhamster46.desi",
    "xhamster.com",
]

# Public CORS proxies are disabled by default: they are unreliable and sending
# private URLs/cookies through an unrelated third party is unsafe. Operators
# can explicitly enable them, but cookies are never forwarded to them.
_WEB_PROXIES = [
    lambda url: f"https://api.codetabs.com/v1/proxy?quest={quote(url, safe='')}",
    lambda url: f"https://api.allorigins.win/raw?url={quote(url, safe='')}",
    lambda url: f"https://corsproxy.io/?{quote(url, safe='')}",
]


def _env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


# Optional operator-controlled egress. Prefer an authenticated proxy that the
# bot owner is authorised to use; do not rotate random public proxies.
HTTP_PROXY = (
    os.environ.get("XH_HTTP_PROXY", "").strip()
    or os.environ.get("BIMBO_HTTP_PROXY", "").strip()
)
CF_WORKER_URL = os.environ.get("XH_WORKER_URL", "").strip()
ALLOW_PUBLIC_PROXIES = _env_bool("XH_ALLOW_PUBLIC_PROXIES", False)
WORKER_FORWARD_COOKIES = _env_bool("XH_WORKER_FORWARD_COOKIES", False)
ENV_COOKIE_HEADER = (
    os.environ.get("XHAMSTER_COOKIE_HEADER", "").strip()
    or os.environ.get("XH_COOKIE_HEADER", "").strip()
)

REQUEST_TIMEOUT = max(5, int(os.environ.get("XH_REQUEST_TIMEOUT", "20")))
WEB_PROXY_TIMEOUT = max(5, int(os.environ.get("XH_PROXY_TIMEOUT", "15")))
MIN_REQUEST_INTERVAL = max(0.0, float(os.environ.get("XH_MIN_REQUEST_INTERVAL", "1.25")))
RATE_LIMIT_COOLDOWN = max(10, int(os.environ.get("XH_429_COOLDOWN", "120")))

_REQUEST_GATE = threading.Lock()
_REQUEST_STATE_LOCK = threading.Lock()
_LAST_REQUEST_AT = 0.0
_HOST_COOLDOWNS = {}


def _random_ua():
    # Backwards-compatible helper used by a few call sites. Extraction itself
    # now chooses one UA once and reuses it.
    return random.choice(_UA_POOL)


def _new_session():
    if HAS_CURL_CFFI:
        session = curl_requests.Session(impersonate="chrome")
        backend = "curl-cffi"
    elif HAS_CLOUDSCRAPER:
        session = cloudscraper.create_scraper(
            browser={"browser": "chrome", "platform": "windows", "mobile": False}
        )
        backend = "cloudscraper"
    else:
        session = requests.Session()
        backend = "requests"
    return session, backend


def _throttle_request():
    global _LAST_REQUEST_AT
    with _REQUEST_GATE:
        wait = MIN_REQUEST_INTERVAL - (time.monotonic() - _LAST_REQUEST_AT)
        if wait > 0:
            time.sleep(wait)
        _LAST_REQUEST_AT = time.monotonic()


def _session_get(session, url, **kwargs):
    _throttle_request()
    if HTTP_PROXY and "proxies" not in kwargs:
        kwargs["proxies"] = {"http": HTTP_PROXY, "https": HTTP_PROXY}
    return session.get(url, **kwargs)


def _retry_after_seconds(response):
    value = (response.headers.get("Retry-After") or "").strip()
    if value.isdigit():
        return max(1, min(int(value), 3600))
    if value:
        try:
            seconds = int(parsedate_to_datetime(value).timestamp() - time.time())
            return max(1, min(seconds, 3600))
        except Exception:
            pass
    return RATE_LIMIT_COOLDOWN


def _mark_rate_limited(url, response):
    host = (urlparse(url).hostname or "").lower()
    seconds = _retry_after_seconds(response)
    with _REQUEST_STATE_LOCK:
        _HOST_COOLDOWNS[host] = time.monotonic() + seconds
    logger.warning("xhamster: 429 on %s; cooldown=%ss", host, seconds)


def _host_is_cooling_down(url):
    host = (urlparse(url).hostname or "").lower()
    with _REQUEST_STATE_LOCK:
        until = _HOST_COOLDOWNS.get(host, 0)
        if until and until <= time.monotonic():
            _HOST_COOLDOWNS.pop(host, None)
            return False
        return until > time.monotonic()

# ============================================================
#  xHamster detection
# ============================================================
_XH_BRANDS = (
    "xhamster", "xhms", "xhday", "xhvid", "xhwide", "xhwebcam",
    "xhopen", "xhtab", "xhtotal", "xh_official", "xhaccess", "xhmoon",
    "xhbig", "xhbranch", "xhchannel", "xhdate", "xhlease", "xhcdn",
)
_XH_TLDS = (
    ".com", ".desi", ".one", ".tv", ".pro", ".net", ".to",
    ".xxx", ".porn", ".sex", ".mobi", ".cc", ".org",
)

QLABEL = {
    144: "144p", 240: "240p", 360: "360p", 480: "480p (SD)",
    720: "720p (HD)", 1080: "1080p (FHD)", 1440: "1440p", 2160: "4K",
}


def is_xhamster(url: str) -> bool:
    try:
        host = (urlparse(str(url)).hostname or "").lower()
    except Exception:
        host = str(url or "").lower()
    host = re.sub(r"^(www|m|mobile|de|fr|es|it|pt|nl|ru|jp|en)\.", "", host)
    if "xhamster" in host:
        return True
    for brand in _XH_BRANDS:
        if host == brand or host.startswith(brand + ".") or f".{brand}." in host:
            return True
        for tld in _XH_TLDS:
            if host == brand + tld or host.endswith("." + brand + tld):
                return True
    if re.match(r"^xh[a-z0-9]{1,12}\.(com|desi|one|tv|pro|net|to|xxx|porn|cc)$", host):
        return True
    return False


def _clean_xhamster_page_url(url: str) -> str:
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


def _to_desktop(url: str) -> str:
    return re.sub(r"^(https?://(?:.+?\.)?)m\.", r"\1", str(url or "").strip())


def _base_of(url: str) -> str:
    try:
        p = urlparse(url)
        return f"{p.scheme}://{p.hostname}"
    except Exception:
        return "https://xhamster.com"


def _get_mirror_urls(url: str):
    url = _clean_xhamster_page_url(_to_desktop(url))
    try:
        parsed = urlparse(url)
        path = parsed.path
    except Exception:
        return [url]

    if "/videos/" not in path and "/movies/" not in path:
        return [url]

    mirror_urls = []
    seen = set()

    if url not in seen:
        mirror_urls.append(url)
        seen.add(url)

    for host in _MIRROR_HOSTS:
        mirror_url = f"https://{host}{path}"
        if mirror_url not in seen:
            mirror_urls.append(mirror_url)
            seen.add(mirror_url)

    # Deterministic order avoids repeatedly hitting random dead mirrors and
    # makes 429 cooldown behaviour predictable.
    return mirror_urls


def _normalize_html_for_urls(text: str) -> str:
    if not text:
        return ""
    out = html_lib.unescape(str(text))
    out = out.replace("\\/", "/").replace("\\u002F", "/").replace("\\u002f", "/")
    out = out.replace("\\u0026", "&").replace("\\u003D", "=").replace("\\u003d", "=")
    try:
        out2 = unquote(out)
        if out2 != out:
            out = out + "\n" + out2
    except Exception:
        pass
    return out


def _find_m3u8_candidates(text: str):
    text = _normalize_html_for_urls(text)
    candidates = []
    for m in re.finditer(r'https?://[^"\'\s<>]+?\.m3u8[^"\'\s<>]*', text, re.I):
        u = m.group(0).rstrip('\\,;)}]')
        if u not in candidates:
            candidates.append(u)
    return candidates


def _pick_best_master(candidates):
    if not candidates:
        return None
    def score(u):
        lu = u.lower()
        sc = 0
        if "_tpl_" in lu: sc += 100
        if "hls" in lu: sc += 40
        if "h264" in lu: sc += 30
        if "av1" in lu: sc += 10
        if "multi=" in lu: sc += 20
        if "/seg-" in lu: sc -= 100
        return sc
    return sorted(candidates, key=score, reverse=True)[0]


def _ytdlp_decipher():
    try:
        import yt_dlp
        from yt_dlp.extractor.xhamster import XHamsterIE
        ydl = yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True})
        ie = XHamsterIE()
        ie.set_downloader(ydl)
        def dec(u, fid="hls"):
            try:
                return ie._decipher_format_url(u, fid)
            except Exception:
                return None
        return dec
    except Exception as e:
        logger.warning("xhamster: yt-dlp decipher unavailable: %s", e)
        return None


def _extract_window_initials(html: str):
    if not html:
        return None
    idx = html.find("window.initials")
    if idx < 0:
        return None
    start = html.find("{", idx)
    if start < 0:
        return None
    depth = 0
    in_str = False
    quote = ""
    esc = False
    end = None
    for i in range(start, len(html)):
        ch = html[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == quote:
                in_str = False
            continue
        if ch in ('"', "'"):
            in_str = True
            quote = ch
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end is None:
        return None
    raw = html[start:end]
    try:
        return json.loads(raw)
    except Exception as e:
        logger.warning("xhamster: window.initials json load failed: %s", e)
        return None


def _walk_strings(obj):
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _walk_strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_strings(v)
    elif isinstance(obj, str):
        yield obj


def _walk_key_values(obj, path=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{path}.{k}" if path else str(k)
            yield p, k, v
            yield from _walk_key_values(v, p)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _walk_key_values(v, f"{path}[{i}]")


def _decipher_candidates(values):
    if not values:
        return None
    dec = _ytdlp_decipher()
    seen = set()
    cleaned = []
    for val in values:
        if not isinstance(val, str):
            continue
        val = _normalize_html_for_urls(val).strip().strip('"\'')
        if val and val not in seen:
            seen.add(val)
            cleaned.append(val)
    direct = []
    for val in cleaned:
        if ".m3u8" in val or "m3u8" in val.lower():
            direct.extend(_find_m3u8_candidates(val))
            if val.startswith("http") and ".m3u8" in val:
                direct.append(val)
    picked = _pick_best_master(direct)
    if picked:
        return picked
    if not dec:
        return None
    for val in cleaned:
        low = val.lower()
        looks_candidate = (
            re.fullmatch(r"[0-9a-fA-F]{40,}", val)
            or (val.startswith("http") and re.search(r"/[0-9a-fA-F]{40,}(?:[/,]|$)", val))
            or ("hls" in low and len(val) > 30)
        )
        if not looks_candidate:
            continue
        for fid in ("h264", "av1", "hls"):
            out = dec(val, fid)
            if out and ".m3u8" in out:
                return out
    return None


def _find_hls_from_initials(initials):
    if not isinstance(initials, dict):
        return None
    direct = []
    for val in _walk_strings(initials):
        if ".m3u8" in val or "m3u8" in val.lower():
            direct.extend(_find_m3u8_candidates(val))
            if val.startswith("http") and ".m3u8" in val:
                direct.append(val)
    picked = _pick_best_master(direct)
    if picked:
        return picked
    candidates = []
    priority = []
    for path, key, value in _walk_key_values(initials):
        p = path.lower()
        k = str(key).lower()
        if isinstance(value, str):
            if any(w in p for w in ("hls", "source", "sources", "h264", "av1", "fallback", "video")):
                candidates.append(value)
                if any(w in p for w in ("hls", "h264", "fallback")):
                    priority.append(value)
            elif k in ("url", "fallback", "src", "file") and len(value) > 30:
                candidates.append(value)
        elif isinstance(value, dict) and any(w in p for w in ("hls", "h264", "av1", "source", "sources")):
            for sv in _walk_strings(value):
                candidates.append(sv)
                priority.append(sv)
    out = _decipher_candidates(priority)
    if out:
        return out
    out = _decipher_candidates(candidates)
    if out:
        return out
    broad = [v for v in _walk_strings(initials) if len(v) > 40]
    return _decipher_candidates(broad)


def _heights_from_master(master_text: str):
    hs = set()
    for m in re.finditer(r"RESOLUTION=\d+x(\d+)", master_text or ""):
        hs.add(int(m.group(1)))
    return sorted(hs)


def _build_variant_url(master_url: str, height: int) -> str:
    u = master_url or ""
    u = u.replace(".av1.mp4.m3u8", ".h264.mp4.m3u8")
    u = u.replace("/av1/", "/h264/")
    u = u.replace(".av1.", ".h264.")
    if "_TPL_" in u:
        u = u.replace("_TPL_", f"{height}p")
    if f"{height}p" not in u and re.search(r"/[^/?]+\.h264\.mp4\.m3u8", u):
        u = re.sub(r"/[^/?]+\.h264\.mp4\.m3u8", f"/{height}p.h264.mp4.m3u8", u)
    return u


def _parse_cookie_lines(lines):
    """Parse Netscape cookies while preserving domain/path/expiry scope."""
    records = []
    for raw in lines:
        line = raw.strip()
        if line.startswith("#HttpOnly_"):
            line = line[len("#HttpOnly_"):]
        elif not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 7:
            parts = re.split(r"\s+", line, maxsplit=6)
        if len(parts) < 7:
            continue
        domain = parts[0].strip().lower()
        # Repair accidental Markdown domains from copied chat messages.
        md_domain = re.search(r"\[([^\]]+)\]", domain)
        if md_domain:
            domain = md_domain.group(1).lower()
        name = parts[5].strip()
        value = parts[6].strip()
        if not domain or not name:
            continue
        try:
            expires = int(parts[4])
        except (TypeError, ValueError):
            expires = 0
        records.append({
            "domain": domain,
            "include_subdomains": parts[1].strip().upper() == "TRUE" or domain.startswith("."),
            "path": parts[2].strip() or "/",
            "secure": parts[3].strip().upper() == "TRUE",
            "expires": expires,
            "name": name,
            "value": value,
        })
    return records


def _load_cookies(cookies_file=None):
    if not cookies_file:
        return []
    try:
        with open(cookies_file, "r", encoding="utf-8", errors="ignore") as f:
            records = _parse_cookie_lines(f)
        if records:
            logger.info("xhamster: loaded %d domain-scoped cookies from %s", len(records), cookies_file)
        return records
    except Exception as e:
        logger.warning("xhamster: cookie file load failed: %s", e)
        return []


def _cookie_header_for_url(cookie_records, url):
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    path = parsed.path or "/"
    secure = parsed.scheme.lower() == "https"
    now = int(time.time())
    matches = []
    for item in cookie_records or []:
        domain = item["domain"].lstrip(".")
        domain_ok = host == domain
        if item["include_subdomains"]:
            domain_ok = domain_ok or host.endswith("." + domain)
        if not domain_ok or not path.startswith(item["path"]):
            continue
        if item["secure"] and not secure:
            continue
        if item["expires"] and item["expires"] <= now:
            continue
        matches.append(item)

    # More-specific paths win when duplicate cookie names are present.
    matches.sort(key=lambda item: len(item["path"]), reverse=True)
    seen = set()
    parts = []
    for item in matches:
        if item["name"] in seen:
            continue
        seen.add(item["name"])
        parts.append(f'{item["name"]}={item["value"]}')

    # Raw header is an explicit operator opt-in. Keep it on first-party page
    # hosts only; never send it to the video CDN or a public proxy.
    if ENV_COOKIE_HEADER and "xhamster" in host and "xhcdn" not in host:
        parts.append(ENV_COOKIE_HEADER)
    return "; ".join(parts) if parts else None


def _candidate_video_urls_from_initials(initials, current_url):
    out = []
    def add_clean(cand):
        cand = _clean_xhamster_page_url(cand)
        if cand and is_xhamster(cand) and ("/videos/" in cand or "/movies/" in cand) and cand not in out:
            out.append(cand)
    def add(u):
        if not isinstance(u, str):
            return
        u = _normalize_html_for_urls(u).strip()
        for m in re.finditer(r"https?://[^\s<>\"']+", u):
            cand = m.group(0).strip().strip("`'\"<>[]()")
            cand = cand.replace("&amp;", "&")
            add_clean(cand)
    if isinstance(initials, dict):
        urls_node = initials.get("urls")
        for val in _walk_strings(urls_node):
            add(val)
        for path, key, val in _walk_key_values(initials):
            p = path.lower()
            if isinstance(val, str) and any(w in p for w in ("url", "link", "fallback", "canonical", "pagehidden")):
                add(val)
    cur = _clean_xhamster_page_url(current_url)
    add_clean(cur)
    try:
        parsed = urlparse(cur)
        path = parsed.path
        if "/videos/" in path or "/movies/" in path:
            for host in _MIRROR_HOSTS:
                add_clean(f"https://{host}{path}")
    except Exception:
        pass
    out = [u for u in out if "/my/favorites/" not in u and "/watch-later" not in u]
    return out


def _has_player_data(html):
    initials = _extract_window_initials(html)
    if not isinstance(initials, dict):
        return False, initials
    if isinstance(initials.get("videoModel"), dict):
        return True, initials
    try:
        if isinstance(initials.get("xplayerSettings", {}).get("sources"), dict):
            return True, initials
    except Exception:
        pass
    return False, initials


def _title_has_cjk_or_japanese(text):
    return any(
        ('\u3040' <= ch <= '\u30ff') or
        ('\u3400' <= ch <= '\u4dbf') or
        ('\u4e00' <= ch <= '\u9fff') or
        ('\uf900' <= ch <= '\ufaff')
        for ch in str(text or '')
    )


def _title_from_url_slug(page_url):
    try:
        slug = urlparse(page_url).path.rstrip('/').split('/')[-1]
        if not slug:
            return None
        parts = slug.split('-')
        if len(parts) > 1 and re.match(r'^(?:xh)?[A-Za-z0-9]{5,}$', parts[-1]):
            slug = '-'.join(parts[:-1])
        slug = unquote(slug).replace('-', ' ')
        slug = re.sub(r'\s+', ' ', slug).strip()
        if not slug:
            return None
        return slug.title()
    except Exception:
        return None


def _clean_title(title, page_url):
    title = html_lib.unescape(str(title or '')).strip()
    title = re.sub(r'\s+', ' ', title)
    slug_title = _title_from_url_slug(page_url)
    if (not title) or _title_has_cjk_or_japanese(title):
        title = slug_title or title or 'xHamster video'
    title = re.sub(r'[\x00-\x1f\x7f]+', ' ', title).strip()
    return title or 'xHamster video'


def _build_browser_headers(ua, page_url, page_base, cookie_header=None, media=False):
    if media:
        h = {
            "User-Agent": ua,
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": page_url,
            "Origin": page_base,
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "cross-site",
        }
    else:
        h = {
            "User-Agent": ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Cache-Control": "no-cache",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
        }
    if cookie_header:
        h["Cookie"] = cookie_header
    return h


def _extract_from_html(html, page_url, cookie_header=None, ua=None, session=None):
    base = _base_of(page_url)
    ua = ua or UA

    title = None
    duration = None
    initials = _extract_window_initials(html)
    if isinstance(initials, dict):
        vm = initials.get("videoModel")
        if isinstance(vm, dict):
            title = vm.get("title") or title
            if isinstance(vm.get("duration"), (int, float)):
                duration = int(vm["duration"])
    thumbnail = None
    if isinstance(initials, dict):
        vm = initials.get("videoModel")
        if isinstance(vm, dict):
            thumbnail = (
                vm.get("thumbURL")
                or vm.get("posterURL")
                or vm.get("thumb")
                or vm.get("previewURL")
            )
    if not thumbnail:
        tm_img = (
            re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\'](.*?)["\']', html, re.I)
            or re.search(r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\'](.*?)["\']', html, re.I)
            or re.search(r'"thumbURL"\s*:\s*"([^"]+)"', html, re.I)
            or re.search(r'"posterURL"\s*:\s*"([^"]+)"', html, re.I)
        )
        if tm_img:
            thumbnail = tm_img.group(1).replace("\\/", "/")
    if not title:
        tm = (
            re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\'](.*?)["\']', html, re.I)
            or re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
        )
        if tm:
            title = re.sub(r"\s+", " ", tm.group(1)).strip()

    candidates = _find_m3u8_candidates(html)
    master = _pick_best_master(candidates)
    if not master and isinstance(initials, dict):
        master = _find_hls_from_initials(initials)
    if not master:
        logger.warning("xhamster: master not found")
        return None

    heights = []
    owns_session = session is None
    manifest_session = session
    try:
        if manifest_session is None:
            manifest_session, _ = _new_session()
        # The signed CDN URL is enough for public streams. Do not leak page
        # cookies to xhcdn, and do not hammer the manifest after a 429.
        mh = _build_browser_headers(ua, page_url, base, media=True)
        r = _session_get(
            manifest_session, master, headers=mh,
            timeout=REQUEST_TIMEOUT, allow_redirects=True,
        )
        if r.status_code == 200:
            heights = _heights_from_master(r.text)
        elif r.status_code == 429:
            _mark_rate_limited(master, r)
        else:
            logger.info("xhamster: master status=%s; using URL qualities", r.status_code)
    except Exception as e:
        logger.warning("xh master fetch fail: %s", e)
    finally:
        if owns_session and manifest_session is not None:
            try:
                manifest_session.close()
            except Exception:
                pass

    if not heights:
        for m2 in re.finditer(r":(\d{3,4})p", master):
            heights.append(int(m2.group(1)))
        heights = sorted(set(heights))
    if not heights:
        heights = [144, 240, 480, 720]

    qualities = []
    for h in sorted(set(heights)):
        qualities.append({
            "height": h,
            "label": QLABEL.get(h, f"{h}p"),
            "m3u8": _build_variant_url(master, h),
        })

    return {
        "title": _clean_title(title, page_url),
        "duration": duration,
        "thumbnail": thumbnail,
        "webpage_url": page_url,
        "base": base,
        "master_m3u8": master,
        "qualities": qualities,
        "headers": {"User-Agent": ua, "Referer": page_url, "Origin": base},
    }


def _filter_xhamster_cookies(cookie_header):
    """Sirf xhamster-related cookies rakho, baaki hatao."""
    if not cookie_header:
        return None
    parts = cookie_header.split("; ")
    # Important xhamster cookies
    important = ["_id", "_cfg", "settings", "cookie_accept", "parental-control",
                 "uid", "x_csrf_token", "x_tgt", "x_viewes", "x_content_preference",
                 "h_v4_straight", "stats_src_last", "ff_thumb_offset", "recs_show_time",
                 "last_video_search", "search_last_list", "moments_listing",
                 "x_preroll"]
    filtered = []
    for part in parts:
        if "=" not in part:
            continue
        name = part.split("=", 1)[0].strip()
        if any(imp in name.lower() for imp in important):
            filtered.append(part)
        # Skip tracking/ad cookies
        elif any(skip in name.lower() for skip in ["_ga", "gads", "gpi", "cto_", "__g", "IDE", "TDID"]):
            continue
    result = "; ".join(filtered) if filtered else None
    if result:
        logger.info("xhamster: filtered cookies: %d (from %d total)", len(filtered), len(parts))
    return result


def _fetch_via_cf_worker(url, cookie_header=None):
    """Cloudflare Worker proxy se page fetch karo. FASTEST option!"""
    if not CF_WORKER_URL:
        return None

    worker_url = f"{CF_WORKER_URL}?url={quote(url, safe='')}"

    filtered_cookies = (
        _filter_xhamster_cookies(cookie_header)
        if WORKER_FORWARD_COOKIES else None
    )

    # Anonymous request first. Cookie forwarding requires an explicit opt-in
    # because the worker is outside this process' trust boundary.
    attempts = [False, True] if filtered_cookies else [False]

    for use_cookies in attempts:
        try:
            h = {"User-Agent": _random_ua()}
            if use_cookies and filtered_cookies:
                h["X-Forward-Cookies"] = filtered_cookies

            r = requests.get(worker_url, headers=h, timeout=WEB_PROXY_TIMEOUT, allow_redirects=True)

            if r.status_code == 200 and len(r.text) > 500:
                html_text = r.text

                # Check if xplayerSettings has actual data (not None)
                has_real_player = False
                if "xplayerSettings" in html_text:
                    # Check it's not "xplayerSettings": null
                    xps_match = re.search(r'"xplayerSettings"\s*:\s*(\{|\")', html_text)
                    if xps_match:
                        has_real_player = True

                if has_real_player:
                    logger.info("xhamster: CF WORKER SUCCESS with player data (cookies=%s, html_len=%d)",
                              use_cookies, len(html_text))
                    return html_text

                # Check if page requires login
                if "verify your age" in html_text or "must be logged in" in html_text:
                    if use_cookies:
                        logger.warning("xhamster: page requires login even with cookies")
                    else:
                        logger.info("xhamster: page requires login, will try with cookies")
                        continue  # Try with cookies

                # Has window.initials but no player - might still have m3u8
                if "window.initials" in html_text:
                    m3u8_check = re.findall(r'https?://[^\s\"<>]+\.m3u8', html_text)
                    if m3u8_check:
                        logger.info("xhamster: CF WORKER found m3u8 directly (cookies=%s)", use_cookies)
                        return html_text

                    # No player, no m3u8 - try with cookies if we haven't yet
                    if not use_cookies and filtered_cookies:
                        logger.info("xhamster: no player data without cookies, retrying with cookies")
                        continue

                # Return whatever we got
                if "xhamster" in html_text.lower():
                    logger.info("xhamster: CF worker returned xhamster page (cookies=%s, player=%s, html_len=%d)",
                              use_cookies, has_real_player, len(html_text))
                    return html_text

            elif r.status_code in (520, 521, 522, 523, 524):
                logger.warning("xhamster: CF worker origin error %d (cookies=%s)", r.status_code, use_cookies)
                continue
            elif r.status_code == 400:
                logger.warning("xhamster: CF worker got 400 (bad URL)")
                return None
            else:
                logger.warning("xhamster: CF worker status=%d len=%d", r.status_code, len(r.text))
                continue
        except Exception as e:
            logger.warning("xhamster: CF worker error: %s", str(e)[:80])
            return None

    return None


def _fetch_via_web_proxy(url, cookie_header=None):
    """Optional last-resort public proxy fetch; cookies are never forwarded."""
    if not ALLOW_PUBLIC_PROXIES:
        return None
    proxies = list(_WEB_PROXIES)
    random.shuffle(proxies)

    for proxy_fn in proxies:
        proxy_url = proxy_fn(url)
        try:
            # Use cloudscraper for proxy requests too
            if HAS_CLOUDSCRAPER:
                _s = cloudscraper.create_scraper(browser={"browser": "chrome", "platform": "windows", "mobile": False})
            else:
                _s = requests.Session()
            h = {"User-Agent": UA}
            r = _s.get(proxy_url, headers=h, timeout=WEB_PROXY_TIMEOUT, allow_redirects=True)
            _s.close()

            if r.status_code == 200 and len(r.text) > 500:
                html_text = r.text
                if "window.initials" in html_text or "xhamster" in html_text.lower():
                    logger.info("xhamster: web proxy SUCCESS via %s (html_len=%d)",
                              proxy_url[:60], len(html_text))
                    return html_text
                else:
                    logger.warning("xhamster: web proxy returned non-xhamster content")
            elif r.status_code == 200:
                logger.warning("xhamster: web proxy response too small (%d bytes)", len(r.text))
            else:
                logger.warning("xhamster: web proxy status=%d", r.status_code)
        except Exception as e:
            logger.warning("xhamster: web proxy error: %s", str(e)[:80])

    return None


def extract(url, cookies_file=None):
    """Extract a public xHamster page with conservative request behaviour.

    Strategy: anonymous request first, one domain-scoped cookie retry only when
    needed, then known mirrors. A 429 immediately cools down that hostname; it
    is never retried in a tight loop.
    """
    desktop = _clean_xhamster_page_url(_to_desktop(url))
    if not is_xhamster(desktop):
        logger.warning("xhamster: rejected non-xhamster URL")
        return None

    cookie_records = _load_cookies(cookies_file)
    mirror_urls = _get_mirror_urls(desktop)
    session, backend = _new_session()
    ua = UA
    best_html = None
    best_url = None
    best_cookie_header = None
    success = False

    logger.info(
        "xhamster: mirrors=%d cookie_records=%d backend=%s proxy=%s",
        len(mirror_urls), len(cookie_records), backend, "YES" if HTTP_PROXY else "NO",
    )

    try:
        # Phase 1: direct fetch. Never send cookies on the first request.
        for page_url in mirror_urls:
            page_url = _clean_xhamster_page_url(page_url)
            host = urlparse(page_url).hostname or "unknown"
            if _host_is_cooling_down(page_url):
                logger.info("xhamster: skipping %s (429 cooldown active)", host)
                continue

            cookie_header = _cookie_header_for_url(cookie_records, page_url)
            attempts = [(False, None)]
            if cookie_header:
                attempts.append((True, cookie_header))

            for using_cookies, request_cookie_header in attempts:
                # Cookie fallback is only useful after an anonymous 4xx/limited
                # page. A successful player page breaks before this retry.
                headers = _build_browser_headers(
                    ua, page_url, _base_of(page_url), request_cookie_header,
                )
                try:
                    response = _session_get(
                        session, page_url, headers=headers,
                        timeout=REQUEST_TIMEOUT, allow_redirects=True,
                    )
                except Exception as exc:
                    logger.warning("xhamster: fetch error %s: %s", host, str(exc)[:100])
                    break

                status = response.status_code
                final_url = _clean_xhamster_page_url(str(getattr(response, "url", page_url)))
                if status == 429:
                    _mark_rate_limited(page_url, response)
                    break
                if status in (400, 401, 403):
                    logger.warning(
                        "xhamster: status=%d host=%s cookies=%s",
                        status, host, using_cookies,
                    )
                    # Allow exactly one scoped-cookie fallback when available.
                    if not using_cookies and cookie_header:
                        continue
                    break
                if status != 200 or not response.text:
                    logger.info("xhamster: status=%d host=%s", status, host)
                    break
                if re.search(r'id=["\']videoClosed["\']', response.text, re.I):
                    logger.info("xhamster: closed/unavailable video on %s", host)
                    break

                has_player, _ = _has_player_data(response.text)
                if has_player:
                    logger.info(
                        "xhamster: direct success host=%s cookies=%s",
                        host, using_cookies,
                    )
                    best_html = response.text
                    best_url = final_url or page_url
                    best_cookie_header = request_cookie_header
                    success = True
                    break

                # Keep a limited page only if it contains useful extraction
                # data. This can still be enough when the m3u8 is in HTML.
                if best_html is None and (
                    "window.initials" in response.text or ".m3u8" in response.text
                ):
                    best_html = response.text
                    best_url = final_url or page_url
                    best_cookie_header = request_cookie_header
                logger.info(
                    "xhamster: limited page host=%s cookies=%s",
                    host, using_cookies,
                )
                if not using_cookies and cookie_header:
                    continue
                break

            if success:
                break

        # Phase 2: an operator-owned worker, if configured. Cookies stay local
        # unless XH_WORKER_FORWARD_COOKIES=true was explicitly set.
        if not success and CF_WORKER_URL:
            logger.info("xhamster: trying configured worker")
            for page_url in mirror_urls[:3]:
                worker_cookie = _cookie_header_for_url(cookie_records, page_url)
                html_text = _fetch_via_cf_worker(page_url, worker_cookie)
                if not html_text:
                    continue
                has_player, _ = _has_player_data(html_text)
                if has_player:
                    best_html = html_text
                    best_url = page_url
                    best_cookie_header = worker_cookie
                    success = True
                    break
                if best_html is None and (
                    "window.initials" in html_text or ".m3u8" in html_text
                ):
                    best_html = html_text
                    best_url = page_url

        # Phase 3: explicit opt-in only; no cookies are sent.
        if not success and ALLOW_PUBLIC_PROXIES:
            logger.warning("xhamster: trying opt-in public proxy fallback")
            for page_url in mirror_urls[:2]:
                html_text = _fetch_via_web_proxy(page_url)
                if not html_text:
                    continue
                has_player, _ = _has_player_data(html_text)
                if has_player or ".m3u8" in html_text:
                    best_html = html_text
                    best_url = page_url
                    success = has_player
                    break

        if not best_html:
            logger.error("xhamster: extraction fetch failed; all hosts unavailable/rate-limited")
            return None

        result = _extract_from_html(
            best_html, best_url, best_cookie_header, ua=ua, session=session,
        )
        if not result:
            logger.warning("xhamster: player data found but stream extraction failed")
        return result
    except Exception as exc:
        logger.exception("xhamster: unexpected extraction error: %s", exc)
        return None
    finally:
        try:
            session.close()
        except Exception:
            pass


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    u = sys.argv[1] if len(sys.argv) > 1 else None
    if not u:
        print("Usage: python xhamster_engine.py <url>")
        sys.exit(0)
    res = extract(u)
    if not res:
        print("FAIL")
    else:
        print("TITLE   :", res["title"])
        print("DURATION:", res["duration"])
        print("MASTER  :", res["master_m3u8"][:120])
        for q in res["qualities"]:
            print(f"  [{q['height']:>5}] {q['label']:14} {q['m3u8'][:100]}")
