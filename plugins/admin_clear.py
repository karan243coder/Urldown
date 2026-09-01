# -*- coding: utf-8 -*-
"""
Admin Clear Command - Clear all pending downloads and queues
Only owner/admin can use this command
"""
import os
import shutil
import logging
from pyrogram import Client, filters
from config import Config
from utils import is_admin
from database.users_chats_db import db

logger = logging.getLogger(__name__)


@Client.on_message(filters.command("clear") & filters.private)
async def clear_all_downloads(client, message):
    """
    Clear all pending downloads, queues, and temporary files
    Admin/Owner only command
    """
    user_id = message.from_user.id
    
    # Check if user is admin/owner
    if not is_admin(user_id):
        await message.reply_text(
            "❌ **Access Denied**\n\n"
            "Yeh command sirf Admin/Owner use kar sakte hain.\n\n"
            f"Your ID: `{user_id}`"
        )
        return
    
    try:
        await message.reply_text("🔄 **Clearing all downloads and queues...**")
        
        cleared_count = 0
        errors = []
        
        # 1. Clear xHamster queue from database
        try:
            if hasattr(db, 'db') and hasattr(db.db, 'xhamster_queue'):
                result = await db.db.xhamster_queue.delete_many({})
                cleared_count += result.deleted_count
                logger.info(f"Cleared {result.deleted_count} xHamster queue jobs")
        except Exception as e:
            errors.append(f"xHamster queue: {str(e)}")
            logger.error(f"Error clearing xHamster queue: {e}")
        
        # 2. Clear Eporner queue from database (if exists)
        try:
            if hasattr(db, 'db') and hasattr(db.db, 'eporner_queue'):
                result = await db.db.eporner_queue.delete_many({})
                cleared_count += result.deleted_count
                logger.info(f"Cleared {result.deleted_count} Eporner queue jobs")
        except Exception as e:
            errors.append(f"Eporner queue: {str(e)}")
            logger.error(f"Error clearing Eporner queue: {e}")
        
        # 3. Clear Terabox queue from database (if exists)
        try:
            if hasattr(db, 'db') and hasattr(db.db, 'terabox_queue'):
                result = await db.db.terabox_queue.delete_many({})
                cleared_count += result.deleted_count
                logger.info(f"Cleared {result.deleted_count} Terabox queue jobs")
        except Exception as e:
            errors.append(f"Terabox queue: {str(e)}")
            logger.error(f"Error clearing Terabox queue: {e}")
        
        # 4. Clear temporary download files
        try:
            download_dir = Config.BIMBO_DOWNLOAD_LOCATION
            if os.path.exists(download_dir):
                # Delete all files in download directory
                for item in os.listdir(download_dir):
                    item_path = os.path.join(download_dir, item)
                    try:
                        if os.path.isfile(item_path):
                            os.remove(item_path)
                        elif os.path.isdir(item_path):
                            shutil.rmtree(item_path)
                        cleared_count += 1
                    except Exception as e:
                        errors.append(f"File {item}: {str(e)}")
                        logger.error(f"Error deleting {item_path}: {e}")
                logger.info(f"Cleared temporary files from {download_dir}")
        except Exception as e:
            errors.append(f"Download directory: {str(e)}")
            logger.error(f"Error clearing download directory: {e}")
        
        # 5. Clear cookies.txt xHamster cookies (optional - refresh session)
        try:
            cookies_file = "cookies.txt"
            if os.path.exists(cookies_file):
                # Keep the file but log that it can be refreshed
                logger.info("Cookies file exists - can be refreshed if needed")
        except Exception as e:
            errors.append(f"Cookies file: {str(e)}")
            logger.error(f"Error checking cookies file: {e}")
        
        # Send summary
        summary = (
            f"✅ **Clear Complete!**\n\n"
            f"🗑️ **Cleared:** {cleared_count} items\n"
            f"📊 **xHamster queue:** Cleared\n"
            f"📊 **Eporner queue:** Cleared\n"
            f"📊 **Terabox queue:** Cleared\n"
            f"📁 **Temp files:** Deleted\n\n"
        )
        
        if errors:
            summary += f"⚠️ **Errors:** {len(errors)}\n"
            for error in errors[:5]:  # Show first 5 errors
                summary += f"• {error[:100]}\n"
        
        summary += "\n🎉 **Bot is now fresh and ready!**"
        
        await message.reply_text(summary)
        
    except Exception as e:
        logger.error(f"Error in clear command: {e}")
        await message.reply_text(
            f"❌ **Error:** {str(e)[:200]}\n\n"
            "Please check logs for details."
        )


@Client.on_message(filters.command("clearstats") & filters.private)
async def clear_stats(client, message):
    """
    Show clear statistics - Admin only
    """
    user_id = message.from_user.id
    
    if not is_admin(user_id):
        await message.reply_text("❌ Admin only command")
        return
    
    try:
        stats = []
        
        # Check xHamster queue
        if hasattr(db, 'db') and hasattr(db.db, 'xhamster_queue'):
            xh_count = await db.db.xhamster_queue.count_documents({})
            stats.append(f"📊 xHamster queue: {xh_count} jobs")
        
        # Check Eporner queue
        if hasattr(db, 'db') and hasattr(db.db, 'eporner_queue'):
            ep_count = await db.db.eporner_queue.count_documents({})
            stats.append(f"📊 Eporner queue: {ep_count} jobs")
        
        # Check download directory
        download_dir = Config.BIMBO_DOWNLOAD_LOCATION
        if os.path.exists(download_dir):
            items = os.listdir(download_dir)
            stats.append(f"📁 Temp files: {len(items)} items")
        
        if stats:
            await message.reply_text(
                "📊 **Current Queue Statistics:**\n\n" + 
                "\n".join(stats) +
                "\n\nUse `/clear` to clear all queues."
            )
        else:
            await message.reply_text("✅ All queues are empty!")
            
    except Exception as e:
        await message.reply_text(f"❌ Error: {str(e)[:200]}")
