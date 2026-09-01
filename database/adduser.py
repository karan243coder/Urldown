# BIMBO v4.0
import logging
from pyrogram import Client
from pyrogram.types import Message
from database.access import bimbo
from config import Config

logger = logging.getLogger(__name__)

LOG_TEXT_P = """#NewUser
ID - <code>{}</code>
Name - {}
Username - @{}
"""


async def AddUser(bot: Client, update: Message):
    try:
        if not update or not update.from_user:
            return
        uid = update.from_user.id
        name = (update.from_user.first_name or "") + " " + (update.from_user.last_name or "")
        username = update.from_user.username or ""
        if not await bimbo.is_user_exist(uid):
            await bimbo.add_user(uid, name=name.strip(), username=username)
            if Config.BIMBO_LOG_CHANNEL and Config.BIMBO_LOG_CHANNEL != 0:
                try:
                    await bot.send_message(
                        Config.BIMBO_LOG_CHANNEL,
                        LOG_TEXT_P.format(uid, update.from_user.mention, username or "n/a")
                    )
                except Exception as e:
                    logger.warning(f"New-user log failed: {e}")
        else:
            # update last active
            try:
                await bimbo.db.add_user(uid, name=name.strip(), username=username)
            except Exception:
                pass
    except Exception as e:
        logger.error(f"AddUser error: {e}")
