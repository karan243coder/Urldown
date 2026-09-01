import os
import json
import random
from datetime import datetime
from pyrogram import filters, Client, enums
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from config import BIMBO_OWNER_ID, BIMBO_DATABASE_URL
from plugins.premium import premium_manager
from database.access import bimbo
import logging
import asyncio
import aiohttp
from io import BytesIO
from PIL import Image

logger = logging.getLogger(__name__)

ADMIN_DATA_FILE = "admin_data.json"
IMAGES_FOLDER = "images/"

def load_admin_data():
    try:
        if os.path.exists(ADMIN_DATA_FILE):
            with open(ADMIN_DATA_FILE, 'r') as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Load admin data error: {e}")
    
    return {
        'channels': [],
        'banned_users': [],
        'custom_messages': {},
        'settings': {
            'force_sub': False,
            'maintenance_mode': False
        },
        'images': {
            'progress': [],
            'start': '',
            'local_folder': IMAGES_FOLDER
        },
        'pending_actions': {}  # user_id -> action type
    }

def save_admin_data(data):
    try:
        with open(ADMIN_DATA_FILE, 'w') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.error(f"Save admin data error: {e}")

admin_data = load_admin_data()

# ── Image helper functions ──
def get_progress_images():
    return admin_data.get('images', {}).get('progress', [])

def set_progress_images(images_list):
    if 'images' not in admin_data:
        admin_data['images'] = {}
    admin_data['images']['progress'] = images_list
    save_admin_data(admin_data)

def get_start_pic():
    return admin_data.get('images', {}).get('start', '')

def set_start_pic(url):
    if 'images' not in admin_data:
        admin_data['images'] = {}
    admin_data['images']['start'] = url
    save_admin_data(admin_data)

def get_image_folder():
    return admin_data.get('images', {}).get('local_folder', IMAGES_FOLDER)

def set_image_folder(path):
    if 'images' not in admin_data:
        admin_data['images'] = {}
    admin_data['images']['local_folder'] = path
    save_admin_data(admin_data)

def get_random_progress_image():
    """Get a random progress image from admin panel settings."""
    images = get_progress_images()
    folder = get_image_folder()
    
    all_sources = list(images)
    
    # Check local folder
    if folder and os.path.isdir(folder):
        try:
            files = [f for f in os.listdir(folder) 
                     if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')) 
                     and not f.startswith('.')]
            if files:
                all_sources.extend([os.path.join(folder, f) for f in files])
        except Exception:
            pass
    
    if not all_sources:
        return None
    
    return random.choice(all_sources)

def ensure_images_folder():
    """Make sure the images folder exists"""
    folder = get_image_folder()
    os.makedirs(folder, exist_ok=True)
    return folder

async def download_photo_to_folder(client, photo, folder):
    """Download photo from Telegram to local folder. Returns local path or None.
    photo can be: Photo object, Document object, or file_id string"""
    try:
        # Get file extension
        ext = 'jpg'  # Default
        if hasattr(photo, 'mime_type') and photo.mime_type:
            if 'png' in photo.mime_type:
                ext = 'png'
            elif 'webp' in photo.mime_type:
                ext = 'webp'
            elif 'gif' in photo.mime_type:
                ext = 'gif'
        elif hasattr(photo, 'file_name') and photo.file_name:
            ext = photo.file_name.split('.')[-1] if '.' in photo.file_name else 'jpg'
        
        # Generate unique filename
        timestamp = int(datetime.now().timestamp() * 1000)
        file_name = f"img_{timestamp}.{ext}"
        full_path = os.path.join(folder, file_name)
        
        # Get file_id
        file_id = None
        if isinstance(photo, str):
            file_id = photo
        elif hasattr(photo, 'file_id'):
            file_id = photo.file_id
        
        if not file_id:
            logger.error("No file_id found in photo object")
            return None
        
        # Download using client
        file_path = await client.download_media(file_id, file_name=full_path)
        
        # Verify file exists
        if file_path and os.path.exists(file_path):
            file_size = os.path.getsize(file_path)
            logger.info(f"Downloaded photo: {file_path} ({file_size} bytes)")
            return file_path
        else:
            logger.error(f"Download failed - file not found: {full_path}")
            return None
    except Exception as e:
        logger.error(f"Failed to download photo: {e}", exc_info=True)
        return None

