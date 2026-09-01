"""Unified xHamster/Eporner download → split → upload pipeline."""

import asyncio
import os
import re
import time
from urllib.parse import urlparse

from config import Config
from helper_funcs.display_progress import (
    claim_user_progress_message,
    finalize_user_progress,
    get_task,
    get_user_active_tasks,
    get_user_message,
    is_task_cancelled,
    prune_stalled_tasks,
    register_task,
    remove_task,
    reset_idle_dashboard,
    set_task_stage,
    update_task,
    update_user_progress,
)
from plugins.media_pipeline import (
    PRIORITY_INTERACTIVE, PRIORITY_NORMAL,
    begin_interactive_job, end_interactive_job, stage_slot,
)
from utils import humanbytes, user_download_dir


def _site_from_url(url: str, headers=None) -> str:
    text = f"{url} {(headers or {}).get('Origin', '')}".lower()
    return "eporner" if "eporner" in text else "xhamster"


def _message_identity(message):
    if message is None:
        return None
    chat = getattr(getattr(message, "chat", None), "id", None)
    mid = getattr(message, "id", getattr(message, "message_id", None))
    return chat, mid


async def _canonical_dashboard(client, user_id, candidate):
    current = get_user_message(user_id)
    if current is None:
        return await claim_user_progress_message(
            user_id, candidate, delete_duplicate=False
        )
    if candidate is not None and _message_identity(candidate) != _message_identity(current):
        try:
            await candidate.delete()
        except Exception:
            pass
    return current


async def _notify_failure(client, user_id, dashboard, task_id, title, error):
    task = get_task(task_id)
    if task:
        task["error"] = str(error)[:300]
    update_task(
        task_id,
        (task or {}).get("downloaded", 0),
        (task or {}).get("total_size", 0),
        0,
        status="failed",
        engine=(task or {}).get("engine", "unknown"),
    )
    await update_user_progress(client, user_id, force=True)
    try:
        await client.send_message(
            user_id,
            f"❌ **Media job failed**\n`{str(title)[:80]}`\n\n`{str(error)[:500]}`",
        )
    except Exception:
        pass
    remove_task(task_id)
    await finalize_user_progress(client, user_id, dashboard)


