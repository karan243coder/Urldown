# -*- coding: utf-8 -*-
# BIMBO URL Bot
# Powered by BIMBO
# Support: @Bimbo69

import os
import asyncio
import random
import logging
from PIL import Image, ImageOps
from config import Config
from pyrogram import filters
from translation import Translation
from database.access import bimbo
from database.adduser import AddUser
from pyrogram import Client as BimboBot
from hachoir.parser import createParser
from hachoir.metadata import extractMetadata
from helper_funcs.help_Nekmo_ffmpeg import take_screen_shot

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

THUMB_MAX_EDGE = 320
THUMB_DEFAULT_VIDEO_SIZE = (320, 180)
THUMB_DEFAULT_IMAGE_SIZE = (320, 320)
THUMB_QUALITY = 88


def ensure_thumb_dir():
    os.makedirs(Config.BIMBO_DOWNLOAD_LOCATION, exist_ok=True)


def get_thumb_path(user_id: int, task_id: str = "") -> str:
    ensure_thumb_dir()
    if task_id:
        return os.path.join(Config.BIMBO_DOWNLOAD_LOCATION, f"{user_id}_{task_id}.jpg")
    return os.path.join(Config.BIMBO_DOWNLOAD_LOCATION, f"{user_id}.jpg")


def get_target_thumbnail_size(video_width: int = 0, video_height: int = 0):
    if video_width and video_height:
        ratio = float(video_width) / float(video_height)
        if ratio >= 1:
            target_width = THUMB_MAX_EDGE
            target_height = max(90, int(target_width / ratio))
        else:
            target_height = THUMB_MAX_EDGE
            target_width = max(90, int(target_height * ratio))
        return target_width, target_height
    return THUMB_DEFAULT_VIDEO_SIZE


def normalize_thumbnail(input_path: str, output_path: str = None, target_size=None, crop_to_fit: bool = False) -> str | None:
    """Convert image to Telegram-friendly JPEG thumbnail."""
    try:
        if not input_path or not os.path.exists(input_path):
            return None

        output_path = output_path or input_path
        target_size = target_size or THUMB_DEFAULT_IMAGE_SIZE

        with Image.open(input_path) as img:
            img = img.convert("RGB")
            if crop_to_fit:
                final_img = ImageOps.fit(
                    img,
                    target_size,
                    method=Image.Resampling.LANCZOS,
                    centering=(0.5, 0.5)
                )
            else:
                final_img = ImageOps.contain(img, target_size, method=Image.Resampling.LANCZOS)
            final_img.save(output_path, "JPEG", quality=THUMB_QUALITY, optimize=True)
        return output_path
    except Exception as e:
        logger.error(f"Thumbnail normalize error: {e}")
        return None


async def download_user_thumbnail(bot, user_id: int, target_size=None, crop_to_fit: bool = False, task_id: str = ""):
    db_thumbnail = await bimbo.get_thumbnail(user_id)
    if db_thumbnail is None:
        return None

    thumb_image_path = get_thumb_path(user_id, task_id)
    try:
        downloaded_path = await bot.download_media(message=db_thumbnail, file_name=thumb_image_path)
        return normalize_thumbnail(downloaded_path, thumb_image_path, target_size=target_size, crop_to_fit=crop_to_fit)
    except Exception as e:
        logger.error(f"Custom thumbnail download error: {e}")
        return None


