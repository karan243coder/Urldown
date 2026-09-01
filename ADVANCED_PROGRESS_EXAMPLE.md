# 🎨 Advanced Progress UI - Usage Example

Bhai, yeh raha tere **Advanced Progress UI** ka complete example! 🚀

---

## 📱 **How It Looks:**

```
⌬ ***Movie.2024.1080p.BluRay.x264.mp4***
┃ [■■■■■▧□□□□□□□] 42.31%
┠ **Processed:** 120.45MB of 285.88MB
┠ **Status:** [Upload](https://t.me/c/2371166454/2907) | **ETA:** 5m27s
┠ **Speed:** 2.34MB/s | **Elapsed:** 1m29s
┠ **Engine:** PyroMulti v2.2.11
┠ **Mode:** #Leech | #Pyrogram
┠ **User:** 𝔅𝔦𝔪𝔟𝔬 | **ID:** 5071005351
┖ /cancel_fc7b41c57d47efdf

⌬ ***Bot Stats***
┠ **CPU:** 6.9% | **F:** 18.49GB [91.0%]
┠ **RAM:** 42.0% | **UPTIME:** 11h5m35s
┖ **DL:** 0B/s | **UL:** 2.34MB/s
```

---

## 💻 **Code Usage:**

### **Basic Example:**

```python
from plugins.advanced_progress import create_progress_tracker

# Create progress tracker
tracker = create_progress_tracker(
    user_id=5071005351,
    username="Bimbo"
)

# Build progress message
message = tracker.build_progress_message(
    filename="Movie.2024.1080p.mp4",
    current=120450000,  # bytes downloaded
    total=285880000,    # total bytes
    speed=2340000,      # bytes per second
    status_msg="Upload",
    message_link="https://t.me/c/2371166454/2907"
)

# Send message
await client.send_message(
    chat_id=chat_id,
    text=message,
    reply_markup=tracker.get_cancel_button()
)
```

---

## 🔧 **Integration with Downloads:**

### **1. Torrent Download:**

```python
from plugins.advanced_progress import create_progress_tracker, is_task_cancelled
from plugins.torrent_download import download_torrent

async def handle_torrent_download(client, message, url):
    # Create tracker
    tracker = create_progress_tracker(
        user_id=message.from_user.id,
        username=message.from_user.username or "User"
    )
    
    # Send initial message
    progress_msg = await message.reply_text(
        "⏳ Starting download...",
        reply_markup=tracker.get_cancel_button()
    )
    
    # Download with progress
    async def progress_callback(downloaded, total, speed, progress, file_name):
        # Check if cancelled
        if is_task_cancelled(tracker.get_task_id()):
            raise Exception("Download cancelled by user")
        
        # Update progress
        text = tracker.build_progress_message(
            filename=file_name,
            current=downloaded,
            total=total,
            speed=speed,
            status_msg="Download"
        )
        
        await progress_msg.edit_text(text)
    
    result = await download_torrent(
        url=url,
        download_path=f"downloads/{message.from_user.id}",
        progress_callback=progress_callback
    )
    
    # Cleanup
    from plugins.advanced_progress import remove_progress_tracker
    remove_progress_tracker(tracker.get_task_id())
    
    return result
```

---

### **2. YouTube Download:**

```python
from plugins.advanced_progress import create_progress_tracker

async def handle_youtube_download(client, message, url):
    tracker = create_progress_tracker(
        user_id=message.from_user.id,
        username=message.from_user.username
    )
    
    progress_msg = await message.reply_text(
        "⏳ Fetching video info...",
        reply_markup=tracker.get_cancel_button()
    )
    
    # yt-dlp progress hook
    def progress_hook(d):
        if d['status'] == 'downloading':
            downloaded = d.get('downloaded_bytes', 0)
            total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
            speed = d.get('speed', 0) or 0
            filename = d.get('filename', 'Unknown')
            
            text = tracker.build_progress_message(
                filename=filename,
                current=downloaded,
                total=total,
                speed=speed,
                status_msg="Download",
                engine="yt-dlp"
            )
            
            # Update message (async)
            asyncio.run_coroutine_threadsafe(
                progress_msg.edit_text(text),
                loop
            )
    
    # Download with yt-dlp
    ydl_opts = {
        'progress_hooks': [progress_hook],
        # ... other options
    }
    
    # ... rest of download logic
```

---

### **3. Direct Link Download:**

```python
import aiohttp
from plugins.advanced_progress import create_progress_tracker

async def handle_direct_download(client, message, url):
    tracker = create_progress_tracker(
        user_id=message.from_user.id,
        username=message.from_user.username
    )
    
    progress_msg = await message.reply_text(
        "⏳ Connecting...",
        reply_markup=tracker.get_cancel_button()
    )
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            total = int(response.headers.get('content-length', 0))
            downloaded = 0
            start_time = time.time()
            
            filename = url.split('/')[-1]
            
            with open(f"downloads/{filename}", 'wb') as f:
                async for chunk in response.content.iter_chunked(8192):
                    # Check cancellation
                    if is_task_cancelled(tracker.get_task_id()):
                        f.close()
                        os.remove(f"downloads/{filename}")
                        await progress_msg.edit_text("❌ Download cancelled")
                        return
                    
                    f.write(chunk)
                    downloaded += len(chunk)
                    
                    # Calculate speed
                    elapsed = time.time() - start_time
                    speed = downloaded / elapsed if elapsed > 0 else 0
                    
                    # Update progress every 1 second
                    if int(elapsed) % 1 == 0:
                        text = tracker.build_progress_message(
                            filename=filename,
                            current=downloaded,
                            total=total,
                            speed=speed,
                            status_msg="Download",
                            engine="aiohttp"
                        )
                        
                        await progress_msg.edit_text(text)
    
    # Cleanup
    remove_progress_tracker(tracker.get_task_id())
    
    return f"downloads/{filename}"
```

