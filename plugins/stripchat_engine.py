# -*- coding: utf-8 -*-
# BIMBO — Stripchat LIVE Engine v1.0 (Premium Only)
# ==================================================
# Features:
#   /str <model|url>   -> live status card + record buttons (5/10/30 min + Until Stop)
#   /strtop [tag]      -> online models browse (girls/couples/guys/trans)
#   Record -> live progress card + Stop button -> auto remux -> Telegram upload
#
# Mouflon (v2) notes:
#   - pkey mast playlist se FREE milta hai (#EXT-X-MOUFLON:PSCH line). Koi key management nahi.
#   - Segment file NAMES encrypted hote hain (reverse + b64 + XOR sha256(pdkey)).
#   - pdkey owner ko dena hota hai (community tools ki tarah): file `stripchat_keys.txt`
#     ya env STRIPCHAT_PKEY / STRIPCHAT_PDKEY. Keys rotate hoti hain (player update pe).
#   - Keys na hon / stale hon toh status+browse CHALTA rahega, recording msg dega.
#
# Auto-cleaner: status/browse cards = menu 60s (click=reset) | recording/videos = KABHI delete nahi

import os
import re
import json
import time
import base64
import hashlib
import asyncio
import logging
import secrets
import itertools
from urllib.parse import urlparse

import aiohttp
from pyrogram import Client, filters
from pyrogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
)

from config import Config
from utils import (
    is_admin, is_premium, user_download_dir, cleanup_dir, humanbytes, get_url,
)

logger = logging.getLogger(__name__)

# ---------------- Config (env se, config.py touch nahi kiya) ----------------
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")
HEADERS_PAGE = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
HEADERS_JSON = {"User-Agent": UA, "Accept": "application/json"}
HEADERS_CDN = {"User-Agent": UA, "Referer": "https://stripchat.com/"}

STRIPCHAT_ENABLED = (os.environ.get("STRIPCHAT_ENABLED", "true").lower() != "false")
LIST_API = "https://stripchat.com/api/front/models"
CAM_API = "https://stripchat.com/api/front/v2/models/username/{u}/cam"
STATIC_CFG = (
    "https://hu.stripchat.com/api/front/v3/config/static",
    "https://stripchat.com/api/front/v3/config/static",
)
KEY_FILE = os.environ.get("STRIPCHAT_KEY_FILE", "stripchat_keys.txt")

MAX_CONCURRENT_REC = int(os.environ.get("STRIPCHAT_MAX_REC", "3") or "3")
PART_MAX_BYTES = int(os.environ.get("STRIPCHAT_PART_MAX", "1850000000") or "1850000000")
UNTIL_STOP_WALL_CAP = int(os.environ.get("STRIPCHAT_UNTIL_STOP_CAP_MIN", "180") or "180") * 60
PLAYLIST_POLL = 2.0          # live playlist refresh seconds
EDIT_EVERY = 8.0             # status card edit gap
MAX_PLAYLIST_FAILS = 8       # itni baar fail -> model offline maana

_TAGS = ("girls", "couples", "guys", "trans")
_PRELOAD_RE = re.compile(r"window\.__PRELOADED_STATE__\s*=\s*(\{.*?\})\s*</script>", re.S)


# ---------------- VIP gate (xhamster_wala pattern) ----------------
async def _str_vip_allowed(m: Message) -> bool:
    uid = m.from_user.id if m.from_user else 0
    if is_admin(uid):
        return True
    try:
        if await is_premium(uid):
            return True
    except Exception:
        pass
    return False


_STR_VIP_DENY_TEXT = (
    "🔒 **Stripchat Live Recorder Premium Only!** 💎\n\n"
    "Live cam recording server pe heavy hoti hai (bandwidth + upload), isliye "
    "ye feature sirf **Premium users** ya **Admin** ke liye hai.\n\n"
    "Premium lene ke liye owner se sampark karo: @bimbobot69"
)


# ---------------- version-safe command filter (repo pattern) ----------------
def _cmd(*names):
    names = [n.lower().lstrip("/") for n in names]

    def f(_flt, _client, m: Message):
        if not m or not getattr(m, "text", None):
            return False
        if m.media:
            return False
        t = (m.text or "").strip()
        if not t.startswith("/"):
            return False
        first = t.split()[0][1:].split("@")[0].lower()
        return first in names

    return filters.create(f)


# ---------------- small http helper ----------------
async def _aget(session: aiohttp.ClientSession, url: str, headers=None, timeout=25, binary=False):
    h = dict(HEADERS_PAGE)
    if headers:
        h.update(headers)
    try:
        async with session.get(url, headers=h, timeout=aiohttp.ClientTimeout(total=timeout),
                               allow_redirects=True) as r:
            if r.status != 200:
                return r.status, None
            data = await r.read()
            return r.status, (data if binary else data.decode("utf-8", "ignore"))
    except Exception as e:
        logger.debug(f"str: GET fail {url[:80]}: {e}")
        return 0, None


