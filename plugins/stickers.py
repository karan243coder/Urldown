# -*- coding: utf-8 -*-
"""
BIMBO — Sticker helper (LadyCat, FIXED roles)
=============================================
Random nahi — har mood ke liye SPECIFIC LadyCat stickers set kiye gaye hain.

Sticker set: t.me/addstickers/LadyCat  (animated .tgs)
Local files: repo ke sticker/LadyCat-*/ folder me.

Index -> file mapping (grid ke hisaab se):
  index N  =>  file_16886{14+N}.tgs
  (#0=..614, #2=..616, #10=..624, #14=..628, #18=..632, #20=..634, #22=..636, #24=..638)

MOOD -> kaunse sticker (index):
  start   : #0, #6        (hi / blush+hearts — welcome)
  success : #2, #13, #22  (thumbs up / relieved / balloons — download done)
  error   : #14           (sad — fail)
  denied  : #18           (NO NO — ban/limit/forcesub)
  wait    : #20, #19      (meditation / wine — processing)
  thanks  : #24, #26      (heart hands / hearts)
  premium : #8, #21, #27  (gift / money — plans/vip)
  adult   : #4,#5,#9,#11,#12,#16,#17,#23,#25  (NSFW — adult site link aane par)
  night   : #15           (good night)
  fun     : #1, #7        (LOL / shrug)

Sab safe hai — sticker fail ho to bot normally chalta rahega.
"""

import os
import glob
import random
import asyncio
import logging

logger = logging.getLogger(__name__)

# Sticker kitne second baad auto-delete ho (config/env se, default 10s)
try:
    from config import Config
    AUTO_DELETE_SEC = int(getattr(Config, "AUTO_DELETE_SECONDS", 10) or 10)
except Exception:
    AUTO_DELETE_SEC = int(os.environ.get("AUTO_DELETE_SECONDS", "10") or 10)
if AUTO_DELETE_SEC < 1:
    AUTO_DELETE_SEC = 10


async def _auto_delete(msg, delay: int):
    """Sticker ko `delay` sec baad delete kar do (chup-chaap)."""
    try:
        await asyncio.sleep(delay)
        await msg.delete()
    except Exception:
        pass

# ---- LadyCat local folder ----
_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _find_ladycat_dir():
    # sticker/LadyCat-* folder dhundo (naam me timestamp hota hai)
    for d in glob.glob(os.path.join(_BASE, "sticker", "LadyCat*")):
        if os.path.isdir(d):
            return d
    return os.path.join(_BASE, "sticker", "LadyCat-1785312910379")


_DIR = _find_ladycat_dir()


def _f(idx: int) -> str:
    """index -> local .tgs path"""
    return os.path.join(_DIR, f"file_{1688614 + idx}.tgs")


# ---- MOOD -> list of indexes (FIXED, curated) ----
MOOD_INDEXES = {
    "start":   [0, 6],
    "success": [2, 13, 22],
    "done":    [2, 22],          # alias for success
    "error":   [14],
    "denied":  [18],
    "wait":    [20, 19],
    "thanks":  [24, 26],
    "premium": [8, 21, 27],
    "adult":   [4, 5, 9, 11, 12, 16, 17, 23, 25],
    "night":   [15],
    "fun":     [1, 7],
}

# Live sticker set fallback (agar local file kaam na kare)
SET_NAME = "LadyCat"

# Master switch (env se off kar sakte ho)
STICKERS_ENABLED = os.environ.get("BIMBO_STICKERS", "true").lower() not in (
    "0", "false", "no", "off"
)

_set_cache = None  # live set ke file_ids (order-wise)


async def _live_set_ids(client):
    global _set_cache
    if _set_cache is not None:
        return _set_cache
    ids = []
    try:
        stickers = await client.get_stickers(SET_NAME)
        ids = [s.file_id for s in stickers if getattr(s, "file_id", None)]
    except Exception as e:
        logger.debug("get_stickers(%s) failed: %s", SET_NAME, e)
    _set_cache = ids
    return ids


async def send_sticker(client, chat_id: int, mood: str = "start", reply_to: int = None):
    """
    Mood ke hisaab se ek FIXED (curated) LadyCat sticker bhejo.
    Ek mood me multiple ho to unme se ek random (par sirf usi mood ke andar).
    Fail ho to chup-chaap ignore.
    """
    if not STICKERS_ENABLED:
        return False
    idxs = MOOD_INDEXES.get(mood)
    if not idxs:
        return False
    idx = random.choice(idxs)
    try:
        # 1) local .tgs file (exact sticker — reliable)
        path = _f(idx)
        if os.path.exists(path):
            try:
                sent = await client.send_sticker(chat_id, path, reply_to_message_id=reply_to)
                # 10 sec baad auto-delete
                asyncio.create_task(_auto_delete(sent, AUTO_DELETE_SEC))
                return True
            except Exception as e:
                logger.debug("send_sticker(local #%d) failed: %s", idx, e)

        # 2) live set se (same index) — order set jaisa hi hota hai
        ids = await _live_set_ids(client)
        if ids and idx < len(ids):
            try:
                sent = await client.send_sticker(chat_id, ids[idx], reply_to_message_id=reply_to)
                asyncio.create_task(_auto_delete(sent, AUTO_DELETE_SEC))
                return True
            except Exception as e:
                logger.debug("send_sticker(set #%d) failed: %s", idx, e)
    except Exception as e:
        logger.debug("send_sticker error: %s", e)
    return False
