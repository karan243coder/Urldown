# BIMBO URL Bot
# Powered by BIMBO
# Support: @Bimbo69

from pyrogram import Client as BimboBot
from pyrogram import filters, enums
from config import Config
from database.access import bimbo
from plugins.buttons import *

@BimboBot.on_message(filters.private & filters.command('total'))
async def sts(c, m):
    if m.from_user.id != Config.BIMBO_OWNER_ID:
        return 
    total_users = await bimbo.total_users_count()
    await m.reply_text(text=f"Total user(s) {total_users}", quote=True)


@BimboBot.on_message(filters.private & filters.command("search"))
async def serc(bot, update):

      await bot.send_message(chat_id=update.chat.id, text="🔍 TORRENT SEARCH", 
      parse_mode=enums.ParseMode.HTML, reply_markup=Button.BUTTONS01)