def _stripchat_model_from_input(text: str) -> str:
    """'ModelName' ya https://stripchat.com/ModelName -> model username"""
    t = (text or "").strip().strip("<>")
    if not t:
        return ""
    u = get_url(t) or ""
    if u:
        try:
            p = urlparse(u)
            if "stripchat" in (p.hostname or ""):
                seg = p.path.strip("/").split("/")
                if seg and seg[0]:
                    return seg[0]
        except Exception:
            pass
    if re.fullmatch(r"[A-Za-z0-9_\-.]{2,40}", t):
        return t
    return ""


# ---------------- online models (browse) ----------------
async def fetch_online_models(session: aiohttp.ClientSession, tag="girls", limit=40, offset=0):
    if tag not in _TAGS:
        tag = "girls"
    url = f"{LIST_API}?limit={limit}&offset={offset}&primaryTag={tag}"
    code, txt = await _aget(session, url, headers=HEADERS_JSON)
    if code != 200 or not txt:
        return [], 0
    try:
        d = json.loads(txt)
        return d.get("models", []) or [], int(d.get("totalCount", 0) or 0)
    except Exception:
        return [], 0


# ---------------- single model status ----------------
async def fetch_model_status(session: aiohttp.ClientSession, username: str):
    """Status dict: username,id,online,private,viewers,country,hd,vr,preview,cam_available.
    Kabhi exception nahi — fail pe {online:False, error:...}"""
    st = {
        "username": username, "id": 0, "online": False, "private": False,
        "viewers": 0, "country": "", "hd": False, "vr": False,
        "preview": "", "error": "",
    }
    # 1) cam detail api (show/private + streamName)
    uniq = secrets.token_hex(8)
    code, txt = await _aget(session, CAM_API.format(u=username) + f"?uniq={uniq}", headers=HEADERS_JSON)
    if code == 200 and txt:
        try:
            d = json.loads(txt)
            if (d or {}).get("error"):
                st["error"] = str(d["error"])
            cam = (d or {}).get("cam") or {}
            user = ((d or {}).get("user") or {}).get("user") or {}
            st["private"] = bool(cam.get("show"))
            st["cam_available"] = bool(cam.get("isCamAvailable"))
            try:
                st["id"] = int(cam.get("streamName") or 0)
            except Exception:
                st["id"] = 0
            if user:
                st["username"] = user.get("username") or username
        except Exception:
            pass
    # 2) models list se enrichment (viewers/preview/hd/country) + isLive fallback
    for tag in _TAGS:
        models, _ = await fetch_online_models(session, tag=tag, limit=60, offset=0)
        hit = next((x for x in models if str(x.get("username", "")).lower() == username.lower()), None)
        if hit:
            st["id"] = st["id"] or int(hit.get("id") or 0)
            st["online"] = bool(hit.get("isLive") or hit.get("isOnline"))
            st["viewers"] = int(hit.get("viewersCount") or 0)
            st["country"] = str(hit.get("country") or "").upper()
            st["hd"] = bool(hit.get("isHd"))
            st["vr"] = bool(hit.get("isVr"))
            st["preview"] = str(hit.get("previewUrlThumbSmall") or "")
            if hit.get("status") in ("private", "groupShow", "p2p", "virtualPrivate"):
                st["private"] = True
            break
    # 3) page PRELOADED fallback (isLive) — sabse reliable
    if not st["online"]:
        code, html = await _aget(session, f"https://stripchat.com/{username}")
        if code == 200 and html:
            m = _PRELOAD_RE.search(html)
            if m:
                try:
                    data = json.loads(m.group(1))
                except Exception:
                    data = json.loads(m.group(1).replace("\\'", "'"))
                vc = data.get("viewCam", {}) or {}
                md = vc.get("model", {}) or {}
                if md:
                    st["online"] = bool(md.get("isLive"))
                    st["id"] = st["id"] or int(md.get("id") or 0)
                if vc.get("show"):
                    st["private"] = True
    return st


# ================= MOUFLON (v2) =================
class MouflonError(Exception):
    pass


_KEY_CACHE = {"pkey": None, "pdkey": None, "ts": 0.0}


def _keys_from_env_or_file():
    """Owner-supplied keys. Format file: single line 'pkey:pdkey'."""
    pk = os.environ.get("STRIPCHAT_PKEY", "").strip()
    pd = os.environ.get("STRIPCHAT_PDKEY", "").strip()
    if pk and pd:
        return pk, pd
    try:
        if os.path.exists(KEY_FILE):
            line = open(KEY_FILE, encoding="utf-8").read().strip().splitlines()[0].strip()
            if ":" in line:
                pk, pd = (x.strip() for x in line.split(":", 1))
                if pk and pd:
                    return pk, pd
    except Exception:
        pass
    return None, None


def _xor_b64_rev_decode(encrypted_b64_reversed: str, pdkey: str) -> str:
    """Mouflon v2: encrypted part ko reverse karke b64 decode, phir XOR sha256(pdkey)."""
    hb = hashlib.sha256(pdkey.encode("utf-8")).digest()
    data = base64.b64decode(encrypted_b64_reversed[::-1] + "==")
    return bytes(a ^ b for a, b in zip(data, itertools.cycle(hb))).decode("utf-8")


