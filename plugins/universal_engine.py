# -*- coding: utf-8 -*-
"""
Universal Video Extractor for BIMBO Bot
=======================================
Koi bhi website ka link do -> best-effort video nikaalne ki koshish.

STRATEGY (order):
  1) HTML scrape       -> page se seedha .mp4 / .m3u8 / og:video / JSON-LD /
                          <video>/<source> / inline JS me chhupe direct links
  2) iframe/embed dive -> agar page me embed iframe hai to uske andar bhi scan
  3) (fallback) yt-dlp  -> caller (youtube_dl_echo) khud yt-dlp try karta hai

IMPORTANT / HONEST LIMITS:
  - Har website support nahi hogi. Login/DRM/heavy-JS/captcha wali sites fail
    hongi. Ye 90%+ common sites cover karta hai, magic nahi hai.
  - Ye engine wahi API deta hai jo sxyprn_engine deta hai (extract_video_info),
    taaki bot ka baaki flow bina change ke chal jaye.

Returns dict:
  { title, thumbnail, duration, qualities:[{height,label,url}], headers, webpage_url }
or None.
"""

import re
import json
import base64
import logging
from urllib.parse import urlparse, urljoin
from typing import Optional, Dict, List

import requests
from bs4 import BeautifulSoup

# verify=False ki wajah se aane wali "InsecureRequestWarning" log spam band karo
try:
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except Exception:
    pass

logger = logging.getLogger(__name__)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")

QLABEL = {
    144: "144p", 240: "240p", 360: "360p", 480: "480p (SD)",
    720: "720p (HD)", 1080: "1080p (FHD)", 1440: "1440p (2K)", 2160: "2160p (4K UHD)",
}

# Video-ish direct file extensions we accept
_VIDEO_EXTS = (".mp4", ".m3u8", ".webm", ".mkv", ".mov", ".m4v", ".ts", ".mpd")

# Sites jinke apne dedicated engine ya better handling hai — universal skip kare,
# taaki wo pehle wale specialised path se hi chalein.
_SKIP_HOSTS = (
    "youtube.com", "youtu.be", "youtube-nocookie.com",
)


def is_universal_candidate(url: str) -> bool:
    """Universal ke liye eligible hai? (http/https aur skip-list me nahi)."""
    try:
        p = urlparse(url)
        if p.scheme not in ("http", "https") or not p.hostname:
            return False
        host = p.hostname.lower()
        return not any(h in host for h in _SKIP_HOSTS)
    except Exception:
        return False


def _clean_url(url: str) -> str:
    url = (url or "").strip()
    if not url.startswith("http"):
        url = "https://" + url
    return url


def _resolve_aggregator(url: str, session: "requests.Session") -> str:
    """
    Kuch sites (jaise qorno.com) khud video host nahi karti — wo ek redirect
    link deti hain jaise /out/?l=<base64> jo asli site (eporner/xhamster/etc.)
    pe le jaata hai. Yahan asli URL nikaalne ki koshish karo:
      1) base64 payload me chhupa http URL decode karo
      2) na mile to HTTP redirect follow karke final URL le lo
    """
    try:
        p = urlparse(url)
        # 1) base64-embedded target (qorno /out/?l=... , aur similar)
        from urllib.parse import parse_qs, unquote
        qs = parse_qs(p.query)
        for key in ("l", "u", "url", "link", "r", "to"):
            if key in qs and qs[key]:
                token = unquote(qs[key][0])
                # direct URL param
                if token.startswith("http"):
                    return token
                # base64 blob me chhupa http URL
                blob = token.replace("-", "+").replace("_", "/")
                for pad in range(4):
                    try:
                        d = base64.b64decode(blob + "=" * pad)
                        m = re.search(rb'https?://[^\x00-\x1f"\\\s]+', d)
                        if m:
                            return m.group(0).decode("utf-8", "ignore")
                    except Exception:
                        pass
        # 2) /out/ /go/ /away/ redirect endpoints -> follow HTTP redirect
        if any(seg in p.path.lower() for seg in ("/out", "/go", "/away", "/redirect", "/link")):
            r = session.get(url, timeout=20, allow_redirects=True, verify=False, stream=True)
            final = r.url
            try:
                r.close()
            except Exception:
                pass
            if final and urlparse(final).hostname != p.hostname:
                return final
    except Exception as e:
        logger.debug("aggregator resolve: %s", e)
    return url


def _abs(base: str, link: str) -> str:
    if not link:
        return link
    if link.startswith("//"):
        return "https:" + link
    return urljoin(base, link)


