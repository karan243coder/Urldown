# BIMBO URL Bot
# Powered by BIMBO
# Support: @Bimbo69

# the logging things
import logging
logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
import asyncio
import aiohttp
import json
import math
import os
import shutil
import time
from datetime import datetime
# the secret configuration specific things
from config import Config
from pyrogram import enums
# the Strings used for this "thing"
from translation import Translation
from plugins.custom_thumbnail import *
logging.getLogger("pyrogram").setLevel(logging.WARNING)
from helper_funcs.display_progress import progress_for_pyrogram, humanbytes, TimeFormatter
from hachoir.metadata import extractMetadata
from hachoir.parser import createParser
# https://stackoverflow.com/a/37631799/4723940
from PIL import Image


async def ddl_call_back(bot, update):
    logger.info(update)
    cb_data = update.data
    # youtube_dl extractors
    tg_send_type, youtube_dl_format, youtube_dl_ext = cb_data.split("=")
    thumb_image_path = Config.BIMBO_DOWNLOAD_LOCATION + \
        "/" + str(update.from_user.id) + ".jpg"
    youtube_dl_url = update.message.reply_to_message.text
    custom_file_name = os.path.basename(youtube_dl_url)
    if "|" in youtube_dl_url:
        url_parts = youtube_dl_url.split("|")
        if len(url_parts) == 2:
            youtube_dl_url = url_parts[0]
            custom_file_name = url_parts[1]
        else:
            for entity in update.message.reply_to_message.entities:
                if entity.type == "text_link":
                    youtube_dl_url = entity.url
                elif entity.type == "url":
                    o = entity.offset
                    l = entity.length
                    youtube_dl_url = youtube_dl_url[o:o + l]
        if youtube_dl_url is not None:
            youtube_dl_url = youtube_dl_url.strip()
        if custom_file_name is not None:
            custom_file_name = custom_file_name.strip()
        # https://stackoverflow.com/a/761825/4723940
        logger.info(youtube_dl_url)
        logger.info(custom_file_name)
    else:
        for entity in update.message.reply_to_message.entities:
            if entity.type == "text_link":
                youtube_dl_url = entity.url
            elif entity.type == "url":
                o = entity.offset
                l = entity.length
                youtube_dl_url = youtube_dl_url[o:o + l]
    
    user = await bot.get_me()
    # BUG FIXED HERE: Changed user["mention"] to user.mention
    mention = user.mention 
    description = Translation.BIMBO_CUSTOM_CAPTION_UL_FILE.format(mention)
    
    start = datetime.now()
    await bot.edit_message_text(
        text=Translation.BIMBO_DOWNLOAD_START,
        chat_id=update.message.chat.id,
        message_id=update.message.id
    )
    tmp_directory_for_each_user = Config.BIMBO_DOWNLOAD_LOCATION + "/" + str(update.from_user.id)
    if not os.path.isdir(tmp_directory_for_each_user):
        os.makedirs(tmp_directory_for_each_user)
    download_directory = tmp_directory_for_each_user + "/" + custom_file_name
    command_to_exec = []
    # 🚀 Tuned TCP connector — larger limit, no DNS cache issues, faster I/O
    timeout = aiohttp.ClientTimeout(total=None, sock_connect=30, sock_read=600)
    connector = aiohttp.TCPConnector(
        limit=16,
        ttl_dns_cache=300,
        use_dns_cache=True,
        force_close=False,
        enable_cleanup_closed=True,
    )
    async with aiohttp.ClientSession(
        timeout=timeout,
        connector=connector,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/125.0.0.0 Safari/537.36"
        },
    ) as session:
        c_time = time.time()
        try:
            await download_coroutine(
                bot,
                session,
                youtube_dl_url,
                download_directory,
                update.message.chat.id,
                update.message.id,
                c_time
            )
        except asyncio.TimeoutError:
            await bot.edit_message_text(
                text=Translation.BIMBO_SLOW_URL_DECED,
                chat_id=update.message.chat.id,
                message_id=update.message.id
            )
            return False
    if os.path.exists(download_directory):
        end_one = datetime.now()
        await bot.edit_message_text(
            text=Translation.BIMBO_UPLOAD_START,
            chat_id=update.message.chat.id,
            message_id=update.message.id
        )
        file_size = Config.BIMBO_TG_MAX_FILE_SIZE + 1
        try:
            file_size = os.stat(download_directory).st_size
        except FileNotFoundError as exc:
            download_directory = os.path.splitext(download_directory)[0] + "." + "mkv"
            # https://stackoverflow.com/a/678242/4723940
            file_size = os.stat(download_directory).st_size
        if file_size > Config.BIMBO_TG_MAX_FILE_SIZE:
            await bot.edit_message_text(
                chat_id=update.message.chat.id,
                text=Translation.BIMBO_RCHD_TG_API_LIMIT,
                message_id=update.message.id
            )
        else:
            # ref: BIMBO bot message
            start_time = time.time()
            # try to upload file
            if tg_send_type == "audio":
                duration = await Mdata03(download_directory)
                thumb_image_path = await Gthumb01(bot, update)
                await bot.send_audio(
                    chat_id=update.message.chat.id,
                    audio=download_directory,
                    caption=description,
                    duration=duration,
                    thumb=thumb_image_path,
                    reply_to_message_id=update.message.reply_to_message.id,
                    progress=progress_for_pyrogram,
                    progress_args=(
                        Translation.BIMBO_UPLOAD_START,
                        update.message,
                        start_time
                    )
                )
            elif tg_send_type == "file":
                  thumb_image_path = await Gthumb01(bot, update)
                  await bot.send_document(
                    chat_id=update.message.chat.id,
                    document=download_directory,
                    thumb=thumb_image_path,
                    caption=description,
                    reply_to_message_id=update.message.reply_to_message.id,
                    progress=progress_for_pyrogram,
                    progress_args=(
                        Translation.BIMBO_UPLOAD_START,
                        update.message,
                        start_time
                    )
                )
            elif tg_send_type == "vm":
                 width, duration = await Mdata02(download_directory)
                 thumb_image_path = await Gthumb02(bot, update, duration, download_directory)
                 await bot.send_video_note(
                    chat_id=update.message.chat.id,
                    video_note=download_directory,
                    duration=duration,
                    length=width,
                    thumb=thumb_image_path,
                    reply_to_message_id=update.message.reply_to_message.id,
                    progress=progress_for_pyrogram,
                    progress_args=(
                        Translation.BIMBO_UPLOAD_START,
                        update.message,
                        start_time
                    )
                )
            elif tg_send_type == "video":
                 width, height, duration = await Mdata01(download_directory)
                 thumb_image_path = await Gthumb02(bot, update, duration, download_directory)
                 await bot.send_video(
                    chat_id=update.message.chat.id,
                    video=download_directory,
                    caption=description,
                    duration=duration,
                    width=width,
                    height=height,
                    supports_streaming=True,
                    thumb=thumb_image_path,
                    reply_to_message_id=update.message.reply_to_message.id,
                    progress=progress_for_pyrogram,
                    progress_args=(
                        Translation.BIMBO_UPLOAD_START,
                        update.message,
                        start_time
                    )
                )
            else:
                logger.info("Did this happen? :\\")
            end_two = datetime.now()
            try:
                os.remove(download_directory)
                os.remove(thumb_image_path)
            except:
                pass
            time_taken_for_download = (end_one - start).seconds
            time_taken_for_upload = (end_two - end_one).seconds
            await bot.edit_message_text(
                text=Translation.BIMBO_AFTER_SUCCESSFUL_UPLOAD_MSG_WITH_TS.format(time_taken_for_download, time_taken_for_upload),
                chat_id=update.message.chat.id,
                message_id=update.message.id,
                disable_web_page_preview=True
            )
    else:
        await bot.edit_message_text(
            text=Translation.BIMBO_NO_VOID_FORMAT_FOUND.format("Incorrect Link"),
            chat_id=update.message.chat.id,
            message_id=update.message.id,
            disable_web_page_preview=True
        )