def _decode_segment_uri(mouflon_uri: str, pdkey: str) -> str:
    """MOUFLON:URI line -> REAL full segment URL.
    enc part (2nd-last '_' token, reverse+XOR) ko decoded se replace karo."""
    enc = mouflon_uri.split("_")[-2]
    dec = _xor_b64_rev_decode(enc, pdkey)
    return mouflon_uri.replace(enc, dec)


def _extract_psch(master_text: str):
    """Master playlist se (psch_version, pkey). v2 prefer karo."""
    entries = []
    for line in master_text.splitlines():
        if line.strip().upper().startswith("#EXT-X-MOUFLON:PSCH"):
            parts = line.split(":")
            if len(parts) >= 2:
                entries.append((parts[-2].strip(), parts[-1].strip()))
    if not entries:
        return None, None
    for ver, pk in entries:
        if ver.lower() == "v2":
            return ver, pk
    return entries[0]


async def _autodiscover_pdkey(session, sample_enc_reversed: str):
    """Best-effort: purane Doppio/main.js style key pairs dhoondo + decode-validate.
    Chunks obfuscated hone pe kaam nahi karega — silent fail."""
    try:
        cache_ok = _KEY_CACHE["pdkey"] and (time.time() - _KEY_CACHE["ts"] < 3600)
        if cache_ok:
            return _KEY_CACHE["pdkey"]
        for cfg_url in STATIC_CFG:
            code, txt = await _aget(session, cfg_url, headers=HEADERS_JSON)
            if code != 200 or not txt:
                continue
            st = (json.loads(txt) or {}).get("static", {})
            fs = st.get("featureSettings", {}) or {}
            origin = fs.get("MMPExternalSourceOrigin") or "https://img.doppiocdn.com/player/mmp"
            ver = None
            f2 = st.get("featuresV2", {}) or {}
            ver = (f2.get("playerModuleExternalLoading") or {}).get("mmpVersion")
            if not ver:
                # config me nahi mila -> skip autodiscovery
                continue
            base = f"{origin}/{ver}" if str(ver).startswith("v") else f"{origin}/v{ver}"
            code, main_js = await _aget(session, f"{base}/main.js")
            if code != 200 or not main_js:
                continue
            candidates = []
            try:
                djs = re.findall(r'require[(]"./(Doppio.*?[.]js)"[)]', main_js)
                if djs:
                    _c, dop = await _aget(session, f"{base}/{djs[0]}")
                    if dop:
                        candidates.append(dop)
            except Exception:
                pass
            candidates.append(main_js)
            for blob in candidates:
                pairs = re.findall(r"\b([A-Za-z0-9]{12,}):([A-Za-z0-9]{12,})\b", blob)
                for _pk, pd in pairs:
                    try:
                        dec = _xor_b64_rev_decode(sample_enc_reversed, pd)
                        if re.fullmatch(r"[A-Za-z0-9\-_]{6,40}", dec or ""):
                            _KEY_CACHE.update(pkey=_pk, pdkey=pd, ts=time.time())
                            logger.info(f"str: pdkey autodiscovered via JS ({_pk[:6]}...)")
                            return pd
                    except Exception:
                        continue
    except Exception as e:
        logger.debug(f"str: autodiscover fail: {e}")
    return None


async def _get_pdkey(session, sample_enc_reversed: str):
    pk, pd = _keys_from_env_or_file()
    if pd:
        return pd, "file/env"
    pd = await _autodiscover_pdkey(session, sample_enc_reversed)
    if pd:
        return pd, "autodiscovery"
    raise MouflonError(
        "pdkey nahi mili. Owner ko `stripchat_keys.txt` (format: `pkey:pdkey`) "
        "ya env STRIPCHAT_PKEY/STRIPCHAT_PDKEY update karne honge."
    )


async def _playlist_and_keys(session, model_id: int):
    """Master playlist -> variant url + (psch, pkey). Returns (variant_url, psch, pkey)."""
    murl = f"https://edge-hls.doppiocdn.com/hls/{model_id}/master/{model_id}_auto.m3u8"
    code, master = await _aget(session, murl, headers=HEADERS_CDN)
    if code != 200 or not master:
        raise MouflonError(f"Master playlist nahi mili (HTTP {code}) — model offline/hidden ho sakti hai.")
    psch, pkey = _extract_psch(master)
    if not pkey:
        raise MouflonError("PSCH/pkey playlist me nahi mila.")
    variants = [l.strip() for l in master.splitlines() if l.strip().startswith("http")]
    if not variants:
        raise MouflonError("Master playlist me variants nahi mile.")
    return variants[0], psch, pkey  # source quality pehla hota hai


