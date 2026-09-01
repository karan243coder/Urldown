# BIMBO Bot - Cancel Handler
# Kisi bhi progress message ke reply mein /cancel karne se task cancel ho jayega

from pyrogram import filters, Client
from pyrogram.types import Message
import logging
import os

logger = logging.getLogger(__name__)

# Store active processes for cancellation
active_processes = {}  # msg_id -> {'process': subprocess, 'file_paths': []}

def register_process(msg_id, process=None, file_paths=None):
    """Register a process for cancellation"""
    if msg_id not in active_processes:
        active_processes[msg_id] = {'process': process, 'file_paths': file_paths or []}
    else:
        if process:
            active_processes[msg_id]['process'] = process
        if file_paths:
            active_processes[msg_id]['file_paths'].extend(file_paths)

def unregister_process(msg_id):
    """Remove from tracking"""
    active_processes.pop(msg_id, None)

@Client.on_message(filters.command("cancel"))
async def cancel_command(client: Client, message: Message):
    """Cancel current task - reply to a progress message"""
    if message.reply_to_message:
        msg_id = message.reply_to_message.id
        proc_data = active_processes.get(msg_id)
        
        if proc_data and proc_data.get('process'):
            try:
                proc_data['process'].kill()
                await message.reply_text("✅ **Task cancelled!**")
            except:
                await message.reply_text("✅ **Task stopped!**")
            unregister_process(msg_id)
        else:
            await message.reply_text("ℹ️ No active task found for this message.")
    else:
        await message.reply_text("ℹ️ Reply to a progress message with /cancel to stop it.")
