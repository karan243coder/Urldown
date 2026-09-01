# BIMBO URL Bot v4.0 - ULTIMATE EDITION
import os
import sys
import asyncio
import logging
import threading
import subprocess
import time
import shutil
from http.server import HTTPServer, BaseHTTPRequestHandler

from config import Config
from pyrogram import Client as BimboBot

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logging.getLogger("pyrogram").setLevel(logging.WARNING)
logging.getLogger("pymongo").setLevel(logging.WARNING)
logging.getLogger("pymongo.topology").setLevel(logging.WARNING)
if Config.BIMBO_VERBOSE_LOG:
    logging.getLogger().setLevel(logging.DEBUG)
logger = logging.getLogger(__name__)

HEALTH_PORT = int(os.environ.get("PORT", 8080))


# ------------------------------------------------------------------
# Health HTTP Server
# ------------------------------------------------------------------
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK - BIMBO v4.0 Running")

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

    def log_message(self, format, *args):
        pass


def run_health_server():
    server = HTTPServer(("0.0.0.0", HEALTH_PORT), HealthHandler)
    logger.info(f"✅ Health server listening on port {HEALTH_PORT}")
    server.serve_forever()


# ------------------------------------------------------------------
# Aria2 Daemon (tuned)
# ------------------------------------------------------------------
def start_aria2_daemon():
    try:
        subprocess.run(["aria2c", "--version"], capture_output=True, check=True)
    except FileNotFoundError:
        logger.warning("⚠️  aria2 not installed. apt-get install -y aria2")
        return False
    except Exception as e:
        logger.warning(f"⚠️  aria2 check failed: {e}")
        return False

    download_dir = os.path.abspath(Config.BIMBO_DOWNLOAD_LOCATION)
    aria2_dir = os.path.join(download_dir, ".aria2")
    os.makedirs(aria2_dir, exist_ok=True)
    os.makedirs(download_dir, exist_ok=True)

    # Kill stale aria2 processes (safely — procps available via Dockerfile, fall back to pid-file)
    try:
        subprocess.run(["pkill", "-f", "aria2c"], capture_output=True, check=False)
    except FileNotFoundError:
        # pkill not available — kill any leftover aria2c via PID file if exists
        pid_file = "/tmp/aria2d.pid"
        if os.path.exists(pid_file):
            try:
                with open(pid_file) as f:
                    os.kill(int(f.read().strip()), 15)
            except Exception:
                pass
        # Last resort: kill aria2 by shell if /proc available
        try:
            subprocess.run(["sh", "-c", "kill -9 $(pgrep aria2c) 2>/dev/null || true"],
                           capture_output=True, check=False)
        except Exception:
            pass
    time.sleep(1)

    session_file = os.path.join(aria2_dir, "aria2.session")
    log_file = os.path.join(aria2_dir, "aria2.log")
    open(session_file, "a").close()

    cmd = [
        "aria2c", "--daemon=true",
        "--enable-rpc=true", "--rpc-listen-all=true",
        "--rpc-allow-origin-all=true", "--rpc-listen-port=6800",
        "--max-concurrent-downloads=20",
        "--max-connection-per-server=16",
        "--max-file-not-found=5",
        "--min-split-size=1M", "--split=16",
        "--continue=true",
        "--max-overall-download-limit=0",
        "--max-download-limit=0",
        "--file-allocation=none",
        "--allow-overwrite=true",
        "--auto-file-renaming=false",
        "--disk-cache=64M",
        f"--dir={download_dir}",
        f"--input-file={session_file}",
        f"--save-session={session_file}",
        "--save-session-interval=30",
        f"--log={log_file}",
        "--log-level=error",
        "--summary-interval=0",
        "--console-log-level=warn",
        "--enable-color=false",
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode == 0:
        logger.info(
            f"✅ Aria2 RPC ready — dir={download_dir}, split=16, conns=16, port=6800"
        )
        return True
    logger.warning(f"⚠️  Aria2 start: {r.stderr.strip()}")
    return False


# ------------------------------------------------------------------
# Auto Cleanup (disk protection for Koyeb)
# ------------------------------------------------------------------
def auto_cleanup_loop():
    hours = max(0, int(Config.BIMBO_AUTO_CLEANUP_HOURS or 0))
    if hours <= 0:
        return
    threshold = hours * 3600
    download_dir = os.path.abspath(Config.BIMBO_DOWNLOAD_LOCATION)
    check_every = 900
    while True:
        try:
            time.sleep(check_every)
            now = time.time()
            cleaned = 0
            for root, dirs, files in os.walk(download_dir):
                if ".aria2" in root:
                    continue
                for name in files + dirs:
                    p = os.path.join(root, name)
                    try:
                        if now - os.path.getmtime(p) > threshold:
                            if os.path.isdir(p):
                                shutil.rmtree(p, ignore_errors=True)
                            else:
                                os.remove(p)
                            cleaned += 1
                    except Exception:
                        pass
            if cleaned:
                logger.info(f"🧹 Auto-cleanup removed {cleaned} old item(s)")
        except Exception as e:
            logger.error(f"Cleanup error: {e}")


# ------------------------------------------------------------------
# Ensure required directories exist
# ------------------------------------------------------------------
def _ensure_dirs():
    for d in [
        Config.BIMBO_DOWNLOAD_LOCATION,
        "data", "thumbnails", "logs",
    ]:
        os.makedirs(d, exist_ok=True)


if __name__ == "__main__":
    _ensure_dirs()
    logger.info(f"📂 Download dir: {os.path.abspath(Config.BIMBO_DOWNLOAD_LOCATION)}")
    logger.info(f"🧑 Owner ID: {Config.BIMBO_OWNER_ID} | "
                f"🔧 Workers: {Config.BIMBO_WORKERS} | "
                f"🚀 Concurrent tasks: {Config.BIMBO_MAX_CONCURRENT_TASKS}")
    if Config.MAINTENANCE_MODE:
        logger.warning("⚠️  MAINTENANCE_MODE is ON — only owner can use bot.")

    # Single-port mode (Koyeb/Render): stream server khud HEALTH_PORT pe chalega
    # aur "/" pe health check bhi de dega — isliye purana threaded health server
    # tabhi start karo jab stream server alag port maang raha ho.
    _single_port = not bool(Config.BIMBO_STREAM_PORT)
    if not _single_port:
        threading.Thread(target=run_health_server, daemon=True).start()
    threading.Thread(target=start_aria2_daemon, daemon=True).start()
    
    # Start qBittorrent daemon if enabled
    if Config.QB_ENABLED:
        try:
            from plugins.qbittorrent_manager import start_qbittorrent_daemon
            threading.Thread(target=lambda: asyncio.run(start_qbittorrent_daemon()), daemon=True).start()
            time.sleep(2)  # Wait for daemon to start
        except Exception as e:
            logger.warning(f"qBittorrent daemon startup failed: {e}")
    
    time.sleep(2)
    threading.Thread(target=auto_cleanup_loop, daemon=True).start()

    plugins = dict(root="plugins")
    BIMBO_CLIENT = BimboBot(
        name=Config.BIMBO_SESSION_NAME or "BIMBO_BOT",
        bot_token=Config.BIMBO_BOT_TOKEN,
        api_id=Config.BIMBO_API_ID,
        api_hash=Config.BIMBO_API_HASH,
        plugins=plugins,
        workers=Config.BIMBO_WORKERS,
        max_concurrent_transmissions=8,
        sleep_threshold=30,
    )

    logger.info("🚀 BIMBO v4.0 starting up...")
    try:
        # Start client manually so we can start auto-cleaner immediately (100% reliable)
        import asyncio
        BIMBO_CLIENT.start()
        try:
            # Start auto-cleaner reaper right after bot starts
            from plugins.auto_cleaner import start_cleaner
            loop = asyncio.get_event_loop()
            loop.create_task(start_cleaner(BIMBO_CLIENT))
            logger.info(" Auto-cleaner hooked at startup")
            
            # Start stuck task cleanup (runs every 60 seconds)
            async def periodic_cleanup():
                while True:
                    await asyncio.sleep(60)
                    try:
                        from helper_funcs.display_progress import cleanup_stuck_tasks
                        from config import Config as _Cfg
                        await cleanup_stuck_tasks(
                            BIMBO_CLIENT,
                            max_age_seconds=getattr(_Cfg, "BIMBO_STALL_TIMEOUT", 360),
                        )
                    except Exception as e:
                        logger.debug(f"Periodic cleanup error: {e}")
            
            loop.create_task(periodic_cleanup())
            logger.info(" Stuck task cleanup hooked at startup (60s interval)")
            
            # Initialize qBittorrent if enabled
            if Config.QB_ENABLED:
                try:
                    from plugins.qbittorrent_manager import init_qbittorrent
                    loop.create_task(init_qbittorrent())
                    logger.info("🧲 qBittorrent initialization started")
                except Exception as qe:
                    logger.warning(f"qBittorrent init failed: {qe}")
        except Exception as ce:
            logger.warning(f"Cleaner startup hook failed (will auto-start on first msg): {ce}")
        # Start the video stream server (/watch, /dl) for /stream links.
        # Default (single-port): stream server HEALTH_PORT (8080) pe chalega —
        # Koyeb ke ek public port me sab fit. Alag port chahiye to
        # BIMBO_STREAM_PORT set kar do (VPS pe useful).
        try:
            from stream_server import start_stream_server
            stream_port = Config.BIMBO_STREAM_PORT or HEALTH_PORT
            loop.create_task(start_stream_server(BIMBO_CLIENT, stream_port))
            logger.info(f"🎬 Stream server hooked on port {stream_port} "
                        f"({'single-port' if stream_port == HEALTH_PORT else 'separate port'})")
        except Exception as se:
            logger.warning(f"Stream server startup failed: {se}")
        # idle
        from pyrogram import idle
        idle()
        BIMBO_CLIENT.stop()
    except Exception as e:
        logger.critical(f"❌ Fatal error: {e}", exc_info=True)
        sys.exit(1)