async def _fetch_live_segments(session, variant_url, psch, pkey, pdkey):
    """Live variant playlist fetch + decode -> (init_url, {seq: seg_url}, endlist: bool)"""
    sep = "&" if "?" in variant_url else "?"
    code, pl = await _aget(session, f"{variant_url}{sep}psch={psch}&pkey={pkey}", headers=HEADERS_CDN, timeout=15)
    if code != 200 or not pl:
        raise MouflonError(f"live playlist HTTP {code}")
    if "ENDLIST" in pl:
        return None, {}, True
    init_url, segs = None, {}
    last_real, last_seq = None, None
    for line in pl.splitlines():
        line = line.strip()
        if line.startswith("#EXT-X-MAP:"):
            m = re.search(r'URI="([^"]+)"', line)
            if m:
                init_url = m.group(1)
        elif line.startswith("#EXT-X-MOUFLON:URI:"):
            uri = line[len("#EXT-X-MOUFLON:URI:"):]
            try:
                last_real = _decode_segment_uri(uri, pdkey)
                sm = re.search(r"_(\d+)_", uri)
                last_seq = int(sm.group(1)) if sm else None
            except Exception:
                last_real, last_seq = None, None
        elif line.endswith("media.mp4") and last_real:
            # key = seq nahi to URL khud (dedup safe)
            segs[last_seq if last_seq is not None else last_real] = last_real
            last_real, last_seq = None, None
        elif line.startswith("http") and not line.endswith("media.mp4"):
            # non-mouflon plain segment (rare fallback)
            sm = re.search(r"_(\d+)_", line)
            segs[int(sm.group(1)) if sm else line] = line
    q = f"psch={psch}&pkey={pkey}"
    if init_url:
        init_url += ("&" if "?" in init_url else "?") + q
    segs = {k: v + ("&" if "?" in v else "?") + q for k, v in segs.items()}
    return init_url, segs, False


# ================= RECORDER =================
_RECS = {}            # rec_id -> dict(stop=Event, user_id, model, started)
_USER_ACTIVE = {}     # uid -> rec_id


def _fmt_dur(secs: int) -> str:
    secs = int(secs)
    return f"{secs//3600:02d}:{(secs%3600)//60:02d}:{secs%60:02d}"


async def _remux_to_mp4(src_path: str) -> str:
    """fMP4 (.m4s concat) -> proper .mp4 (stream copy). Fail -> original rename."""
    out = os.path.splitext(src_path)[0] + ".mp4"
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", src_path, "-c", "copy", "-movflags", "+faststart", out,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        _, err = await asyncio.wait_for(proc.communicate(), timeout=900)
        if proc.returncode == 0 and os.path.exists(out) and os.path.getsize(out) > 1024:
            try:
                os.remove(src_path)
            except Exception:
                pass
            return out
        logger.warning(f"str: ffmpeg remux fail: {(err or b'')[-200:]!r}")
    except Exception as e:
        logger.warning(f"str: remux exception: {e}")
    try:
        os.replace(src_path, out)
    except Exception:
        out = src_path
    return out


async def _upload_recording(client, status_msg, user, path, model, idx, total_parts):
    """Recorded file -> Telegram (repo pipeline style, lekin self-contained)."""
    uid = int(user.id)
    title = f"{model} LIVE {time.strftime('%d-%b %H:%M')}"
    try:
        from plugins.xhamster_upgrade import get_video_whd
        whd = await get_video_whd(path)
        width, height, duration = whd
    except Exception:
        width = height = duration = 0
    thumb = None
    try:
        from plugins.custom_thumbnail import Gthumb02

        class _FU:
            id = uid
            first_name = getattr(user, "first_name", "User")
            username = getattr(user, "username", None)

        class _UP:
            from_user = _FU()
            id = getattr(status_msg, "id", 0)
            message_id = id
            chat = getattr(status_msg, "chat", None)

        thumb = await Gthumb02(client, _UP(), max(duration, 1), path, task_id=f"strc_{uid}_{idx}")
    except Exception:
        thumb = None

    started = time.time()

    async def _prog(cur, tot):
        el = max(time.time() - started, 0.001)
        try:
            await status_msg.edit_text(
                f"📤 **Uploading…** `{humanbytes(cur)}/{humanbytes(tot)}` "
                f"({humanbytes(int(cur/el))}/s)\n🎬 {title}"
                + (f" [Part {idx}/{total_parts}]" if total_parts > 1 else "")
            )
        except Exception:
            pass

    size = os.path.getsize(path)
    caption = f"🎥 **{title}**\n🔴 Stripchat LIVE | ⚡ BIMBO"
    if total_parts > 1:
        caption += f" | Part {idx}/{total_parts}"
    sent = await client.send_video(
        chat_id=uid, video=path, caption=caption,
        duration=max(duration, 1), width=width or 0, height=height or 0,
        supports_streaming=True,
        thumb=thumb if thumb and os.path.exists(str(thumb)) else None,
        progress=_prog,
    )
    try:
        from plugins.user_quota import record_user_download
        record_user_download(uid, size)
    except Exception:
        pass
    # log channel (best-effort)
    try:
        if Config.BIMBO_LOG_CHANNEL:
            from plugins.youtube_dl_button import send_log_media
            await send_log_media(
                bot=client, user=user, file_path=path,
                link=f"https://stripchat.com/{model}",
                file_name=title, media_type="video",
                file_size=size, thumbnail=thumb,
                duration=duration, width=width, height=height,
            )
    except Exception:
        pass
    try:
        if thumb and os.path.exists(str(thumb)):
            os.remove(thumb)
    except Exception:
        pass
    return sent