async def download_coroutine(bot, session, url, file_name, chat_id, message_id, start):
    downloaded = 0
    display_message = ""
    async with session.get(url, timeout=Config.BIMBO_PROCESS_MAX_TIMEOUT) as response:
        if response.status >= 400:
            raise Exception(f"HTTP {response.status}: direct link download failed")

        total_length = int(response.headers.get("Content-Length") or 0)
        content_type = response.headers.get("Content-Type", "")
        if "text" in content_type and total_length and total_length < 500:
            return await response.release()

        total_text = humanbytes(total_length) if total_length else "Unknown"
        await bot.edit_message_text(
            chat_id,
            message_id,
            text="""Initiating Download
URL: {}
File Size: {}""".format(url, total_text)
        )
        with open(file_name, "wb") as f_handle:
            last_byte_at = time.time()
            stall_limit = int(getattr(Config, "BIMBO_STALL_TIMEOUT", 360) or 360)
            while True:
                try:
                    chunk = await asyncio.wait_for(
                        response.content.read(Config.BIMBO_CHUNK_SIZE),
                        timeout=30,
                    )
                except asyncio.TimeoutError:
                    if time.time() - last_byte_at >= stall_limit:
                        raise Exception(
                            f"Direct download stalled for {stall_limit // 60} min (dead link)"
                        )
                    continue
                if not chunk:
                    break
                f_handle.write(chunk)
                downloaded += len(chunk)
                last_byte_at = time.time()
                now = last_byte_at
                diff = now - start
                if round(diff % 5.00) == 0 or (total_length and downloaded >= total_length):
                    speed = downloaded / diff if diff > 0 else 0
                    try:
                        if total_length:
                            percentage = downloaded * 100 / total_length
                            elapsed_time = round(diff) * 1000
                            time_to_completion = round((total_length - downloaded) / speed) * 1000 if speed > 0 else 0
                            estimated_total_time = elapsed_time + time_to_completion
                            eta_text = TimeFormatter(estimated_total_time)
                        else:
                            percentage = 0
                            eta_text = "Unknown"

                        current_message = """**Download Status**
URL: {}
File Size: {}
Downloaded: {}
ETA: {}""".format(
    url,
    total_text,
    humanbytes(downloaded),
    eta_text
)
                        if current_message != display_message:
                            await bot.edit_message_text(
                                chat_id,
                                message_id,
                                text=current_message
                            )
                            display_message = current_message
                    except Exception as e:
                        logger.info(str(e))
                        pass
        return await response.release()
