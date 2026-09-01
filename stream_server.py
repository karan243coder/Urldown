# -*- coding: utf-8 -*-
# BIMBO — Stream Server
# ================================================================
# File-share-bot style video streaming.
#
# Bot jab /stream par ek video ko save karta hai, wo token banata hai aur
# MongoDB me {token -> chat_id, msg_id} store karta hai (24h TTL).
#
# Yeh server 2 cheezein deta hai:
#   GET /watch/<token>  -> HTML player page (browser me chal jaata hai)
#   GET /dl/<token>     -> actual video bytes (HTTP Range support => seeking
#                          + instant streaming, poora file download nahi hota)
#
# Website (urlbotwebsite.vercel.app) sirf is server ke /watch link ko
# embed/redirect karti hai — isse bot pe extra load nahi aata, aur link
# 24h baad MongoDB se auto-delete hote hi apne aap dead ho jaata hai.
#
# NOTE: iske liye bot ka HTTP port publicly reachable hona chahiye
#       (Koyeb/VPS pe hota hai). Config.BIMBO_STREAM_PUBLIC_URL set karo.
import asyncio
import logging
import mimetypes
import time

from aiohttp import web

from config import Config
from database.users_chats_db import db

logger = logging.getLogger(__name__)

# 1 MB chunks while piping from Telegram
CHUNK_SIZE = 1024 * 1024

# Koyeb free = 512MB RAM + 1 shared pyrogram session. Browser ek video ke liye
# 3-4 parallel range request bhejta hai — agar sab ek saath Telegram se stream
# karein to session choke ho ke "Broken pipe" aata hai. Isliye ek saath sirf
# limited streams chalne do; baaki thodi der wait karenge (queue).
_MAX_CONCURRENT_STREAMS = max(1, int(getattr(Config, "BIMBO_STREAM_MAX_CONCURRENT", 3) or 3))
_stream_sem = asyncio.Semaphore(_MAX_CONCURRENT_STREAMS)

# get_messages() ka result thodi der cache karo taaki har parallel/seek request
# pe dobara Telegram na poocha jaye (session pe load kam).
_msg_cache: dict = {}
_MSG_CACHE_TTL = 300  # 5 min


async def _cached_get_message(client, chat_id: int, msg_id: int):
    key = (chat_id, msg_id)
    now = time.time()
    hit = _msg_cache.get(key)
    if hit and (now - hit[1]) < _MSG_CACHE_TTL:
        return hit[0]
    message = await client.get_messages(chat_id, msg_id)
    _msg_cache[key] = (message, now)
    # cache ko chhota rakho
    if len(_msg_cache) > 256:
        for k in list(_msg_cache)[:64]:
            _msg_cache.pop(k, None)
    return message