async def _record_task(client, rec_id, uid, user, model, dur_seconds, status_msg):
    """Core recording loop: playlist poll -> naye segments append -> stop -> remux -> upload."""
    stop: asyncio.Event = _RECS[rec_id]["stop"]
    work = None
    parts_written = []
    try:
        work = os.path.join(user_download_dir(uid), rec_id)
        os.makedirs(work, exist_ok=True)
        async with aiohttp.ClientSession() as session:
            # fresh status -> model_id + online/private validation (click ke baad offline ho sakti hai)
            st = await fetch_model_status(session, model)
            if not st.get("id"):
                raise MouflonError("Model ka stream id nahi mila (offline/host change?).")
            if not st.get("online"):
                raise MouflonError("Model abhi online nahi dikh rahi. Baad me try karo.")
            if st.get("private"):
                raise MouflonError("Model private/group show me hai — public stream nahi hai.")
            model_id = int(st["id"])
            variant_url, psch, pkey = await _playlist_and_keys(session, model_id)
            # pehli playlist se ek sample enc nikaal ke pdkey resolve karo
            code, pl0 = await _aget(
                session,
                variant_url + ("&" if "?" in variant_url else "?") + f"psch={psch}&pkey={pkey}",
                headers=HEADERS_CDN, timeout=15,
            )
            if code != 200 or not pl0:
                raise MouflonError(f"Live playlist nahi khuli (HTTP {code})")
            if "ENDLIST" in pl0:
                raise MouflonError("Model abhi live nahi hai (sirf preview chal raha).")
            uris = [l for l in pl0.splitlines() if l.startswith("#EXT-X-MOUFLON:URI:")]
            if not uris:
                raise MouflonError("Mouflon segment nahi mila (format change?).")
            sample_enc = uris[0].split("_")[-2]
            pdkey, _src = await _get_pdkey(session, sample_enc)
            # validate pdkey actually decodes
            try:
                test_dec = _xor_b64_rev_decode(sample_enc, pdkey)
                if not re.fullmatch(r"[A-Za-z0-9\-_]{6,40}", test_dec or ""):
                    raise ValueError
            except Exception:
                raise MouflonError(
                    "pdkey stale/invalid lag rahi hai. Owner ko `stripchat_keys.txt` "
                    "update karwana hoga (pkey:pdkey)."
                )
            logger.info(f"str: rec {rec_id} start model={model} dur={dur_seconds} keysrc={_src}")

            started = time.time()
            deadline = (started + dur_seconds) if dur_seconds else (started + UNTIL_STOP_WALL_CAP)
            total_bytes = 0
            part_idx = 0
            cur_fh = None
            cur_path = None
            cur_bytes = 0
            done_keys = set()
            init_written = False
            fails = 0
            last_edit = 0.0

            def _open_part():
                nonlocal cur_fh, cur_path, cur_bytes, init_written
                cur_path = os.path.join(work, f"{model}_{rec_id[-6:]}_part{part_idx + 1:02d}.m4s")
                cur_fh = open(cur_path, "wb")
                cur_bytes = 0
                init_written = False

            def _close_part():
                nonlocal part_idx, cur_fh
                if cur_fh:
                    try:
                        cur_fh.close()
                    except Exception:
                        pass
                    if cur_path and os.path.exists(cur_path) and os.path.getsize(cur_path) > 1024:
                        parts_written.append(cur_path)
                        part_idx += 1
                    elif cur_path and os.path.exists(cur_path):
                        try:
                            os.remove(cur_path)
                        except Exception:
                            pass
                cur_fh = None

            async def _write_init():
                nonlocal cur_bytes, init_written
                if init_written or not init_url_global[0]:
                    return
                try:
                    _, data = await _aget(session, init_url_global[0], headers=HEADERS_CDN, binary=True)
                    if data:
                        cur_fh.write(data)
                        cur_bytes += len(data)
                        init_written = True
                except Exception:
                    pass

            _open_part()
            init_url_global = [None]
            offline = False
            while time.time() < deadline:
                if stop.is_set():
                    break
                try:
                    init_url, segs, endlist = await _fetch_live_segments(session, variant_url, psch, pkey, pdkey)
                    if init_url:
                        init_url_global[0] = init_url
                    fails = 0
                except Exception as e:
                    fails += 1
                    logger.debug(f"str: playlist poll fail ({fails}) {e}")
                    if fails >= MAX_PLAYLIST_FAILS:
                        offline = True
                        break
                    await asyncio.sleep(PLAYLIST_POLL)
                    continue
                if endlist:
                    offline = True
                    break
                if not init_written:
                    await _write_init()
                # naye segments (ints pehle sorted, phir koi str keys)
                ordered = sorted([k for k in segs if isinstance(k, int)]) + \
                          [k for k in segs if not isinstance(k, int)]
                for k in ordered:
                    if k in done_keys:
                        continue
                    if cur_bytes >= PART_MAX_BYTES:
                        _close_part()
                        _open_part()
                        await _write_init()
                    try:
                        _, data = await _aget(session, segs[k], headers=HEADERS_CDN, binary=True, timeout=30)
                        if data and len(data) > 100:
                            cur_fh.write(data)
                            done_keys.add(k)
                            total_bytes += len(data)
                            cur_bytes += len(data)
                    except Exception:
                        continue
                now = time.time()
                if now - last_edit >= EDIT_EVERY:
                    last_edit = now
                    el = int(now - started)
                    left = int(deadline - now) if dur_seconds else None
                    try:
                        await status_msg.edit_text(
                            f"🔴 **RECORDING: {model}**\n\n"
                            f"⏱ Elapsed: `{_fmt_dur(el)}`"
                            + (f" | ⏳ Left: `{_fmt_dur(left)}`\n" if left is not None else " | ♾ Until Stop\n")
                            + f"💾 Size: `{humanbytes(total_bytes)}` | 🧩 Parts: `{part_idx + (1 if cur_bytes else 0)}`\n"
                            f"📶 Avg: `{humanbytes(int(total_bytes/max(el,1)))}/s`\n\n"
                            f"⏹ Rokne ke liye Stop dabao:",
                            reply_markup=InlineKeyboardMarkup(
                                [[InlineKeyboardButton("⏹ STOP & UPLOAD", callback_data=f"str:stop:{rec_id}")]]
                            ),
                        )
                    except Exception:
                        pass
                if cur_fh:
                    try:
                        cur_fh.flush()
                    except Exception:
                        pass
                await asyncio.sleep(PLAYLIST_POLL)
            _close_part()
            reason = "🛑 stopped" if stop.is_set() else ("📴 model offline" if offline else "⏱ duration complete")
    except MouflonError as e:
        try:
            await status_msg.edit_text(f"❌ **Recording nahi ho payi:**\n{e}")
        except Exception:
            pass
        _cleanup(work)
        _RECS.pop(rec_id, None)
        _USER_ACTIVE.pop(uid, None)
        return
    except Exception as e:
        logger.exception("str: record task crash")
        try:
            await status_msg.edit_text(f"❌ **Recording error:** `{str(e)[:300]}`")
        except Exception:
            pass
        _cleanup(work)
        _RECS.pop(rec_id, None)
        _USER_ACTIVE.pop(uid, None)
        return

    # -------- finalize: remux + upload --------
    origin = getattr(status_msg, "reply_to_message", None) or status_msg
    if not parts_written:
        try:
            await status_msg.edit_text(
                f"⚠️ **{model}** — recording khatam ({reason}) par kuch capture nahi hua.\n"
                f"Possible: model ne stream jaldi band kar di."
            )
        except Exception:
            pass
        _cleanup(work)
        _RECS.pop(rec_id, None)
        _USER_ACTIVE.pop(uid, None)
        return
    final_files = []
    for i, p in enumerate(parts_written, 1):
        try:
            await status_msg.edit_text(f"🎞 **Finalizing…** Part {i}/{len(parts_written)} (remux)")
        except Exception:
            pass
        final_files.append(await _remux_to_mp4(p))
    ok = 0
    for i, path in enumerate(final_files, 1):
        try:
            await status_msg.edit_text(f"📤 **Uploading…** Part {i}/{len(final_files)}")
            await _upload_recording(client, status_msg, user, path, model, i, len(final_files))
            ok += 1
        except Exception as e:
            logger.exception("str: upload fail")
            try:
                from plugins.auto_cleaner import reply_clean
                await reply_clean(origin, f"❌ Part {i} upload fail: `{str(e)[:200]}`")
            except Exception:
                pass
    try:
        await status_msg.delete()
    except Exception:
        pass
    try:
        from plugins.auto_cleaner import reply_clean
        await reply_clean(
            origin,
            (f"✅ **{model}** — {ok}/{len(final_files)} part(s) uploaded ({reason}).")
            if ok else f"❌ **{model}** — upload fail hua ({reason}).",
        )
    except Exception:
        pass
    _cleanup(work)
    # upload phase tak guard active rakhna tha -> ab release
    _RECS.pop(rec_id, None)
    _USER_ACTIVE.pop(uid, None)