async def _download_and_upload_impl(
    client,
    status_msg,
    user,
    webpage_url,
    media_url,
    title,
    height,
    mode,
    headers,
    task_id=None,
    priority=PRIORITY_NORMAL,
):
    """Run one media item through the shared 2-DL/2-UL pipeline.

    Returns True on successful Telegram upload and False on failure.
    """
    from helper_funcs.display_progress import humanbytes as progress_humanbytes
    from plugins.custom_thumbnail import Gthumb01, Gthumb02, Mdata01, Mdata03
    from plugins.xhamster_upgrade import _split_large_video, get_video_whd
    from plugins.youtube_dl_button import send_log_media

    uid = int(user.id)
    site = _site_from_url(webpage_url, headers)
    engine = site
    task_id = task_id or f"{site}_{uid}_{time.time_ns()}"
    safe_title = re.sub(r'[\\/:*?"<>|]+', ' ', str(title or "Video"))[:100].strip() or "video"
    prune_stalled_tasks(uid)
    others_live = [
        t for t in get_user_active_tasks(uid)
        if t.get("status") not in ("queued", "waiting")
    ]
    if not others_live:
        await reset_idle_dashboard(client, uid)
    dashboard = await _canonical_dashboard(client, uid, status_msg)

    register_task(
        task_id, uid, safe_title, 0,
        task_type="download", engine=engine, source_url=webpage_url,
    )
    await update_user_progress(client, uid, force=True)

    work_dir = os.path.join(user_download_dir(uid), task_id)
    os.makedirs(work_dir, exist_ok=True)

    def _cleanup_workdir():
        try:
            import shutil
            shutil.rmtree(work_dir, ignore_errors=True)
        except Exception:
            pass

    suffix = "mp3" if mode == "audio" else "mp4"
    out_path = os.path.join(work_dir, f"{safe_title}.{suffix}")
    cmd = [
        "yt-dlp", "--no-warnings", "-c", "--newline",
        "--no-check-certificates", "--geo-bypass",
        "--buffer-size", "8M", "--http-chunk-size", "4M",
        "--retries", "20", "--fragment-retries", "20",
        "--retry-sleep", "http:exp=2:20",
        "--retry-sleep", "fragment:exp=2:20",
        "--concurrent-fragments", str(
            Config.XHAMSTER_CONCURRENT_FRAGMENTS if site == "xhamster"
            else min(2, Config.YTDLP_CONCURRENT_FRAGMENTS)
        ),
        "--add-header", f"User-Agent:{(headers or {}).get('User-Agent', 'Mozilla/5.0')}",
    ]
    if Config.BIMBO_HTTP_PROXY:
        cmd += ["--proxy", Config.BIMBO_HTTP_PROXY]
    if (headers or {}).get("Referer"):
        cmd += ["--add-header", f"Referer:{headers['Referer']}"]
    if (headers or {}).get("Origin"):
        cmd += ["--add-header", f"Origin:{headers['Origin']}"]
    if site == "xhamster" and Config.XHAMSTER_USE_COOKIES and os.path.exists("cookies.txt"):
        cmd += ["--cookies", "cookies.txt"]
    if mode == "audio":
        cmd += [
            "-x", "--audio-format", "mp3", "--audio-quality", "192K",
            "--hls-prefer-native", "-o", out_path,
        ]
    else:
        cmd += ["--hls-prefer-native", "--merge-output-format", "mp4", "-o", out_path]
    cmd.append(media_url or webpage_url)

    process = None
    output_tail = []
    last_pct = -1.0
    last_pct_at = time.monotonic()
    try:
        async with stage_slot(
            "download", task_id, uid, site=site, client=client, priority=priority
        ):
            set_task_stage(
                task_id, task_type="download", status="downloading",
                engine=engine, reset_timer=True,
            )
            await update_user_progress(client, uid, force=True)
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            while True:
                try:
                    line = await asyncio.wait_for(process.stdout.readline(), timeout=30)
                except asyncio.TimeoutError:
                    if (
                        site == "xhamster"
                        and time.monotonic() - last_pct_at >= Config.XHAMSTER_STALL_TIMEOUT
                    ):
                        process.kill()
                        raise RuntimeError(
                            f"xHamster CDN stalled for {Config.XHAMSTER_STALL_TIMEOUT}s"
                        )
                    continue
                if not line:
                    break
                decoded = line.decode("utf-8", "ignore").strip()
                if decoded:
                    output_tail.append(decoded)
                    del output_tail[:-12]
                match = re.search(r"\[download\]\s+([\d.]+)%", decoded)
                if not match:
                    continue
                pct = float(match.group(1))
                if pct > last_pct + 0.001:
                    last_pct = pct
                    last_pct_at = time.monotonic()
                total_match = re.search(r"of\s+~?\s*([\d.]+)\s*([KMGTP]?i?B)", decoded, re.I)
                speed_match = re.search(r"at\s+([\d.]+)\s*([KMGTP]?i?B)/s", decoded, re.I)
                units = {"B": 1, "KB": 1024, "KIB": 1024, "MB": 1024**2,
                         "MIB": 1024**2, "GB": 1024**3, "GIB": 1024**3,
                         "TB": 1024**4, "TIB": 1024**4}
                total = int(float(total_match.group(1)) * units.get(total_match.group(2).upper(), 1)) if total_match else 0
                speed = int(float(speed_match.group(1)) * units.get(speed_match.group(2).upper(), 1)) if speed_match else 0
                downloaded = int(total * pct / 100) if total else 0
                update_task(task_id, downloaded, total, speed, "downloading", engine)
                await update_user_progress(client, uid)
            await process.wait()
            if process.returncode != 0:
                raise RuntimeError("\n".join(output_tail[-6:]) or f"yt-dlp exit {process.returncode}")
    except Exception as exc:
        if process and process.returncode is None:
            try:
                process.kill()
                await process.wait()
            except Exception:
                pass
        await _notify_failure(client, uid, dashboard, task_id, safe_title, exc)
        _cleanup_workdir()
        return False

    if not os.path.exists(out_path):
        candidates = [
            os.path.join(work_dir, name) for name in os.listdir(work_dir)
            if not name.endswith((".part", ".ytdl", ".temp"))
        ]
        candidates = [path for path in candidates if os.path.isfile(path)]
        if candidates:
            out_path = max(candidates, key=os.path.getsize)
    if not os.path.exists(out_path) or os.path.getsize(out_path) <= 0:
        await _notify_failure(client, uid, dashboard, task_id, safe_title, "download produced no file")
        _cleanup_workdir()
        return False

    original_size = os.path.getsize(out_path)
    parts = [out_path]
    split_limit = min(int(Config.BIMBO_SPLIT_SIZE), 1_900_000_000)
    try:
        if original_size > split_limit:
            set_task_stage(
                task_id, task_type="download", status="splitting", engine="ffmpeg",
                downloaded=0, total_size=original_size, reset_timer=True,
            )
            await update_user_progress(client, uid, force=True)
            parts = await _split_large_video(out_path, split_limit, status_msg=None)
            if not parts or any(not os.path.exists(part) for part in parts):
                raise RuntimeError("split produced missing parts")
            oversized = [os.path.getsize(part) for part in parts if os.path.getsize(part) > split_limit]
            if oversized:
                raise RuntimeError(f"split part exceeds Telegram safe limit: {humanbytes(max(oversized))}")
    except Exception as exc:
        await _notify_failure(client, uid, dashboard, task_id, safe_title, exc)
        _cleanup_workdir()
        return False

    total_upload = sum(os.path.getsize(part) for part in parts)
    set_task_stage(
        task_id, task_type="upload", status="waiting", engine="pyrogram",
        downloaded=0, total_size=total_upload, reset_timer=True,
    )
    await update_user_progress(client, uid, force=True)

    thumb = None
    duration = width = video_height = 0
    try:
        class _FakeFromUser:
            id = uid
            first_name = getattr(user, "first_name", "User")
            username = getattr(user, "username", None)

        class _FakeUpdate:
            from_user = _FakeFromUser()
            id = getattr(dashboard, "id", 0)
            message_id = id
            chat = getattr(dashboard, "chat", None)

        fake_update = _FakeUpdate()
        if mode == "audio":
            duration = await Mdata03(out_path)
            thumb = await Gthumb01(client, fake_update, task_id=f"audio_{task_id}")
        elif mode == "file":
            thumb = await Gthumb01(client, fake_update, task_id=f"file_{task_id}")
        else:
            width, video_height, duration = await get_video_whd(out_path)
            duration = max(duration or 1, 1)
            thumb = await Gthumb02(client, fake_update, duration, out_path, task_id=task_id)
    except Exception:
        thumb = None

    uploaded_before = 0
    upload_started = time.time()

    async def _upload_progress(current, total, base):
        elapsed = max(time.time() - upload_started, 0.001)
        done = min(total_upload, int(base) + int(current))
        update_task(
            task_id, done, total_upload, int(done / elapsed),
            status="uploading", engine="pyrogram",
        )
        await update_user_progress(client, uid)

    try:
        async with stage_slot(
            "upload", task_id, uid, site=site, client=client, priority=priority
        ):
            set_task_stage(
                task_id, task_type="upload", status="uploading", engine="pyrogram",
                downloaded=0, total_size=total_upload, reset_timer=True,
            )
            await update_user_progress(client, uid, force=True)
            total_parts = len(parts)
            for index, part in enumerate(parts, 1):
                part_size = os.path.getsize(part)
                caption = f"🎬 {safe_title}\n📥 {height}p | ⚡ BIMBO"
                if total_parts > 1:
                    caption += f" | Part {index}/{total_parts}"
                common = dict(
                    chat_id=getattr(getattr(dashboard, "chat", None), "id", uid),
                    caption=caption,
                    thumb=thumb if thumb and os.path.exists(str(thumb)) else None,
                    reply_to_message_id=getattr(dashboard, "id", None),
                    progress=_upload_progress,
                    progress_args=(uploaded_before,),
                )
                if mode == "audio":
                    await client.send_audio(audio=part, duration=duration, **common)
                elif mode == "file":
                    await client.send_document(document=part, **common)
                else:
                    pw, ph, pdur = width, video_height, duration
                    if total_parts > 1:
                        try:
                            pw, ph, pdur = await get_video_whd(part)
                        except Exception:
                            pass
                    await client.send_video(
                        video=part, duration=max(pdur or 1, 1),
                        width=pw or 0, height=ph or 0,
                        supports_streaming=True, **common,
                    )
                uploaded_before += part_size
                update_task(task_id, uploaded_before, total_upload, 0, "uploading", "pyrogram")

    except Exception as exc:
        await _notify_failure(client, uid, dashboard, task_id, safe_title, exc)
        try:
            if thumb and os.path.exists(str(thumb)):
                os.remove(thumb)
        except Exception:
            pass
        _cleanup_workdir()
        return False

    # User upload is delivered: remove the visible card immediately.
    update_task(task_id, total_upload, total_upload, 0, "completed", "pyrogram")
    remove_task(task_id)
    await finalize_user_progress(client, uid, dashboard, delete_if_idle=True)
    try:
        from plugins.user_quota import record_user_download
        record_user_download(uid, original_size)
    except Exception:
        pass

    # Log-channel copies are invisible background uploads. They use the shared
    # upload limiter but do not keep a 100% user card or priority barrier alive.
    async def _background_log_and_cleanup():
        log_task_id = f"log_{uid}_{time.time_ns()}"
        try:
            if Config.BIMBO_LOG_CHANNEL:
                async with stage_slot(
                    "upload", log_task_id, uid, site="log", client=None,
                    priority=0, notify=False,
                ):
                    for index, part in enumerate(parts, 1):
                        await send_log_media(
                            bot=client, user=user, file_path=part,
                            link=webpage_url,
                            file_name=(
                                f"{safe_title} (part {index})"
                                if len(parts) > 1 else safe_title
                            ),
                            media_type=mode,
                            file_size=os.path.getsize(part), thumbnail=thumb,
                            duration=duration, width=width, height=video_height,
                        )
        except Exception:
            pass
        finally:
            try:
                if thumb and os.path.exists(str(thumb)):
                    os.remove(thumb)
            except Exception:
                pass
            _cleanup_workdir()

    asyncio.create_task(_background_log_and_cleanup())
    return True


async def download_and_upload(
    client, status_msg, user, webpage_url, media_url, title, height, mode,
    headers, task_id=None, priority=PRIORITY_NORMAL,
):
    """Priority-aware public entrypoint.

    Interactive single-video jobs hold a lightweight barrier for their complete
    download→upload lifecycle. Active bulk downloads finish naturally, but no
    new bulk item starts until the interactive job is delivered.
    """
    runtime_id = task_id or f"adult_{int(user.id)}_{time.time_ns()}"
    interactive = int(priority) >= PRIORITY_INTERACTIVE
    if interactive:
        await begin_interactive_job(runtime_id)
    try:
        return await _download_and_upload_impl(
            client, status_msg, user, webpage_url, media_url, title, height,
            mode, headers, task_id=runtime_id, priority=priority,
        )
    finally:
        if interactive:
            await end_interactive_job(runtime_id)
