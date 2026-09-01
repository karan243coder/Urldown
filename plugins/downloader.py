import os
import re
import asyncio
import logging
from config import Config
from utils import safe_filename, user_download_dir

logger = logging.getLogger(__name__)

async def download_file(url: str, progress_callback, message) -> dict:
    """
    Downloads a file using yt-dlp / aria2c and streams progress to progress_callback.
    """
    try:
        user_id = message.from_user.id
        download_dir = user_download_dir(user_id)
        out_tpl = os.path.join(download_dir, "%(title).150B [%(id)s].%(ext)s")
        
        cmd = [
            "yt-dlp", "--no-warnings", "-c", "--newline",
            "--geo-bypass", "--no-check-certificates",
            "--buffer-size", "16M",
            "--retries", "10", "--fragment-retries", "10",
            "--concurrent-fragments", str(Config.YTDLP_CONCURRENT_FRAGMENTS),
            "--add-header", "User-Agent:Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36",
            "-o", out_tpl,
            url
        ]
        
        # Check if cookie file exists
        if os.path.exists("cookies.txt"):
            cmd += ["--cookies", "cookies.txt"]
            
        if Config.YTDLP_USE_ARIA2C:
            cmd += [
                "--downloader", "aria2c",
                "--downloader-args", "aria2c:-x 16 -s 16 -k 1M --file-allocation=none --max-tries=10 --retry-wait=2",
            ]
            
        logger.info(f"Queue executing download for URL: {url} with command: {cmd}")
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT
        )
        
        filename = None
        total_size = 0
        downloaded = 0
        speed = 0
        
        # Regex to parse yt-dlp progress
        percent_re = re.compile(r'(\d+\.?\d*)%')
        size_re = re.compile(r'of\s+~?\s*([\d\.]+\s*[KMGTP]?i?B)')
        speed_re = re.compile(r'at\s+([\d\.]+\s*[KMGTP]?i?B/s)')
        
        def parse_bytes(size_str):
            units = {'b': 1, 'kb': 1024, 'mb': 1024**2, 'gb': 1024**3, 'tb': 1024**4,
                     'kib': 1024, 'mib': 1024**2, 'gib': 1024**3, 'tib': 1024**4}
            m = re.match(r'([\d\.]+)\s*([a-zA-Z]+)', size_str.lower())
            if m:
                val, unit = m.groups()
                return int(float(val) * units.get(unit, 1))
            return 0

        while True:
            line = await process.stdout.readline()
            if not line:
                break
            
            line_str = line.decode(errors="ignore").strip()
            
            # Parsing yt-dlp's standard output
            if "[download]" in line_str and "%" in line_str:
                pct_match = percent_re.search(line_str)
                size_match = size_re.search(line_str)
                spd_match = speed_re.search(line_str)
                
                pct = float(pct_match.group(1)) if pct_match else 0.0
                
                if size_match:
                    total_size = parse_bytes(size_match.group(1))
                    
                if spd_match:
                    speed = parse_bytes(spd_match.group(1).replace('/s', ''))
                
                if total_size > 0:
                    downloaded = int((pct / 100) * total_size)
                    
                # Call callback
                if progress_callback:
                    await progress_callback(downloaded, total_size, speed)
            
            # Destination parsing to find file name
            elif "[download] Destination:" in line_str:
                filename = line_str.split("Destination:")[-1].strip()
            elif "[Merger] Merging formats into" in line_str:
                filename = line_str.split("into")[-1].strip().replace('"', '')
                
        await process.wait()
        
        # Fallback to look up file in download directory if filename not found
        if not filename or not os.path.exists(filename):
            files = [os.path.join(download_dir, f) for f in os.listdir(download_dir) if os.path.isfile(os.path.join(download_dir, f))]
            if files:
                files.sort(key=lambda x: os.path.getmtime(x), reverse=True)
                filename = files[0]
                
        if process.returncode == 0 and filename and os.path.exists(filename):
            return {'success': True, 'filename': filename}
        else:
            return {'success': False, 'error': f"yt-dlp returned {process.returncode}"}
            
    except Exception as e:
        logger.error(f"Error downloading file: {e}")
        return {'success': False, 'error': str(e)}