def _cleanup(work):
    if work:
        try:
            asyncio.create_task(cleanup_dir(work))
        except Exception:
            try:
                import shutil
                shutil.rmtree(work, ignore_errors=True)
            except Exception:
                pass


async def _start_recording(client, c: CallbackQuery, model: str, dur_seconds: int):
    uid = c.from_user.id
    if not STRIPCHAT_ENABLED:
        return await c.answer("Stripchat engine disabled hai (env STRIPCHAT_ENABLED=false).", show_alert=True)
    if uid in _USER_ACTIVE:
        return await c.answer("⚠️ Tumhari ek recording already chal rahi hai. Pehle wo Stop karo.", show_alert=True)
    if len(_RECS) >= MAX_CONCURRENT_REC:
        return await c.answer("⚠️ Server busy: max recordings chal rahi hain. Thodi der baad try karo.", show_alert=True)
    # Recording card = progress message (auto-cleaner se track NAHI karna)
    status_msg = await c.message.reply_text(f"⏳ **{model}** recording start ho rahi hai…")
    rec_id = f"strc_{uid}_{int(time.time())%100000}"
    _RECS[rec_id] = {"stop": asyncio.Event(), "user_id": uid, "model": model}
    _USER_ACTIVE[uid] = rec_id
    asyncio.create_task(_record_task(client, rec_id, uid, c.from_user, model, dur_seconds, status_msg))
    await c.answer("🔴 Recording start!")