async def download_url_to_folder(url, folder):
    """Download image from URL to local folder"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status == 200:
                    content_type = response.headers.get('Content-Type', '')
                    ext = 'jpg'
                    if 'png' in content_type:
                        ext = 'png'
                    elif 'webp' in content_type:
                        ext = 'webp'
                    
                    file_name = f"url_{int(datetime.now().timestamp() * 1000)}.{ext}"
                    file_path = os.path.join(folder, file_name)
                    
                    with open(file_path, 'wb') as f:
                        f.write(await response.read())
                    
                    logger.info(f"Downloaded URL to: {file_path}")
                    return file_path
    except Exception as e:
        logger.error(f"Failed to download URL: {e}")
    return None

@Client.on_message(filters.command("admin") & filters.user(BIMBO_OWNER_ID))
async def admin_panel(client: Client, message: Message):
    buttons = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(" Channels", callback_data="admin_channels"),
            InlineKeyboardButton(" Ban Users", callback_data="admin_ban")
        ],
        [
            InlineKeyboardButton(" Statistics", callback_data="admin_stats"),
            InlineKeyboardButton(" Settings", callback_data="admin_settings")
        ],
        [
            InlineKeyboardButton(" Broadcast", callback_data="admin_broadcast"),
            InlineKeyboardButton(" Database", callback_data="admin_database")
        ],
        [
            InlineKeyboardButton(" Premium Users", callback_data="admin_premium"),
            InlineKeyboardButton(" Premium List", callback_data="admin_premium_list")
        ],
        [
            InlineKeyboardButton(" Images", callback_data="admin_images")
        ]
    ])
    
    await message.reply_text(
        " **Admin Panel**\n\n"
        "Welcome to the admin control center.\n"
        "Choose an option below:",
        reply_markup=buttons
    )

@Client.on_callback_query(filters.regex("^(admin_|action_|save_|view_|clear_)"))
async def admin_callback(client: Client, callback_query):
    data = callback_query.data
    user_id = callback_query.from_user.id
    
    if data == "admin_channels":
        await show_channels(callback_query)
    elif data == "admin_ban":
        await show_ban_panel(callback_query)
    elif data == "admin_stats":
        await show_stats(callback_query)
    elif data == "admin_settings":
        await show_settings(callback_query)
    elif data == "admin_broadcast":
        await callback_query.answer("Use /broadcast command", show_alert=True)
    elif data == "admin_database":
        await show_database(callback_query)
    elif data == "admin_premium":
        await show_premium_panel(callback_query)
    elif data == "admin_premium_list":
        await show_premium_list(callback_query)
    elif data == "admin_images":
        await show_images_panel(callback_query)
    elif data == "admin_back":
        await show_admin_panel(callback_query)
    elif data == "admin_view_progress":
        await show_view_progress(callback_query)
    elif data == "admin_view_start":
        await show_view_start(callback_query)
    elif data == "admin_clear_progress":
        set_progress_images([])
        await callback_query.answer("All progress images cleared!", show_alert=True)
        await show_images_panel(callback_query)
    elif data == "action_add_progress":
        # Set pending action for progress photos
        if 'pending_actions' not in admin_data:
            admin_data['pending_actions'] = {}
        admin_data['pending_actions'][str(user_id)] = 'progress'
        save_admin_data(admin_data)
        await callback_query.answer("Now send photos! They will be saved as progress headers.", show_alert=False)
    elif data == "action_set_start":
        # Set pending action for start photo
        if 'pending_actions' not in admin_data:
            admin_data['pending_actions'] = {}
        admin_data['pending_actions'][str(user_id)] = 'start'
        save_admin_data(admin_data)
        await callback_query.answer("Now send a photo! It will be set as start image.", show_alert=False)

async def show_admin_panel(callback_query):
    buttons = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(" Channels", callback_data="admin_channels"),
            InlineKeyboardButton(" Ban Users", callback_data="admin_ban")
        ],
        [
            InlineKeyboardButton(" Statistics", callback_data="admin_stats"),
            InlineKeyboardButton(" Settings", callback_data="admin_settings")
        ],
        [
            InlineKeyboardButton(" Broadcast", callback_data="admin_broadcast"),
            InlineKeyboardButton(" Database", callback_data="admin_database")
        ],
        [
            InlineKeyboardButton(" Premium Users", callback_data="admin_premium"),
            InlineKeyboardButton(" Premium List", callback_data="admin_premium_list")
        ],
        [
            InlineKeyboardButton(" Images", callback_data="admin_images")
        ]
    ])
    
    await callback_query.message.edit_text(
        " **Admin Panel**\n\n"
        "Welcome to the admin control center.",
        reply_markup=buttons
    )

async def show_images_panel(callback_query):
    progress_imgs = get_progress_images()
    start_pic = get_start_pic()
    local_folder = get_image_folder()
    
    local_count = 0
    if local_folder and os.path.isdir(local_folder):
        try:
            local_count = len([f for f in os.listdir(local_folder) 
                              if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')) 
                              and not f.startswith('.')])
        except Exception:
            pass
    
    text = (
        f" **Images Management**\n\n"
        f" **Progress Images:**\n"
        f"  Links/URLs: {len(progress_imgs)}\n"
        f"  Local folder: `{local_folder}` ({local_count} files)\n\n"
        f" **Start Pic:**\n"
        f"  {start_pic[:60] if start_pic else 'Not set'}...\n\n"
        f" **How to Add Images:**\n"
        f"  • Neeche buttons dabao\n"
        f"  • Phir photos bhejo (single ya album)\n"
        f"  • Ya URL commands use karo"
    )
    
    buttons = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(" Add Progress Photos", callback_data="action_add_progress"),
            InlineKeyboardButton(" Set Start Photo", callback_data="action_set_start")
        ],
        [
            InlineKeyboardButton(" View Progress", callback_data="admin_view_progress"),
            InlineKeyboardButton(" View Start", callback_data="admin_view_start")
        ],
        [
            InlineKeyboardButton(" Clear Progress", callback_data="admin_clear_progress")
        ],
        [
            InlineKeyboardButton(" Back", callback_data="admin_back")
        ]
    ])
    
    await callback_query.message.edit_text(text, reply_markup=buttons)

async def show_premium_panel(callback_query):
    text = (
        " **Premium Management**\n\n"
        "**Commands:**\n"
        "  `/addpremium <user_id> <days>` - Add premium user\n"
        "  `/removepremium <user_id>` - Remove premium user\n"
        "  `/premiumlist` - List all premium users\n\n"
        "**Example:**\n"
        "`/addpremium 123456789 30` - 30 din premium\n"
        "`/addpremium 123456789 365` - 1 saal premium"
    )
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton(" View Premium List", callback_data="admin_premium_list")],
        [InlineKeyboardButton(" Back", callback_data="admin_back")]
    ])
    await callback_query.message.edit_text(text, reply_markup=buttons)

async def show_premium_list(callback_query):
    all_premium = premium_manager.get_all_premium_users()
    
    if not all_premium:
        text = "📋 No premium users found."
    else:
        text = " **Premium Users List**\n\n"
        for uid, data in all_premium.items():
            tier = data.get('tier', 'premium')
            expiry = data.get('expiry', 'Lifetime')
            text += f" `{uid}` | {tier} | Exp: {expiry}\n"
        
        if len(text) > 4000:
            text = text[:4000] + "\n\n...(truncated)"
    
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton(" Back", callback_data="admin_premium")]
    ])
    await callback_query.message.edit_text(text, reply_markup=buttons)

async def show_channels(callback_query):
    channels = admin_data.get('channels', [])
    text = " **Channel Management**\n\n"
    
    if channels:
        text += "**Added Channels:**\n"
        for i, channel in enumerate(channels, 1):
            text += f"{i}. {channel.get('name', 'Unknown')} (`{channel.get('id', 'N/A')}`)\n"
    else:
        text += "No channels added yet.\n"
    
    text += "\n**Commands:**\n"
    text += "  `/addchannel <id> <name>` - Add channel\n"
    text += "  `/removechannel <id>` - Remove channel\n"
    text += "  `/listchannels` - List all channels\n"
    
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton(" Back", callback_data="admin_back")]
    ])
    
    await callback_query.message.edit_text(text, reply_markup=buttons)

async def show_ban_panel(callback_query):
    banned = admin_data.get('banned_users', [])
    text = " **Ban Management**\n\n"
    
    if banned:
        text += f"**Banned Users:** {len(banned)}\n"
        for user_id in banned[:5]:
            text += f"  `{user_id}`\n"
        if len(banned) > 5:
            text += f"... and {len(banned) - 5} more\n"
    else:
        text += "No banned users.\n"
    
    text += "\n**Commands:**\n"
    text += "  `/ban <user_id>` - Ban user\n"
    text += "  `/unban <user_id>` - Unban user\n"
    text += "  `/banlist` - List banned users\n"
    
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton(" Back", callback_data="admin_back")]
    ])
    
    await callback_query.message.edit_text(text, reply_markup=buttons)

async def show_stats(callback_query):
    try:
        total_users = await bimbo.total_users_count()
    except:
        total_users = "N/A"
    
    premium_count = len(premium_manager.get_all_premium_users())
    
    text = (
        f" **Bot Statistics**\n\n"
        f" Total Users: {total_users}\n"
        f" Premium Users: {premium_count}\n"
        f" Channels: {len(admin_data.get('channels', []))}\n"
        f" Banned Users: {len(admin_data.get('banned_users', []))}\n"
        f" Force Subscribe: {' Enabled' if admin_data['settings'].get('force_sub') else ' Disabled'}\n"
        f" Maintenance: {' ON' if admin_data['settings'].get('maintenance_mode') else ' OFF'}\n"
    )
    
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton(" Back", callback_data="admin_back")]
    ])
    
    await callback_query.message.edit_text(text, reply_markup=buttons)

async def show_settings(callback_query):
    settings = admin_data.get('settings', {})
    force_sub = settings.get('force_sub', False)
    maintenance = settings.get('maintenance_mode', False)
    
    text = (
        f" **Bot Settings**\n\n"
        f" **Force Subscribe:** {' Enabled' if force_sub else ' Disabled'}\n"
        f" **Maintenance Mode:** {' ON' if maintenance else ' OFF'}\n"
    )
    
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{'Disable' if force_sub else 'Enable'} Force Sub", callback_data="toggle_forcesub")],
        [InlineKeyboardButton(f"{'Disable' if maintenance else 'Enable'} Maintenance", callback_data="toggle_maintenance")],
        [InlineKeyboardButton(" Back", callback_data="admin_back")]
    ])
    
    await callback_query.message.edit_text(text, reply_markup=buttons)

async def show_database(callback_query):
    from database.access import bimbo as db_access
    try:
        total_users = await db_access.total_users_count()
        db_status = " Connected"
        db_info = f" Total Users in DB: {total_users}\n"
    except Exception as e:
        db_status = f" Error: {e}"
        db_info = ""
    
    try:
        from database.users_chats_db import db as raw_db
        using_fallback = getattr(raw_db, "_use_fb", True)
        if using_fallback:
            db_status = " Fallback (in-memory) - MongoDB NOT connected"
    except Exception:
        pass

    text = (
        f" **Database Information**\n\n"
        f" Database URL: `{str(BIMBO_DATABASE_URL)[:45]}...`\n"
        f" Status: {db_status}\n"
        f"{db_info}"
        f"\n_If status is Fallback, check BIMBO_DATABASE_URL in Koyeb env._"
    )
    
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton(" Back", callback_data="admin_back")]
    ])
    
    await callback_query.message.edit_text(text, reply_markup=buttons)

async def show_view_progress(callback_query):
    """Show all progress images"""
    progress_imgs = get_progress_images()
    folder = get_image_folder()
    
    local_count = 0
    if folder and os.path.isdir(folder):
        try:
            local_count = len([f for f in os.listdir(folder) 
                             if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')) 
                             and not f.startswith('.')])
        except Exception:
            pass
    
    text = f" **Progress Images**\n\n"
    text += f" Links/URLs: {len(progress_imgs)}\n"
    text += f" Local files: {local_count}\n\n"
    
    if progress_imgs:
        text += "**Links/Paths:**\n"
        for i, img in enumerate(progress_imgs[:10], 1):
            text += f"{i}. `{img[:50]}...`\n"
        if len(progress_imgs) > 10:
            text += f"... and {len(progress_imgs) - 10} more\n"
    else:
        text += " No progress images set.\n\n"
        text += "To add:\n"
        text += "  • Use 'Add Progress Photos' button\n"
        text += "  • Or send photo and click button\n"
        text += "  • Or use /setprogresspic command"
    
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton(" Back", callback_data="admin_images")]
    ])
    
    await callback_query.message.edit_text(text, reply_markup=buttons)

async def show_view_start(callback_query):
    """Show current start image"""
    start_pic = get_start_pic()
    
    if not start_pic:
        text = " **Start Image**\n\n Not set yet.\n\n To set:\n  • Use 'Set Start Photo' button\n  • Or send photo and click button\n  • Or use /setstartpic command"
    else:
        text = f" **Start Image**\n\n Current: `{start_pic[:80]}...`"
    
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton(" Back", callback_data="admin_images")]
    ])
    
    await callback_query.message.edit_text(text, reply_markup=buttons)

@Client.on_callback_query(filters.regex("^toggle_"))
async def toggle_settings(client: Client, callback_query):
    data = callback_query.data
    
    if data == "toggle_forcesub":
        admin_data['settings']['force_sub'] = not admin_data['settings'].get('force_sub', False)
        save_admin_data(admin_data)
        await callback_query.answer("Force Subscribe toggled!")
    elif data == "toggle_maintenance":
        admin_data['settings']['maintenance_mode'] = not admin_data['settings'].get('maintenance_mode', False)
        save_admin_data(admin_data)
        await callback_query.answer("Maintenance mode toggled!")
    
    await show_settings(callback_query)

# ══════════════════════════════════════════════════════════
#  PHOTO HANDLING - Send/Forward photos to bot
# ══════════════════════════════════════════════════════════

@Client.on_message(
    (filters.photo | filters.document) & 
    filters.user(BIMBO_OWNER_ID) & 
    filters.private &
    filters.reply &
    filters.regex(r"^/setprogresspic$")
)
async def set_progress_pic_from_photo(client: Client, message: Message):
    """Set progress image from replied photo"""
    folder = ensure_images_folder()
    
    # Get the replied photo
    replied = message.reply_to_message
    photo = None
    
    if replied and replied.photo:
        photo = replied.photo
    elif replied and replied.document and replied.document.mime_type.startswith('image/'):
        # Treat document as photo if it's an image
        photo = replied.document
    
    if not photo:
        await message.reply_text(" Please reply to a photo!")
        return
    
    # Download photo
    file_path = await download_photo_to_folder(client, photo, folder)
    
    if not file_path:
        await message.reply_text(" Failed to download photo!")
        return
    
    # Add to progress images list
    images = get_progress_images()
    images.append(file_path)
    set_progress_images(images)
    
    # Get file size
    file_size = os.path.getsize(file_path)
    
    await message.reply_text(
        f" **Progress Image Added!**\n\n"
        f" Saved to: `{file_path}`\n"
        f" Size: {file_size / 1024:.1f} KB\n"
        f" Total images: {len(images)}\n\n"
        f" Aur photos bhejo ya forward karo!"
    )

@Client.on_message(
    (filters.photo | filters.document) & 
    filters.user(BIMBO_OWNER_ID) & 
    filters.private &
    filters.reply &
    filters.regex(r"^/setstartpic$")
)
async def set_start_pic_from_photo(client: Client, message: Message):
    """Set start image from replied photo"""
    folder = ensure_images_folder()
    
    replied = message.reply_to_message
    photo = None
    
    if replied and replied.photo:
        photo = replied.photo
    elif replied and replied.document and replied.document.mime_type.startswith('image/'):
        photo = replied.document
    
    if not photo:
        await message.reply_text(" Please reply to a photo!")
        return
    
    file_path = await download_photo_to_folder(client, photo, folder)
    
    if not file_path:
        await message.reply_text(" Failed to download photo!")
        return
    
    set_start_pic(file_path)
    
    await message.reply_text(
        f" **Start Image Set!**\n\n"
        f" Saved to: `{file_path}`"
    )

@Client.on_message(
    filters.photo & 
    filters.user(BIMBO_OWNER_ID) & 
    filters.private
)
async def handle_photo_upload(client: Client, message: Message):
    """Handle photo upload - check pending action or show buttons"""
    user_id = str(message.from_user.id)
    pending = admin_data.get('pending_actions', {}).get(user_id)
    folder = ensure_images_folder()
    
    # Check if there's a pending action
    if pending == 'progress':
        # Auto-save as progress
        photo = message.photo if message.photo else message.document
        if photo and (not message.document or message.document.mime_type.startswith('image/')):
            file_path = await download_photo_to_folder(client, photo, folder)
            if file_path:
                images = get_progress_images()
                images.append(file_path)
                set_progress_images(images)
                
                # Clear pending action
                if 'pending_actions' in admin_data:
                    admin_data['pending_actions'].pop(user_id, None)
                    save_admin_data(admin_data)
                
                await message.reply_text(
                    f" **Progress Image Added!**\n\n"
                    f" Saved: `{os.path.basename(file_path)}`\n"
                    f" Total: {len(images)} images\n\n"
                    f" Aur photos bhejo!"
                )
                logger.info(f"Progress image saved: {file_path}")
            else:
                await message.reply_text(" Failed to download photo!")
        else:
            await message.reply_text(" Invalid photo!")
        return
    
    elif pending == 'start':
        # Auto-save as start pic
        photo = message.photo if message.photo else message.document
        if photo and (not message.document or message.document.mime_type.startswith('image/')):
            file_path = await download_photo_to_folder(client, photo, folder)
            if file_path:
                set_start_pic(file_path)
                
                # Clear pending action
                if 'pending_actions' in admin_data:
                    admin_data['pending_actions'].pop(user_id, None)
                    save_admin_data(admin_data)
                
                await message.reply_text(
                    f" **Start Image Set!**\n\n"
                    f" Saved: `{os.path.basename(file_path)}`"
                )
                logger.info(f"Start image saved: {file_path}")
            else:
                await message.reply_text(" Failed to download photo!")
        else:
            await message.reply_text(" Invalid photo!")
        return
    
    # No pending action - show buttons
    buttons = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(" Progress Header", callback_data="save_as_progress"),
            InlineKeyboardButton(" Start Image", callback_data="save_as_start")
        ],
        [
            InlineKeyboardButton(" Cancel", callback_data="cancel_photo")
        ]
    ])
    
    await message.reply_text(
        " **Photo Received!**\n\n"
        "Is image ko kya karna hai? Neeche button dabao:",
        reply_markup=buttons,
        reply_to_message_id=message.id
    )

@Client.on_message(
    filters.media_group & 
    filters.user(BIMBO_OWNER_ID) & 
    filters.private
)
async def handle_media_group(client: Client, message: Message):
    """Handle multiple photos (album) - check pending action or show buttons"""
    user_id = str(message.from_user.id)
    pending = admin_data.get('pending_actions', {}).get(user_id)
    folder = ensure_images_folder()
    
    # Check if there's a pending action
    if pending == 'progress':
        # Auto-save all as progress
        photos_to_save = []
        if message.media_group_id:
            messages = await client.get_media_group(
                chat_id=message.chat.id,
                message_id=message.id
            )
            for msg in messages:
                if msg.photo:
                    photos_to_save.append(msg.photo)
                elif msg.document and msg.document.mime_type.startswith('image/'):
                    photos_to_save.append(msg.document)
        
        if photos_to_save:
            saved_count = 0
            progress_msg = await message.reply_text(f" **Downloading {len(photos_to_save)} photos...**")
            
            for photo in photos_to_save:
                file_path = await download_photo_to_folder(client, photo, folder)
                if file_path:
                    images = get_progress_images()
                    images.append(file_path)
                    set_progress_images(images)
                    saved_count += 1
            
            # Clear pending action
            if 'pending_actions' in admin_data:
                admin_data['pending_actions'].pop(user_id, None)
                save_admin_data(admin_data)
            
            await progress_msg.edit_text(
                f" **{saved_count} Progress Images Added!**\n\n"
                f" Total: {len(get_progress_images())} images\n\n"
                f" Aur photos bhejo!"
            )
            logger.info(f"Album saved: {saved_count} images")
        else:
            await message.reply_text(" No valid photos in album!")
        return
    
    # No pending action - show buttons
    buttons = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(" Progress Headers", callback_data="save_album_as_progress"),
            InlineKeyboardButton(" Start Image", callback_data="save_as_start")
        ],
        [
            InlineKeyboardButton(" Cancel", callback_data="cancel_photo")
        ]
    ])
    
    await message.reply_text(
        " **Photos Received!**\n\n"
        "Sab photos ko kya karna hai? Neeche button dabao:",
        reply_markup=buttons,
        reply_to_message_id=message.id
    )

@Client.on_callback_query(filters.regex("^(save_as_|save_album_|cancel_photo)"))
async def handle_save_callback(client: Client, callback_query):
    """Handle save button clicks"""
    user_id = callback_query.from_user.id
    
    if user_id != BIMBO_OWNER_ID:
        await callback_query.answer(" Only admin can do this!", show_alert=True)
        return
    
    # Get the replied message (photo)
    replied = callback_query.message.reply_to_message
    
    if not replied:
        await callback_query.answer(" No photo found! Please send photo first.", show_alert=True)
        return
    
    folder = ensure_images_folder()
    action = callback_query.data
    
    await callback_query.answer(" Processing...", show_alert=False)
    
    if action in ["save_as_progress", "save_album_as_progress"]:
        # Save as progress images
        photos_to_save = []
        
        if action == "save_as_progress":
            # Single photo
            if replied.photo:
                photos_to_save.append(replied.photo)
            elif replied.document and replied.document.mime_type.startswith('image/'):
                photos_to_save.append(replied.document)
        else:
            # Album - get all photos
            if replied.media_group_id:
                messages = await client.get_media_group(
                    chat_id=callback_query.message.chat.id,
                    message_id=replied.id
                )
                for msg in messages:
                    if msg.photo:
                        photos_to_save.append(msg.photo)
                    elif msg.document and msg.document.mime_type.startswith('image/'):
                        photos_to_save.append(msg.document)
        
        if not photos_to_save:
            await callback_query.answer(" No valid photos!", show_alert=True)
            return
        
        saved_count = 0
        for photo in photos_to_save:
            file_path = await download_photo_to_folder(client, photo, folder)
            if file_path:
                images = get_progress_images()
                images.append(file_path)
                set_progress_images(images)
                saved_count += 1
        
        await callback_query.message.edit_text(
            f" **{saved_count} Progress Image(s) Added!**\n\n"
            f" Total: {len(get_progress_images())} images\n\n"
            f" Aur photos bhejo ya button dabao!"
        )
        
        logger.info(f"Progress images saved: {saved_count}")
    
    elif action == "save_as_start":
        # Save as start pic
        photo = None
        if replied.photo:
            photo = replied.photo
        elif replied.document and replied.document.mime_type.startswith('image/'):
            photo = replied.document
        
        if not photo:
            await callback_query.answer(" No valid photo!", show_alert=True)
            return
        
        file_path = await download_photo_to_folder(client, photo, folder)
        
        if not file_path:
            await callback_query.answer(" Failed to download!", show_alert=True)
            return
        
        set_start_pic(file_path)
        
        await callback_query.message.edit_text(
            f" **Start Image Set!**\n\n"
            f" Saved: `{os.path.basename(file_path)}`"
        )
        
        logger.info(f"Start image saved: {file_path}")
    
    elif action == "cancel_photo":
        await callback_query.message.edit_text(" Cancelled!")
        await asyncio.sleep(1)
        await callback_query.message.delete()

# ══════════════════════════════════════════════════════════
#  TEXT COMMANDS
# ══════════════════════════════════════════════════════════

@Client.on_message(filters.command("setprogresspic") & filters.user(BIMBO_OWNER_ID) & ~filters.reply)
async def set_progress_pic_url(client: Client, message: Message):
    """Add a progress image from URL"""
    if len(message.command) < 2:
        await message.reply_text(
            "**Usage:**\n"
            "  1. Photo bhejo/forward karo, phir reply me `/setprogresspic`\n"
            "  2. Ya URL daal: `/setprogresspic https://...`\n"
            "  3. Ya multiple photos bhejo (album) sab auto-save"
        )
        return
    
    url = message.command[1].strip()
    folder = ensure_images_folder()
    
    # Download from URL
    file_path = await download_url_to_folder(url, folder)
    
    if not file_path:
        await message.reply_text(" Failed to download image from URL!")
        return
    
    images = get_progress_images()
    images.append(file_path)
    set_progress_images(images)
    
    await message.reply_text(
        f" **Progress Image Added!**\n\n"
        f" Saved: `{file_path}`\n"
        f" Total: {len(images)} images"
    )

@Client.on_message(filters.command("setprogresspics") & filters.user(BIMBO_OWNER_ID))
async def set_progress_pics(client: Client, message: Message):
    """Add multiple progress image links"""
    if len(message.command) < 2:
        await message.reply_text(
            "**Usage:** `/setprogresspics <url1,url2,url3>`\n\n"
            "Ya multiple photos ek sath bhejo (album) - sab auto-save!"
        )
        return
    
    urls = [url.strip() for url in message.text.split(None, 1)[1].split(',') if url.strip()]
    if not urls:
        await message.reply_text(" No valid URLs found!")
        return
    
    folder = ensure_images_folder()
    saved = []
    
    progress_msg = await message.reply_text(f" Downloading {len(urls)} images...")
    
    for i, url in enumerate(urls, 1):
        file_path = await download_url_to_folder(url, folder)
        if file_path:
            saved.append(file_path)
        
        try:
            await progress_msg.edit_text(f" Downloading... {i}/{len(urls)}")
        except Exception:
            pass
    
    if saved:
        images = get_progress_images()
        images.extend(saved)
        set_progress_images(images)
        
        await progress_msg.edit_text(
            f" **Added {len(saved)} images!**\n\n"
            f" Total: {len(images)} images"
        )
    else:
        await progress_msg.edit_text(" Failed to download any images!")

@Client.on_message(filters.command("clearprogresspics") & filters.user(BIMBO_OWNER_ID))
async def clear_progress_pics(client: Client, message: Message):
    """Clear all progress images"""
    set_progress_images([])
    await message.reply_text(" All progress images cleared!")

@Client.on_message(filters.command("listprogresspics") & filters.user(BIMBO_OWNER_ID))
async def list_progress_pics(client: Client, message: Message):
    """List all progress images"""
    images = get_progress_images()
    folder = get_image_folder()
    
    local_count = 0
    if folder and os.path.isdir(folder):
        try:
            local_count = len([f for f in os.listdir(folder) 
                             if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')) 
                             and not f.startswith('.')])
        except Exception:
            pass
    
    if not images and local_count == 0:
        await message.reply_text(" No progress images set.")
        return
    
    text = f" **Progress Images**\n\n"
    text += f" Links/URLs: {len(images)}\n"
    text += f" Local files: {local_count}\n\n"
    
    if images:
        text += "**Links:**\n"
        for i, img in enumerate(images[:10], 1):
            text += f"{i}. `{img[:50]}...`\n"
        if len(images) > 10:
            text += f"... and {len(images) - 10} more\n"
    
    await message.reply_text(text)

@Client.on_message(filters.command("setstartpic") & filters.user(BIMBO_OWNER_ID) & ~filters.reply)
async def set_start_pic_url(client: Client, message: Message):
    """Set start pic from URL"""
    if len(message.command) < 2:
        await message.reply_text(
            "**Usage:**\n"
            "  1. Photo bhejo, phir reply me `/setstartpic`\n"
            "  2. Ya URL: `/setstartpic https://...`"
        )
        return
    
    url = message.command[1].strip()
    set_start_pic(url)
    await message.reply_text(f" Start pic set to: `{url[:60]}...`")

@Client.on_message(filters.command("setimagefolder") & filters.user(BIMBO_OWNER_ID))
async def set_image_folder_cmd(client: Client, message: Message):
    """Set local image folder"""
    if len(message.command) < 2:
        await message.reply_text(
            "**Usage:** `/setimagefolder <path>`\n\n"
            "Example: `/setimagefolder images/`"
        )
        return
    
    path = message.command[1].strip()
    os.makedirs(path, exist_ok=True)
    set_image_folder(path)
    
    files = [f for f in os.listdir(path) 
             if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')) 
             and not f.startswith('.')]
    
    await message.reply_text(
        f" Image folder set to: `{path}`\n\n"
        f" Found {len(files)} images in folder."
    )

@Client.on_message(filters.command("addchannel") & filters.user(BIMBO_OWNER_ID))
async def add_channel(client: Client, message: Message):
    if len(message.command) < 3:
        await message.reply_text(" **Usage:** `/addchannel <channel_id> <channel_name>`")
        return
    
    channel_id = message.command[1]
    channel_name = " ".join(message.command[2:])
    
    if 'channels' not in admin_data:
        admin_data['channels'] = []
    
    admin_data['channels'].append({
        'id': channel_id,
        'name': channel_name,
        'added_at': datetime.now().isoformat()
    })
    save_admin_data(admin_data)
    
    await message.reply_text(f" **Channel Added**\n\n Name: {channel_name}\n ID: `{channel_id}`")

@Client.on_message(filters.command("removechannel") & filters.user(BIMBO_OWNER_ID))
async def remove_channel(client: Client, message: Message):
    if len(message.command) < 2:
        await message.reply_text(" **Usage:** `/removechannel <channel_id>`")
        return
    channel_id = message.command[1]
    if 'channels' in admin_data:
        admin_data['channels'] = [c for c in admin_data['channels'] if c['id'] != channel_id]
        save_admin_data(admin_data)
    await message.reply_text(f" Channel `{channel_id}` removed!")

@Client.on_message(filters.command("listchannels") & filters.user(BIMBO_OWNER_ID))
async def list_channels(client: Client, message: Message):
    channels = admin_data.get('channels', [])
    if not channels:
        await message.reply_text(" No channels added yet.")
        return
    text = " **Added Channels:**\n\n"
    for i, channel in enumerate(channels, 1):
        text += f"{i}. **{channel['name']}**\n   ID: `{channel['id']}`\n\n"
    await message.reply_text(text)

@Client.on_message(filters.command("ban") & filters.user(BIMBO_OWNER_ID))
async def ban_user(client: Client, message: Message):
    if len(message.command) < 2:
        await message.reply_text(" **Usage:** `/ban <user_id>`")
        return
    user_id = int(message.command[1])
    if 'banned_users' not in admin_data:
        admin_data['banned_users'] = []
    if user_id not in admin_data['banned_users']:
        admin_data['banned_users'].append(user_id)
        save_admin_data(admin_data)
    await message.reply_text(f" User `{user_id}` has been banned!")

@Client.on_message(filters.command("unban") & filters.user(BIMBO_OWNER_ID))
async def unban_user(client: Client, message: Message):
    if len(message.command) < 2:
        await message.reply_text(" **Usage:** `/unban <user_id>`")
        return
    user_id = int(message.command[1])
    if 'banned_users' in admin_data:
        admin_data['banned_users'] = [u for u in admin_data['banned_users'] if u != user_id]
        save_admin_data(admin_data)
    await message.reply_text(f" User `{user_id}` has been unbanned!")

@Client.on_message(filters.command("banlist") & filters.user(BIMBO_OWNER_ID))
async def ban_list(client: Client, message: Message):
    banned = admin_data.get('banned_users', [])
    if not banned:
        await message.reply_text(" No banned users.")
        return
    text = " **Banned Users:**\n\n"
    for user_id in banned:
        text += f"  `{user_id}`\n"
    await message.reply_text(text)

def is_user_banned(user_id: int) -> bool:
    return user_id in admin_data.get('banned_users', [])