def _player_html(token: str, title: str, dl_url: str) -> str:
    safe_title = (title or "Video").replace("<", "").replace(">", "")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{safe_title} — Bimbo Stream</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{ margin:0; background:#0b0b0f; color:#eee; font-family:system-ui,Segoe UI,Roboto,sans-serif; }}
  .wrap {{ max-width:960px; margin:0 auto; padding:16px; }}
  h1 {{ font-size:18px; font-weight:600; margin:12px 0; word-break:break-word; }}
  video {{ width:100%; border-radius:12px; background:#000; box-shadow:0 8px 30px rgba(0,0,0,.5); }}
  .row {{ display:flex; gap:10px; flex-wrap:wrap; margin-top:14px; }}
  a.btn {{ text-decoration:none; padding:10px 16px; border-radius:10px; font-weight:600;
           background:#6d28d9; color:#fff; }}
  a.btn.alt {{ background:#1f2937; }}
  .muted {{ color:#888; font-size:13px; margin-top:10px; }}
</style>
</head>
<body>
  <div class="wrap">
    <h1>{safe_title}</h1>
    <video controls autoplay playsinline preload="metadata" src="{dl_url}"></video>
    <div class="row">
      <a class="btn" href="{dl_url}" download>⬇️ Download</a>
    </div>
    <p class="muted">Powered by Bimbo • Link 1 din baad auto-expire ho jaata hai.</p>
  </div>
</body>
</html>"""


async def _get_doc_or_404(token: str):
    doc = await db.get_stream_link(token)
    if not doc:
        return None
    meta = doc.get("meta") or {}
    if not meta.get("chat_id") or not meta.get("msg_id"):
        return None
    return doc


async def watch_handler(request: web.Request):
    token = request.match_info.get("token", "")
    doc = await _get_doc_or_404(token)
    if not doc:
        return web.Response(status=404, text="Link expired ya invalid hai (24h auto-delete).")
    meta = doc.get("meta") or {}
    title = meta.get("file_name", "Video")
    base = _public_base(request)
    dl_url = f"{base}/dl/{token}"
    return web.Response(text=_player_html(token, title, dl_url), content_type="text/html")


async def dl_handler(request: web.Request):
    """Stream the Telegram file with HTTP Range support (seek + instant play)."""
    token = request.match_info.get("token", "")
    doc = await _get_doc_or_404(token)
    if not doc:
        return web.Response(status=404, text="Link expired ya invalid hai.")

    meta = doc.get("meta") or {}
    chat_id = int(meta["chat_id"])
    msg_id = int(meta["msg_id"])
    file_size = int(meta.get("file_size", 0) or 0)
    file_name = meta.get("file_name", "video.mp4")
    mime = meta.get("mime_type") or mimetypes.guess_type(file_name)[0] or "application/octet-stream"

    client = request.app["bot"]

    # Fetch the message (cached) to get an up-to-date media object
    try:
        message = await _cached_get_message(client, chat_id, msg_id)
    except Exception as e:
        # Broken pipe / connection = temporary, 503 do taaki browser retry kare
        if "Broken pipe" in str(e) or "Connection" in str(e):
            return web.Response(status=503, text="Server busy, thodi der me retry hoga.")
        logger.warning(f"stream get_messages: {e}")
        return web.Response(status=502, text="Source unavailable.")
    if not message or not (message.video or message.document or message.audio or message.animation):
        return web.Response(status=404, text="Media not found.")

    media = message.video or message.document or message.audio or message.animation
    if not file_size:
        file_size = int(getattr(media, "file_size", 0) or 0)

    # ---- Parse Range header ----
    range_header = request.headers.get("Range", "")
    start = 0
    end = file_size - 1 if file_size else None
    status = 200
    if range_header and file_size:
        try:
            units, rng = range_header.split("=", 1)
            s, _, e = rng.partition("-")
            start = int(s) if s else 0
            end = int(e) if e else file_size - 1
            end = min(end, file_size - 1)
            status = 206
        except Exception:
            start, end = 0, file_size - 1

    length = (end - start + 1) if (file_size and end is not None) else None

    headers = {
        "Content-Type": mime,
        "Accept-Ranges": "bytes",
        "Content-Disposition": f'inline; filename="{file_name}"',
    }
    if file_size:
        headers["Content-Length"] = str(length if length is not None else file_size)
        if status == 206:
            headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"

    resp = web.StreamResponse(status=status, headers=headers)
    # prepare() ke waqt agar client (browser) pehle hi disconnect ho gaya
    # (seek / tab band / parallel range) to "closing transport" error aata hai.
    # Ye normal hai — chup-chaap ignore karo, log ganda na ho.
    try:
        await resp.prepare(request)
    except (ConnectionError, ConnectionResetError):
        return resp
    except Exception:
        # aiohttp ke ClientConnectionResetError etc bhi yahin aa jaayenge
        return resp

    # Pyrogram stream_media supports offset (in 1MB chunks). We compute the
    # chunk offset and trim the first/last chunk to honour the byte range.
    offset_chunk = start // CHUNK_SIZE
    first_cut = start - (offset_chunk * CHUNK_SIZE)
    bytes_to_send = length if length is not None else file_size
    sent = 0
    # Semaphore: ek saath sirf N streams. Baaki yahan wait karenge — isse
    # session choke nahi hota aur Broken pipe cascade ruk jaata hai.
    async with _stream_sem:
        try:
            async for chunk in client.stream_media(message, offset=offset_chunk):
                if first_cut:
                    chunk = chunk[first_cut:]
                    first_cut = 0
                if bytes_to_send is not None and sent + len(chunk) > bytes_to_send:
                    chunk = chunk[: bytes_to_send - sent]
                if not chunk:
                    break
                try:
                    await resp.write(chunk)
                except (ConnectionError, ConnectionResetError, RuntimeError):
                    break  # browser disconnected — chup-chaap ruk jao
                sent += len(chunk)
                if bytes_to_send is not None and sent >= bytes_to_send:
                    break
        except (ConnectionResetError, ConnectionError, RuntimeError, asyncio.CancelledError):
            pass  # client closed the tab / seeked — bilkul normal
        except OSError:
            # [Errno 32] Broken pipe etc — Telegram/client disconnect, ignore
            pass
        except Exception as e:
            s = str(e)
            if "closing transport" not in s and "Connection" not in s and "Broken pipe" not in s:
                logger.warning(f"stream pipe: {e}")
        finally:
            try:
                await resp.write_eof()
            except Exception:
                pass
    return resp


def _public_base(request: web.Request) -> str:
    base = getattr(Config, "BIMBO_STREAM_PUBLIC_URL", "") or ""
    if base:
        return base.rstrip("/")
    # Fall back to request host (works when hit directly)
    scheme = request.headers.get("X-Forwarded-Proto", request.scheme)
    host = request.headers.get("X-Forwarded-Host", request.host)
    return f"{scheme}://{host}"


async def health_handler(request: web.Request):
    return web.Response(text="OK - BIMBO Stream Server")


async def favicon_handler(request: web.Request):
    # Browser hamesha /favicon.ico maangta hai — 204 de do taaki 404 shor na ho.
    return web.Response(status=204)


async def start_stream_server(bot, port: int):
    """Start the aiohttp streaming server bound to the running bot client."""
    # aiohttp ke access/server logs bahut shor karte hain (har range request +
    # har client disconnect). Sirf warnings+ dikhao.
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
    logging.getLogger("aiohttp.server").setLevel(logging.CRITICAL)
    # asyncio ka "socket.send() raised exception" spam band karo (ye sirf
    # disconnected clients ke liye aata hai, koi asli error nahi).
    logging.getLogger("asyncio").setLevel(logging.CRITICAL)
    # pyrogram session ka "Retrying ... Broken pipe" spam kam karo.
    logging.getLogger("pyrogram.session.session").setLevel(logging.ERROR)

    app = web.Application()
    app["bot"] = bot
    app.router.add_get("/", health_handler)
    app.router.add_get("/favicon.ico", favicon_handler)
    app.router.add_get("/watch/{token}", watch_handler)
    app.router.add_get("/dl/{token}", dl_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"✅ Stream server listening on port {port} (/watch, /dl)")
    return runner