# ================= UI: status card =================
def _card_caption(st: dict) -> str:
    if not st.get("online"):
        return (
            f"🔴 **Stripchat: {st['username']}**\n\n"
            f"📵 **Status:** Offline ya private\n"
            f"{'⏳ ' + str(st['viewers']) + ' viewers last seen' if st.get('viewers') else ''}\n\n"
            f"Model online hogi tab record ho payega. Refresh karke dekho."
        )
    badges = []
    if st.get("hd"):
        badges.append("HD")
    if st.get("vr"):
        badges.append("VR")
    badges.append("PUBLIC" if not st.get("private") else "PRIVATE 🔒")
    return (
        f"🔴 **Stripchat: {st['username']}**\n\n"
        f"📡 **LIVE** | 👀 `{st.get('viewers', 0)}` viewers | 🌍 `{st.get('country') or '??'}`\n"
        f"🏷 `{' | '.join(badges)}`\n\n"
        + ("⚠️ Private/group show chal raha hai — public stream nahi hai, record nahi hoga.\n"
           if st.get("private") else "⏺ Recording duration choose karo:")
    )


def _card_kb(st: dict):
    u = st["username"]
    rows = []
    if st.get("online") and not st.get("private"):
        rows.append([
            InlineKeyboardButton("⏺ 5 min", callback_data=f"str:rec:{u}:300"),
            InlineKeyboardButton("⏺ 10 min", callback_data=f"str:rec:{u}:600"),
            InlineKeyboardButton("⏺ 30 min", callback_data=f"str:rec:{u}:1800"),
        ])
        rows.append([InlineKeyboardButton("♾ Until Stop (Premium)", callback_data=f"str:rec:{u}:0")])
    rows.append([
        InlineKeyboardButton("🔄 Refresh", callback_data=f"str:card:{u}"),
        InlineKeyboardButton("✖️ Close", callback_data="str:close"),
    ])
    return InlineKeyboardMarkup(rows)


async def _send_status_card(client, m: Message, st: dict):
    caption = _card_caption(st)
    kb = _card_kb(st)
    bot_msg = None
    prev = st.get("preview") or ""
    if prev:
        try:
            bot_msg = await m.reply_photo(prev, caption=caption, reply_markup=kb)
        except Exception:
            bot_msg = None
    if bot_msg is None:
        bot_msg = await m.reply_text(caption, reply_markup=kb, disable_web_page_preview=True)
    try:
        from plugins.auto_cleaner import schedule_delete_menu
        await schedule_delete_menu(client, m, bot_msg)
    except Exception:
        pass
    return bot_msg


@Client.on_message(filters.private & _cmd("str", "strip", "stripchat"))
async def cmd_str_card(client: Client, m: Message):
    if not await _str_vip_allowed(m):
        return await m.reply_text(_STR_VIP_DENY_TEXT, disable_web_page_preview=True)
    parts = (m.text or "").split(None, 1)
    arg = parts[1] if len(parts) > 1 else ""
    if not arg and m.reply_to_message and m.reply_to_message.text:
        arg = m.reply_to_message.text
    model = _stripchat_model_from_input(arg)
    if not model:
        try:
            from plugins.auto_cleaner import reply_clean
            return await reply_clean(
                m,
                "Usage: `/str <model_name>` ya `/str https://stripchat.com/<model>`\n"
                "Browse ke liye: /strtop",
            )
        except Exception:
            return await m.reply_text("Usage: `/str <model_name>`")
    wait = await m.reply_text(f"🔍 **{model}** ka live status check ho raha hai…")
    async with aiohttp.ClientSession() as session:
        st = await fetch_model_status(session, model)
    try:
        await wait.delete()
    except Exception:
        pass
    await _send_status_card(client, m, st)


# ================= UI: browse top online =================
def _browse_text(models, tag, offset, total):
    txt = f"🔴 **Stripchat LIVE — {tag.upper()}** (total {total})\n\n"
    for i, mdl in enumerate(models, offset + 1):
        flags = (" HD" if mdl.get("isHd") else "") + (" VR" if mdl.get("isVr") else "")
        txt += (f"**{i}.** `{mdl.get('username')}` — 👀 {mdl.get('viewersCount', 0)}"
                f" | 🌍 {str(mdl.get('country') or '??').upper()}{flags}\n")
    txt += "\nModel pe tap karke uska status card kholo ⬇️"
    return txt


