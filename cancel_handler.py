# Cancel handler for BIMBO Bot
from pyrogram import filters, Client
from pyrogram.types import Message
from helper_funcs.display_progress import cleanup_progress_state
import logging

logger = logging.getLogger(__name__)

@Client.on_message(filters.command("cancel"))
async def cancel_command(client: Client, message: Message):
    """Cancel all active progress for this user"""
    try:
        # Cancel all tasks from this message
        if message.reply_to_message:
            msg_id = message.reply_to_message.id
            cleanup_progress_state(msg_id)
            await message.reply_text("✅ **Cancelled!**")
        else:
            await message.reply_text("ℹ️ Reply to a progress message with /cancel to cancel it.")
    except Exception as e:
        logger.error(f"Cancel error: {e}")
        await message.reply_text("❌ Error cancelling task.")