def _quality_from_url(u: str, default: int = 720) -> int:
    m = re.search(r"(2160|1440|1080|720|480|360|240|144)\s*[pP]?", u or "")
    if m:
        try:
            return int(m.group(1))
        except Exception:
            pass
    return default


# Preview/thumbnail clips — inhe SKIP karo warna 0.01 sec ka chhota video aata hai
_PREVIEW_HINTS = (
    "vidthumb", "thumb", "preview", "trailer", "teaser", "sample",
    "/prev/", "-prev", "promo", "sprite", "scrubbing", "poster",
    "/small.", "-small", "/tiny", "hover", "webp",
)


def _looks_like_video(u: str) -> bool:
    if not u:
        return False
    ul = u.lower()
    low = ul.split("?")[0]
    is_media = any(low.endswith(e) for e in _VIDEO_EXTS) or ".m3u8" in ul or ".mp4" in ul
    if not is_media:
        return False
    # Preview/thumbnail clip? -> reject (ye 1-2 sec ke chhote clips hote hain)
    if any(hint in ul for hint in _PREVIEW_HINTS):
        return False
    return True


def _fetch_impersonate(url: str, referer: str = None) -> Optional[str]:
    """
    Cloudflare/anti-bot (403/503) sites ke liye curl_cffi se browser
    impersonation karke page laao. curl_cffi na ho to None.
    """
    try:
        from curl_cffi import requests as creq
    except Exception:
        return None
    try:
        hdrs = {"User-Agent": UA,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9"}
        if referer:
            hdrs["Referer"] = referer
        r = creq.get(url, headers=hdrs, impersonate="chrome", timeout=25,
                     allow_redirects=True, verify=False)
        ct = (r.headers.get("Content-Type") or "").lower()
        if r.status_code == 200 and "text/html" in ct:
            return r.text
    except Exception as e:
        logger.debug("impersonate fetch failed: %s", e)
    return None


def _pack(html: str, base: str, url: str, vids: List[str]) -> Dict:
    """HTML + found video URLs -> standard info dict."""
    return {
        "title": (_title_from_html(html) or "Video")[:200],
        "thumbnail": _thumb_from_html(html),
        "duration": 0,
        "qualities": _build_qualities(vids),
        "headers": {"User-Agent": UA, "Referer": url},
        "webpage_url": url,
    }


def _new_session(referer: str) -> requests.Session:
    # NOTE: page fetch pe Referer NAHI bhejte — kuch server (w3.org etc.) apne
    # hi root referer ko suspicious maan ke 403 dete hain. Referer sirf video
    # download ke waqt chahiye (hotlink bypass), wo `headers` me alag jaata hai.
    s = requests.Session()
    s.headers.update({
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    })
    return s


# ------------------------------ scrapers ------------------------------
def _unescape_all(html: str) -> str:
    r"""
    JS/JSON me media URL aksar escaped hote hain:
      \/  -> /     \"...mp4\"  -> "...mp4"    \u002F -> /
    Regex scan se pehle unescape kar do, warna URL miss ho jaata hai
    (jaise hqporner -> mydaddy.cc iframe me \"//s1.bigcdn.cc/..360.mp4\").
    """
    if not html:
        return html
    out = html
    out = out.replace("\\/", "/").replace('\\"', '"').replace("\\'", "'")
    # unicode-escaped slashes
    out = re.sub(r"\\u002[fF]", "/", out)
    out = re.sub(r"\\x2[fF]", "/", out)
    return out


def _collect_from_html(html: str, base_url: str) -> List[str]:
    """Return list of candidate video URLs found in the HTML (raw + unescaped)."""
    found: List[str] = []

    def add(u):
        u = (u or "").strip().strip('"\'')
        if not u:
            return
        u = _abs(base_url, u)
        if _looks_like_video(u) and u not in found:
            found.append(u)

    soup = BeautifulSoup(html, "html.parser")

    # 1) <video src> and <video><source src>
    for v in soup.find_all("video"):
        add(v.get("src"))
        for attr in ("data-src", "data-video", "data-hls", "data-mp4"):
            add(v.get(attr))
        for src in v.find_all("source"):
            add(src.get("src"))

    # 2) Open Graph / twitter video meta
    for prop in ("og:video", "og:video:url", "og:video:secure_url", "twitter:player:stream"):
        for tag in soup.find_all("meta", attrs={"property": prop}) + soup.find_all("meta", attrs={"name": prop}):
            add(tag.get("content"))

    # 3) JSON-LD (schema.org VideoObject -> contentUrl)
    for s in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = json.loads(s.string or s.get_text() or "{}")
        except Exception:
            continue
        for obj in (data if isinstance(data, list) else [data]):
            if not isinstance(obj, dict):
                continue
            for key in ("contentUrl", "embedUrl"):
                if obj.get(key):
                    add(obj[key])

    # 4+5) Regex scan — RAW aur UNESCAPED dono par (JS-escaped URLs pakadne ke liye)
    media_re = re.compile(
        r'(?:https?:)?//[^\s"\'\\<>]+?\.(?:mp4|m3u8|webm|mkv|mov|m4v|mpd)(?:\?[^\s"\'\\<>]*)?',
        re.I)
    kv_re = re.compile(
        r'(?:file|src|source|url|hls|mp4|stream|videoUrl|video_url)["\']?\s*[:=]\s*'
        r'["\']((?:https?:)?//[^"\'\\<>\s]+?\.(?:mp4|m3u8|webm|mkv|mov|m4v|mpd)[^"\'\\<>\s]*)["\']',
        re.I)

    for variant in (html, _unescape_all(html)):
        for m in media_re.finditer(variant):
            add(m.group(0))
        for m in kv_re.finditer(variant):
            add(m.group(1))

    return found


def _find_iframes(html: str, base_url: str) -> List[str]:
    urls = []
    soup = BeautifulSoup(html, "html.parser")
    for f in soup.find_all("iframe"):
        src = f.get("src") or f.get("data-src")
        if src:
            u = _abs(base_url, src)
            if u.startswith("http") and u not in urls:
                urls.append(u)
    return urls


def _title_from_html(html: str) -> Optional[str]:
    soup = BeautifulSoup(html, "html.parser")
    t = soup.find("meta", property="og:title")
    if t and t.get("content"):
        return t["content"].strip()
    if soup.title and soup.title.string:
        return soup.title.string.strip()
    h1 = soup.find("h1")
    if h1:
        return h1.get_text(strip=True)
    return None


def _thumb_from_html(html: str) -> Optional[str]:
    soup = BeautifulSoup(html, "html.parser")
    for prop in ("og:image", "twitter:image"):
        t = soup.find("meta", property=prop) or soup.find("meta", attrs={"name": prop})
        if t and t.get("content"):
            return t["content"]
    return None


def _build_qualities(urls: List[str]) -> List[Dict]:
    seen = set()
    qs = []
    for u in urls:
        if u in seen:
            continue
        seen.add(u)
        h = _quality_from_url(u)
        qs.append({"height": h, "label": QLABEL.get(h, f"{h}p"), "url": u})
    # dedupe by height, keep first (best-scraped)
    by_h = {}
    for q in qs:
        by_h.setdefault(q["height"], q)
    out = sorted(by_h.values(), key=lambda x: -x["height"])
    return out


def extract_video_info(url: str, _depth: int = 0, _referer: str = None) -> Optional[Dict]:
    """
    Universal best-effort extraction. Returns sxyprn-style dict or None.
    _depth: internal (iframe recursion guard).
    _referer: parent page URL (embed hosts ko Referer chahiye hota hai).
    """
    try:
        url = _clean_url(url)
        if _depth == 0 and not is_universal_candidate(url):
            return None

        s = _new_session(url)
        # iframe/embed ke liye parent page ka Referer bhejo (kai embed host
        # bina sahi referer ke 403 dete hain, jaise hqporner -> mydaddy.cc).
        if _referer:
            s.headers["Referer"] = _referer

        # Aggregator/redirect site (jaise qorno.com /out/?l=...) ko asli video
        # URL me resolve karo, phir usi pe aage badho.
        resolved = _resolve_aggregator(url, s)
        if resolved and resolved != url:
            logger.info("universal: aggregator %s -> %s", url[:60], resolved[:80])
            url = resolved

        logger.info("universal: fetching %s (depth=%d)", url[:120], _depth)

        # Agar URL extension se hi direct video lagta hai, to poori file GET mat
        # karo — sirf HEAD se content-type confirm karo (bandwidth bachao).
        if _looks_like_video(url):
            try:
                hr = s.head(url, timeout=15, allow_redirects=True, verify=False)
                hct = hr.headers.get("Content-Type", "").lower()
                if (any(x in hct for x in ("video/", "octet-stream", "mpegurl"))
                        or _looks_like_video(hr.url)):
                    h = _quality_from_url(hr.url or url)
                    return {
                        "title": urlparse(hr.url or url).path.split("/")[-1] or "Video",
                        "thumbnail": None, "duration": 0,
                        "qualities": [{"height": h, "label": QLABEL.get(h, f"{h}p"),
                                       "url": hr.url or url}],
                        "headers": {"User-Agent": UA, "Referer": url},
                        "webpage_url": url,
                    }
            except Exception:
                pass  # HEAD fail -> normal page fetch try karo

        r = s.get(url, timeout=25, allow_redirects=True, verify=False, stream=True)
        ctype = r.headers.get("Content-Type", "").lower()

        # Redirect/URL khud direct video nikla
        if any(x in ctype for x in ("video/", "application/octet-stream", "mpegurl")):
            r.close()
            h = _quality_from_url(r.url)
            return {
                "title": urlparse(r.url).path.split("/")[-1] or "Video",
                "thumbnail": None, "duration": 0,
                "qualities": [{"height": h, "label": QLABEL.get(h, f"{h}p"), "url": r.url}],
                "headers": {"User-Agent": UA, "Referer": url},
                "webpage_url": url,
            }

        if r.status_code != 200 or "text/html" not in ctype:
            status = r.status_code
            r.close()
            # Cloudflare/anti-bot 403 -> curl_cffi impersonation se retry karo
            if status in (403, 429, 503):
                html2 = _fetch_impersonate(url, _referer)
                if html2:
                    base = url
                    html = html2
                    vids = _collect_from_html(html, base)
                    if vids:
                        return _pack(html, base, url, vids)
                    # iframe dive on impersonated html
                    if _depth < 2:
                        for ifr in _find_iframes(html, base)[:5]:
                            if any(b in ifr.lower() for b in ("ads","track","banner","/smartpop","popunder","doubleclick","syndication","google")):
                                continue
                            try:
                                sub = extract_video_info(ifr, _depth=_depth + 1, _referer=url)
                            except Exception:
                                sub = None
                            if sub and sub.get("qualities"):
                                sub["webpage_url"] = url
                                return sub
            logger.info("universal: non-HTML/failed (%s, %s)", status, ctype)
            return None

        # HTML hai — sirf pehla ~3MB padho (bahut badi page se bacho)
        html = r.raw.read(3 * 1024 * 1024, decode_content=True).decode(
            r.encoding or "utf-8", errors="ignore")
        base = r.url
        r.close()

        # ---- KVS player detect (freeporn8/sortporn/pornwhite/txxx/hclips/etc.) ----
        # In sites me HTML me jo video_url hota hai wo SCRAMBLED/decoy hota hai
        # (aksar ek GIF/37KB deta hai). Asli URL license_code se decode hota hai
        # jo yt-dlp ka KVS extractor achhe se karta hai. Isliye KVS page pe
        # universal scrape SKIP karo -> flow yt-dlp pe fall-through ho jayega.
        if _depth == 0 and ("license_code" in html or "kt_player" in html
                            or "kvs_player" in html or "flashvars" in html.lower()):
            logger.info("universal: KVS player detected -> yt-dlp ko dena behtar, skip")
            return None

        # 1) scrape this page
        vids = _collect_from_html(html, base)

        # 2) iframe dive (depth<=2) if nothing found — embed player me ghuso
        if not vids and _depth < 2:
            for ifr in _find_iframes(html, base)[:5]:
                # ad/tracker iframes skip karo
                if any(bad in ifr.lower() for bad in (
                        "ads", "track", "banner", "/smartpop", "popunder",
                        "doubleclick", "syndication", "disqus", "google")):
                    continue
                try:
                    sub = extract_video_info(ifr, _depth=_depth + 1, _referer=url)
                except Exception:
                    sub = None
                if sub and sub.get("qualities"):
                    # keep parent page as title/webpage; referer = embed page
                    sub["webpage_url"] = url
                    if not sub.get("title") or sub["title"] == "Video":
                        sub["title"] = _title_from_html(html) or sub.get("title") or "Video"
                    return sub

        if not vids:
            logger.info("universal: no video found on page")
            return None

        qualities = _build_qualities(vids)
        return {
            "title": (_title_from_html(html) or "Video")[:200],
            "thumbnail": _thumb_from_html(html),
            "duration": 0,
            "qualities": qualities,
            "headers": {"User-Agent": UA, "Referer": url},
            "webpage_url": url,
        }

    except Exception as e:
        logger.warning("universal extract error: %s", e)
        return None