def _browse_kb(models, tag, offset, total, step=8):
    rows = []
    for mdl in models:
        rows.append([InlineKeyboardButton(
            f"🔴 {mdl.get('username')} ({mdl.get('viewersCount', 0)})",
            callback_data=f"str:card:{mdl.get('username')}",
        )])
    nav = []
    if offset > 0:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"str:pg:{tag}:{max(0, offset-step)}"))
    if offset + step < total and models:
        nav.append(InlineKeyboardButton("➡️ Next", callback_data=f"str:pg:{tag}:{offset+step}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(t.upper() if t != tag else f"✅ {t.upper()}",
                                      callback_data=f"str:pg:{t}:0") for t in _TAGS])
    rows.append([InlineKeyboardButton("✖️ Close", callback_data="str:close")])
    return InlineKeyboardMarkup(rows)


@Client.on_message(filters.private & _cmd("strtop", "strb", "strlive"))
async def cmd_str_top(client: Client, m: Message):
    if not await _str_vip_allowed(m):
        return await m.reply_text(_STR_VIP_DENY_TEXT, disable_web_page_preview=True)
    parts = (m.text or "").split(None, 1)
    tag = parts[1].strip().lower() if len(parts) > 1 else "girls"
    if tag not in _TAGS:
        tag = "girls"
    wait = await m.reply_text(f"🔍 Online {tag} models ho rahi hain…")
    async with aiohttp.ClientSession() as session:
        models, total = await fetch_online_models(session, tag=tag, limit=8, offset=0)
    try:
        await wait.delete()
    except Exception:
        pass
    if not models:
        try:
            from plugins.auto_cleaner import reply_clean
            return await reply_clean(m, f"❌ Abhi koi {tag} model online list nahi mili. Thodi der baad try karo.")
        except Exception:
            return await m.reply_text(f"❌ List nahi mili.")
    bot_msg = await m.reply_text(_browse_text(models, tag, 0, total),
                                 reply_markup=_browse_kb(models, tag, 0, total),
                                 disable_web_page_preview=True)
    try:
        from plugins.auto_cleaner import schedule_delete_menu
        await schedule_delete_menu(client, m, bot_msg)
    except Exception:
        pass


# ================= CALLBACKS =================
@Client.on_callback_query(filters.regex(r"^str:"))
async def str_callbacks(client: Client, c: CallbackQuery):
    data = c.data or ""
    try:
        if data == "str:close":
            try:
                await c.message.delete()
            except Exception:
                pass
            return await c.answer()
        if data.startswith("str:stop:"):
            rec_id = data.split(":", 2)[2]
            rec = _RECS.get(rec_id)
            # sirf owner ya admin rok sakta hai
            if rec and (c.from_user.id == rec.get("user_id") or is_admin(c.from_user.id)):
                rec["stop"].set()
                return await c.answer("🛑 Stop diya — finalize & upload hoga…", show_alert=False)
            return await c.answer("❌ Ye recording active nahi hai (already done?).", show_alert=True)
        if data.startswith("str:rec:"):
            # vip re-check
            uid = c.from_user.id
            if not (is_admin(uid) or await is_premium(uid)):
                return await c.answer(_STR_VIP_DENY_TEXT.split("\n")[0], show_alert=True)
            _, _, model, dur = data.split(":", 3)
            return await _start_recording(client, c, model, int(dur))
        if data.startswith("str:card:"):
            uid = c.from_user.id
            if not (is_admin(uid) or await is_premium(uid)):
                return await c.answer(_STR_VIP_DENY_TEXT.split("\n")[0], show_alert=True)
            model = data.split(":", 2)[2]
            await c.answer("🔄 Refresh…")
            async with aiohttp.ClientSession() as session:
                st = await fetch_model_status(session, model)
            caption = _card_caption(st)
            kb = _card_kb(st)
            try:
                await c.message.edit_caption(caption, reply_markup=kb)
            except Exception:
                try:
                    await c.message.edit_text(caption, reply_markup=kb, disable_web_page_preview=True)
                except Exception:
                    pass
            return
        if data.startswith("str:pg:"):
            uid = c.from_user.id
            if not (is_admin(uid) or await is_premium(uid)):
                return await c.answer(_STR_VIP_DENY_TEXT.split("\n")[0], show_alert=True)
            _, _, tag, off = data.split(":", 3)
            tag = tag if tag in _TAGS else "girls"
            offset = max(0, int(off))
            await c.answer()
            async with aiohttp.ClientSession() as session:
                models, total = await fetch_online_models(session, tag=tag, limit=8, offset=offset)
            if not models:
                return
            try:
                await c.message.edit_text(_browse_text(models, tag, offset, total),
                                          reply_markup=_browse_kb(models, tag, offset, total),
                                          disable_web_page_preview=True)
            except Exception:
                pass
            return
        await c.answer()
    except Exception as e:
        logger.debug(f"str: callback error: {e}")
        try:
            await c.answer(f"Error: {str(e)[:100]}", show_alert=True)
        except Exception:
            pass


def is_stripchat(url: str) -> bool:
    try:
        return "stripchat" in (urlparse(url).hostname or "").lower()
    except Exception:
        return False


logger.info(
    f"✅ stripchat_engine v1.0 loaded | premium-only | rec<= {MAX_CONCURRENT_REC} | "
    f"part<= {humanbytes(PART_MAX_BYTES)} | keyfile={KEY_FILE}"
)
