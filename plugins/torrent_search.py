# BIMBO v4.0 — Simple Torrent Search (1337x + YTS)
# Returns magnet links (actual torrent download libtorrent pe depend karega,
# lekin magnet links user kisi bhi client me daal sakte hain)
import re
import asyncio
import urllib.parse
import logging

import aiohttp
from bs4 import BeautifulSoup
from pyrogram import Client, filters
from pyrogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton,
)

from config import Config

logger = logging.getLogger(__name__)

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/125 Safari/537.36"}

# 1337x mirrors in order of preference
_1337_MIRRORS = [
    "https://www.1377x.to",
    "https://1337x.to",
    "https://1337x.st",
    "https://x1337x.ws",
]

_YTS_URL = "https://yts.mx"


async def _fetch(session, url, **kw):
    try:
        async with session.get(url, headers=HEADERS, ssl=False, timeout=aiohttp.ClientTimeout(total=20), **kw) as r:
            return r.status, await r.text()
    except Exception as e:
        logger.warning(f"fetch fail {url}: {e}")
        return 0, ""


async def search_1337x(query: str, limit=10):
    timeout = aiohttp.ClientTimeout(total=25)
    async with aiohttp.ClientSession(timeout=timeout) as s:
        for base in _1337_MIRRORS:
            url = f"{base}/search/{urllib.parse.quote(query)}/1/"
            code, html = await _fetch(s, url)
            if code != 200 or not html:
                continue
            soup = BeautifulSoup(html, "lxml")
            table = soup.find("table", class_="table-list")
            if not table:
                continue
            results = []
            rows = table.find_all("tr")[1:]
            for row in rows[:limit]:
                try:
                    cols = row.find_all("td")
                    if len(cols) < 6: continue
                    name_a = cols[0].find_all("a")[-1]
                    name = name_a.text.strip()
                    href = name_a.get("href", "")
                    seed = cols[1].text.strip()
                    leech = cols[2].text.strip()
                    size = cols[4].text.strip()  # 1337x col order: cat, name, seed, leech, date, size
                    # Some mirrors order differs; safer regex
                    size_match = re.search(r"\d+[\d.]*\s*[KMGT]B", cols[4].text + " " + cols[5].text, re.I)
                    size = size_match.group(0) if size_match else size
                    # Need to fetch torrent page for magnet
                    link = base + href if href.startswith("/") else href
                    results.append({"name": name, "link": link, "seed": seed,
                                    "leech": leech, "size": size, "src": "1337x"})
                except Exception as e:
                    logger.debug(f"1337 row parse: {e}")
            # fetch magnets for first 5 (avoid too many requests)
            for res in results[:5]:
                try:
                    rc2, h2 = await _fetch(s, res["link"])
                    if rc2 == 200:
                        m = re.search(r'href="(magnet:\?xt=urn:btih:[^"]+)"', h2)
                        if m:
                            res["magnet"] = m.group(1).replace("&amp;", "&")
                except Exception:
                    pass
            return results
    return []


async def search_yts(query: str, limit=10):
    try:
        url = f"{_YTS_URL}/api/v2/list_movies.json?query_term={urllib.parse.quote(query)}&limit={limit}"
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as s:
            code, data = await _fetch(s, url)
            if code != 200:
                return []
            import json
            j = json.loads(data)
            movies = j.get("data", {}).get("movies") or []
            out = []
            for mv in movies:
                for t in mv.get("torrents", [])[:2]:  # limit per movie
                    q = t.get("quality", "")
                    typ = t.get("type", "")
                    name = f"{mv.get('title_long','')} [{q} {typ}]"
                    out.append({
                        "name": name,
                        "seed": str(t.get("seeds", 0)),
                        "leech": str(t.get("peers", 0)),
                        "size": t.get("size", ""),
                        "magnet": t.get("url", ""),
                        "src": "YTS",
                    })
            return out
    except Exception as e:
        logger.warning(f"yts search error: {e}")
        return []



# ============== Cross-version safe command filter ==============
def _cmd(*names):
    names = [n.lower().lstrip("/") for n in names]
    def f(_flt, _client, m):
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


@Client.on_message(filters.private & _cmd('torrentsearch', 'ts', 'tsearch'))
async def tsearch_cmd(client: Client, m: Message):
    if not Config.TORRENT_SEARCH_ENABLED:
        return await m.reply_text("Torrent search disabled by admin.")
    parts = (m.text or "").split(None, 1)
    if len(parts) < 2:
        return await m.reply_text("Usage: <code>/ts movie name</code>")
    q = parts[1]
    msg = await m.reply_text(f"🔍 Searching for `{q}`...")
    try:
        yts, x13 = await asyncio.gather(search_yts(q, limit=5), search_1337x(q, limit=5))
        results = yts + x13
        if not results:
            return await msg.edit_text("❌ No results found.")
        text = f"🔍 **Results for** `{q}`\n\n"
        kb = []
        for i, r in enumerate(results[:10], 1):
            text += f"**{i}.** {r['name'][:60]}\n"
            text += f"   🌱 {r['seed']}  📤 {r['leech']}  💾 {r['size']}  [{r['src']}]\n\n"
            if r.get("magnet"):
                # Inline button with magnet link
                kb.append([InlineKeyboardButton(f"{i}. {r['name'][:35]}", url=r["magnet"])])
        kb.append([InlineKeyboardButton("✖️ Close", callback_data="close")])
        text += "⬇️ Neeche button se magnet link open hoga (uTorrent/qBittorrent me paste karna)."
        await msg.edit_text(text, reply_markup=InlineKeyboardMarkup(kb), disable_web_page_preview=True)
    except Exception as e:
        logger.exception("tsearch")
        await msg.edit_text(f"❌ Error: <code>{e}</code>")