def pick_screenshot_second(duration: int) -> int:
    duration = int(duration or 0)
    if duration <= 1:
        return 0
    if duration <= 10:
        return max(1, duration // 2)

    candidate_points = [
        max(1, int(duration * 0.15)),
        max(1, int(duration * 0.30)),
        max(1, int(duration * 0.45)),
        max(1, int(duration * 0.60)),
        max(1, int(duration * 0.75)),
    ]
    return random.choice(candidate_points)


async def generate_video_screenshot(download_directory: str, duration: int, user_id: int, target_size=None, task_id: str = ""):
    try:
        output_dir = os.path.dirname(download_directory)
        shot_second = pick_screenshot_second(duration)
        screenshot = await take_screen_shot(download_directory, output_dir, shot_second)
        if screenshot and os.path.exists(screenshot):
            return normalize_thumbnail(
                screenshot,
                get_thumb_path(user_id, task_id),
                target_size=target_size,
                crop_to_fit=True,
            )
    except Exception as e:
        logger.error(f"Video screenshot error: {e}")
    return None


def extract_media_metadata(download_directory):
    width = 0
    height = 0
    duration = 0

    try:
        parser = createParser(download_directory)
        if not parser:
            return width, height, duration

        with parser:
            metadata = extractMetadata(parser)

        if metadata is not None:
            if metadata.has("duration"):
                duration = metadata.get("duration").seconds
            if metadata.has("width"):
                width = metadata.get("width")
            if metadata.has("height"):
                height = metadata.get("height")
    except Exception as e:
        logger.error(f"Metadata read error for {download_directory}: {e}")

    return width or 0, height or 0, duration or 0


@BimboBot.on_message(filters.private & filters.photo)
async def save_photo(bot, update):
    await AddUser(bot, update)
    await bimbo.set_thumbnail(update.from_user.id, thumbnail=update.photo.file_id)
    await bot.send_message(
        chat_id=update.chat.id,
        text=Translation.BIMBO_SAVED_CUSTOM_THUMB_NAIL,
        reply_to_message_id=update.id
    )


@BimboBot.on_message(filters.private & filters.command("delthumbnail"))
async def delthumbnail(bot, update):
    await AddUser(bot, update)
    await bimbo.set_thumbnail(update.from_user.id, thumbnail=None)
    await bot.send_message(
        chat_id=update.chat.id,
        text=Translation.BIMBO_DEL_ETED_CUSTOM_THUMB_NAIL,
        reply_to_message_id=update.id
    )


@BimboBot.on_message(filters.private & filters.command("viewthumbnail"))
async def viewthumbnail(bot, update):
    await AddUser(bot, update)
    thumbnail = await bimbo.get_thumbnail(update.from_user.id)
    if thumbnail is not None:
        await bot.send_photo(
            chat_id=update.chat.id,
            photo=thumbnail,
            caption="**Your current saved thumbnail ✅**",
            reply_to_message_id=update.id
        )
    else:
        await update.reply_text(text="**No thumbnail found 🙁**")


async def Gthumb01(bot, update, task_id: str = ""):
    """Get custom thumbnail for audio/document uploads."""
    return await download_user_thumbnail(
        bot,
        update.from_user.id,
        target_size=THUMB_DEFAULT_IMAGE_SIZE,
        crop_to_fit=False,
        task_id=task_id,
    )


async def Gthumb02(bot, update, duration, download_directory, task_id: str = ""):
    """Get video-aligned thumbnail so it looks naturally fitted inside the video frame."""
    video_width, video_height, _ = extract_media_metadata(download_directory)
    target_size = get_target_thumbnail_size(video_width, video_height)

    custom_thumb = await download_user_thumbnail(
        bot,
        update.from_user.id,
        target_size=target_size,
        crop_to_fit=True,
        task_id=task_id,
    )
    if custom_thumb is not None:
        return custom_thumb

    auto_thumb = await generate_video_screenshot(download_directory, duration, update.from_user.id, target_size=target_size, task_id=task_id)
    return auto_thumb


async def Mdata01(download_directory):
    width, height, duration = extract_media_metadata(download_directory)
    return width, height, duration


async def Mdata02(download_directory):
    width, _, duration = extract_media_metadata(download_directory)
    return width, duration


async def Mdata03(download_directory):
    _, _, duration = extract_media_metadata(download_directory)
    return duration


async def get_flocation(download_directory, extension):
    # Normalize extension
    ext = (extension or "mp4").lstrip(".").lower()
    base_no_ext = os.path.splitext(download_directory)[0]
    base_dir = os.path.dirname(download_directory)
    base_name = os.path.basename(download_directory)
    base_name_no_ext = os.path.splitext(base_name)[0]

    candidates = [
        download_directory,
        download_directory + ".mkv",
        download_directory + "." + ext,
        base_no_ext + ".mkv",
        base_no_ext + "." + ext,
        base_no_ext + ".mp4",
        base_no_ext + ".webm",
        base_no_ext + ".m4v",
        base_no_ext + ".mp3",
        base_no_ext + ".m4a",
    ]

    for file_directory in candidates:
        try:
            file_size = os.stat(file_directory).st_size
            if file_size > 0:
                return file_size, file_directory
        except Exception:
            continue

    # Robust fallback: scan the download directory for the latest file
    # matching the base name prefix (handles yt-dlp's temp/merged names)
    try:
        if os.path.isdir(base_dir):
            best = None
            best_mtime = 0
            prefix = base_name_no_ext[:30].lower() if len(base_name_no_ext) >= 30 else base_name_no_ext.lower()
            for f in os.listdir(base_dir):
                fl = f.lower()
                fp = os.path.join(base_dir, f)
                if not os.path.isfile(fp):
                    continue
                # match prefix OR contains xh-quality tag
                if prefix and (prefix in fl or fl.startswith(prefix)):
                    try:
                        st = os.stat(fp)
                        if st.st_size > 100_000 and st.st_mtime > best_mtime:
                            best = fp
                            best_mtime = st.st_mtime
                    except Exception:
                        continue
            if best:
                return os.stat(best).st_size, best
    except Exception:
        pass

    return 0, download_directory

async def add_watermark(file_path: str, watermark_text: str) -> str:
    """
    Add text watermark to the file (image/video thumbnail)
    Uses ffmpeg to add watermark text overlay.
    """
    import subprocess as sp
    
    if not watermark_text or not file_path:
        return file_path
    
    try:
        # For images - use PIL
        if file_path.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')):
            with Image.open(file_path) as img:
                from PIL import ImageDraw, ImageFont
                img_rgba = img.convert("RGBA")
                overlay = Image.new("RGBA", img_rgba.size, (255, 255, 255, 0))
                draw = ImageDraw.Draw(overlay)
                # Use default font
                try:
                    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 30)
                except:
                    font = ImageFont.load_default()
                # Position bottom-right
                bbox = draw.textbbox((0, 0), watermark_text, font=font)
                tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
                x = img_rgba.width - tw - 10
                y = img_rgba.height - th - 10
                draw.text((x, y), watermark_text, font=font, fill=(255, 255, 255, 180))
                watermarked = Image.alpha_composite(img_rgba, overlay)
                watermarked = watermarked.convert("RGB")
                watermarked.save(file_path, "JPEG", quality=88)
            return file_path
        
        # For videos - use ffmpeg
        output_path = os.path.splitext(file_path)[0] + "_wm" + os.path.splitext(file_path)[1]
        cmd = [
            "ffmpeg", "-i", file_path,
            "-vf", f"drawtext=text='{watermark_text}':fontcolor=white:fontsize=24:x=w-tw-10:y=h-th-10:shadowcolor=black:shadowx=2:shadowy=2",
            "-codec:a", "copy", "-y", output_path
        ]
        process = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        await process.communicate()
        if os.path.exists(output_path):
            os.replace(output_path, file_path)
        return file_path
    except Exception as e:
        logger.warning(f"add_watermark error: {e}")
        return file_path
