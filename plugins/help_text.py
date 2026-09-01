# BIMBO v4.0 — Help text (start command ab commands.py mein unified hai)
# Ye file sirf /help ke liye backup/alias ke roop me rakhi hai.
# Main /start aur /help commands plugins/commands.py mein handle ho rahe hain.
import logging
from pyrogram import Client, filters
from pyrogram import enums
from translation import Translation
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

logger = logging.getLogger(__name__)



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


@Client.on_message(filters.private & _cmd('about'))
async def about_user(bot, update):
    await bot.send_message(
        chat_id=update.chat.id,
        text=Translation.BIMBO_ABOUT_TEXT,
        reply_markup=Translation.BIMBO_ABOUT_BUTTONS,
        parse_mode=enums.ParseMode.HTML,
        disable_web_page_preview=True,
        reply_to_message_id=update.id
    )