---

## 🎨 **Customization:**

### **Change Progress Bar Style:**

```python
# In advanced_progress.py, modify _get_progress_bar():

def _get_progress_bar(self, percentage, length=13):
    filled = int(length * percentage / 100)
    
    # Style 1: ■▧□ (Current)
    bar = "■" * filled + "▧" + "□" * (length - filled - 1)
    
    # Style 2: ███░░░
    # bar = "█" * filled + "░" * (length - filled)
    
    # Style 3: ▓▓▓░░░
    # bar = "▓" * filled + "░" * (length - filled)
    
    # Style 4: ●●●○○○
    # bar = "●" * filled + "○" * (length - filled)
    
    return f"[{bar}] {percentage:.2f}%"
```

---

### **Change Username Font:**

```python
# In advanced_progress.py, modify _get_fancy_username():

def _get_fancy_username(self, username):
    # Style 1: 𝔉𝔯𝔞𝔨𝔱𝔲𝔯 (Current)
    fancy_map = {
        'a': '𝔞', 'b': '𝔟', # ... etc
    }
    
    # Style 2: 𝓢𝓬𝓻𝓲𝓹𝓽
    # fancy_map = {
    #     'a': '𝓪', 'b': '𝓫', # ... etc
    # }
    
    # Style 3: 𝕯𝖔𝖚𝖇𝖑𝖊
    # fancy_map = {
    #     'a': '𝕒', 'b': '𝕓', # ... etc
    # }
    
    # Style 4: Ⓑⓤⓑⓑⓛⓔ
    # fancy_map = {
    #     'a': 'ⓐ', 'b': 'ⓑ', # ... etc
    # }
    
    fancy_name = ""
    for char in username:
        fancy_name += fancy_map.get(char, char)
    
    return fancy_name
```

---

## 🚀 **Advanced Features:**

### **1. Multiple Downloads Display:**

```python
from plugins.advanced_progress import active_tasks

async def show_all_downloads(client, message):
    if not active_tasks:
        await message.reply_text("📭 No active downloads")
        return
    
    text = "📥 **Active Downloads:**\n\n"
    
    for task_id, tracker in active_tasks.items():
        text += f"┠ Task: `{task_id}`\n"
        text += f"┠ User: {tracker.username} ({tracker.user_id})\n"
        text += f"┖ /cancel_{task_id}\n\n"
    
    await message.reply_text(text)
```

---

### **2. Cancel Handler:**

```python
from pyrogram import filters
from plugins.advanced_progress import cancel_task

@Client.on_message(filters.regex(r'^/cancel_([a-f0-9]{16})$'))
async def handle_cancel(client, message):
    task_id = message.matches[0].group(1)
    
    if cancel_task(task_id):
        await message.reply_text(f"✅ Task `{task_id}` cancelled!")
    else:
        await message.reply_text(f"❌ Task `{task_id}` not found!")
```

---

### **3. Auto-Delete After Upload:**

```python
async def upload_with_auto_delete(client, chat_id, file_path, tracker):
    # Upload file
    msg = await client.send_document(
        chat_id=chat_id,
        document=file_path,
        caption="✅ Download complete!"
    )
    
    # Update progress with upload status
    text = tracker.build_progress_message(
        filename=os.path.basename(file_path),
        current=os.path.getsize(file_path),
        total=os.path.getsize(file_path),
        speed=0,
        status_msg="Complete",
        message_link=msg.link
    )
    
    # Auto-delete after 30 seconds
    await asyncio.sleep(30)
    await msg.delete()
```

---

## 📊 **Performance Tips:**

### **1. Update Interval:**
```python
# Don't update too frequently (Telegram rate limit)
# Update every 1-2 seconds max

last_update = 0
current_time = time.time()

if current_time - last_update >= 1.0:  # 1 second
    await progress_msg.edit_text(text)
    last_update = current_time
```

---

### **2. Batch Updates:**
```python
# If downloading multiple files, show summary
text = f"""⌬ ***Batch Download***
┃ [■■■■■▧□□□□□□□] 42.31%
┠ **Files:** 5/12 complete
┠ **Total:** 1.2GB / 2.8GB
┠ **Speed:** 5.2MB/s
┖ /cancel_{task_id}
"""
```

---

## 🎯 **Best Practices:**

1. ✅ **Always create tracker** before download starts
2. ✅ **Check cancellation** in download loop
3. ✅ **Remove tracker** after completion
4. ✅ **Handle errors** gracefully
5. ✅ **Update every 1-2 seconds** (not too fast)
6. ✅ **Show meaningful info** (speed, ETA, progress)
7. ✅ **Use cancel button** for user control

---

## 💪 **Summary:**

**Advanced Progress UI Features:**
- ✅ Beautiful progress bar with special characters
- ✅ Real-time system stats (CPU, RAM, Disk)
- ✅ Speed and ETA calculation
- ✅ Task ID for cancellation
- ✅ User info with fancy font
- ✅ Engine and mode display
- ✅ Bot stats section
- ✅ Cancel button support
- ✅ Customizable styling

**Integration:**
- ✅ Works with Torrent downloads
- ✅ Works with YouTube downloads
- ✅ Works with Direct links
- ✅ Works with any download method

---

**Ab tera bot WZML-X jaisa professional dikhega!** 🚀
