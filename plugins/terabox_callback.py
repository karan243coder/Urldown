import os
import logging
from plugins.terabox_engine import extract_terabox_info, download_terabox_file
from plugins.custom_thumbnail import add_watermark
from config import BIMBO_WATERMARK_TEXT, BIMBO_DOWNLOAD_DIR

logger = logging.getLogger(__name__)

async def terabox_call_back(bot, update):
    """Handle Terabox download callback"""
    try:
        # Extract URL from callback data
        url = update.data.split("|")[1]
        logger.info(f"Terabox callback for URL: {url}")
        
        # Send processing message
        processing_msg = await update.message.edit(
            "🔄 **Processing Terabox Link**\n\n"
            "Extracting file information...\n"
            "⏳ Please wait..."
        )
        
        # Extract file info
        file_info = extract_terabox_info(url)
        
        if not file_info or 'error' in file_info:
            error_msg = file_info.get('error', 'Unknown error') if file_info else 'Failed to extract info'
            error_type = file_info.get('error_type', 'unknown') if file_info else 'unknown'
            
            # Different error messages based on error type
            if error_type == 'config_missing':
                error_text = (
                    "❌ **Configuration Error**\n\n"
                    "Terabox cookie not configured.\n\n"
                    "📝 **How to fix:**\n"
                    "1. Login to Terabox in browser\n"
                    "2. Open DevTools (F12)\n"
                    "3. Go to Application → Cookies\n"
                    "4. Copy 'lang' and 'ndus' values\n"
                    "5. Set BIMBO_TERABOX_COOKIE in environment:\n"
                    "   `lang=en; ndus=YOUR_VALUE;`\n\n"
                    "Contact bot owner to configure this."
                )
            elif error_type == 'package_missing':
                error_text = (
                    "❌ **Package Not Installed**\n\n"
                    "TeraboxDL package is missing.\n\n"
                    "Contact bot owner to install:\n"
                    "`pip install terabox-downloader`"
                )
            else:
                error_text = (
                    f"❌ **Terabox Error**\n\n"
                    f"Failed to extract file info:\n"
                    f"`{error_msg}`\n\n"
                    "This might be due to:\n"
                    "• Invalid or expired link\n"
                    "• Invalid cookie configuration\n"
                    "• Terabox API issues\n"
                    "• File not accessible"
                )
            
            await processing_msg.edit(error_text)
            return
        
        # Update message with file info
        file_name = file_info['file_name']
        file_size = file_info['file_size']
        thumbnail = file_info.get('thumbnail', '')
        
        # Format file size
        if file_size:
            size_mb = file_size / (1024 * 1024)
            if size_mb >= 1024:
                size_text = f"{size_mb / 1024:.2f} GB"
            else:
                size_text = f"{size_mb:.2f} MB"
        else:
            size_text = "Unknown"
        
        await processing_msg.edit(
            f"📥 **Downloading from Terabox**\n\n"
            f"📁 File: `{file_name}`\n"
            f"📦 Size: {size_text}\n\n"
            f"⏳ Downloading...\n"
            f"Please wait, this may take a while."
        )
        
        # Download file
        download_dir = os.path.join(BIMBO_DOWNLOAD_DIR, str(update.from_user.id))
        os.makedirs(download_dir, exist_ok=True)
        
        terabox_instance = file_info.get('teraboxdl_instance')
        file_path = download_terabox_file(terabox_instance, file_info, download_dir)
        
        if not file_path:
            await processing_msg.edit(
                "❌ **Download Failed**\n\n"
                "Failed to download file from Terabox.\n"
                "Please try again later."
            )
            return
        
        # Update message
        await processing_msg.edit(
            f"✅ **Download Complete**\n\n"
            f"📁 File: `{file_name}`\n"
            f"📦 Size: {size_text}\n\n"
            f"🔄 Processing file...\n"
            f"Adding watermark and preparing upload..."
        )
        
        # Add watermark if configured
        if BIMBO_WATERMARK_TEXT:
            try:
                file_path = await add_watermark(file_path, BIMBO_WATERMARK_TEXT)
            except Exception as e:
                logger.warning(f"Failed to add watermark: {e}")
        
        # Upload to Telegram
        await processing_msg.edit(
            f"📤 **Uploading to Telegram**\n\n"
            f"📁 File: `{file_name}`\n"
            f"📦 Size: {size_text}\n\n"
            f"⏳ Uploading..."
        )
        
        try:
            # Send as document
            await bot.send_document(
                chat_id=update.message.chat.id,
                document=file_path,
                caption=f"📁 **{file_name}**\n\n"
                        f"📦 Size: {size_text}\n"
                        f"🔗 Source: Terabox\n\n"
                        f"✅ Downloaded by BIMBO Bot",
                thumb=thumbnail if thumbnail else None,
                reply_to_message_id=update.message.reply_to_message.message_id if update.message.reply_to_message else None
            )
            
            # Delete processing message
            await processing_msg.delete()
            
            logger.info(f"Successfully uploaded Terabox file: {file_name}")
            
        except Exception as e:
            logger.error(f"Upload error: {e}", exc_info=True)
            await processing_msg.edit(
                f"❌ **Upload Failed**\n\n"
                f"Error: `{str(e)}`\n\n"
                f"File downloaded but upload failed.\n"
                f"This might be due to:\n"
                f"• File too large for Telegram\n"
                f"• Network issues\n"
                f"• Telegram API errors"
            )
        
        finally:
            # Cleanup downloaded file
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
                    logger.info(f"Cleaned up downloaded file: {file_path}")
            except Exception as e:
                logger.warning(f"Failed to cleanup file: {e}")
    
    except Exception as e:
        logger.error(f"Terabox callback error: {e}", exc_info=True)
        try:
            await update.message.edit(
                f"❌ **Error**\n\n"
                f"An unexpected error occurred:\n"
                f"`{str(e)}`"
            )
        except:
            pass
