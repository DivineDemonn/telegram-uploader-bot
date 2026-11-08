import asyncio
import os
import re
import logging

logger = logging.getLogger(__name__)

# Premium public seeder trackers injected into all torrent/magnet tasks
HIGH_SPEED_TRACKERS = (
    "udp://tracker.opentrackr.org:1337/announce,"
    "udp://tracker.torrent.eu.org:451/announce,"
    "udp://tracker.dler.org:6969/announce,"
    "udp://open.stealth.si:80/announce,"
    "udp://open.demonii.com:1337/announce,"
    "udp://tracker.srv00.com:6969/announce,"
    "https://tracker.moeblog.cn:443/announce,"
    "https://tracker.pmman.tech:443/announce,"
    "udp://open.dstud.io:6969/announce"
)

async def download_content(uri_or_path: str, download_dir: str, status_msg):
    """
    Downloads direct URLs, tokenized CDN streams, magnet links, or .torrent files
    using maximum-speed multi-connection aria2c.
    """
    cmd = [
        "aria2c",
        "--enable-dht=true",
        "--bt-enable-lpd=true",
        "--enable-peer-exchange=true",
        "--dht-listen-port=6881",
        f"--bt-tracker={HIGH_SPEED_TRACKERS}",
        "--max-connection-per-server=16",
        "--split=16",
        "--min-split-size=1M",
        "--disk-cache=64M",
        "--file-allocation=none",
        "--max-overall-download-limit=0",
        "--max-download-limit=0",
        "--seed-time=0",
        "--summary-interval=2",
        "--allow-overwrite=true",
        f"--dir={download_dir}",
        uri_or_path
    ]

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )

    speed_regex = re.compile(r"\((\d+%?)\)\s+CN:\d+\s+DL:([0-9\.]+[A-Za-z]+)")
    last_update = 0

    while True:
        line = await process.stdout.readline()
        if not line:
            break
        decoded = line.decode("utf-8", errors="ignore").strip()
        match = speed_regex.search(decoded)
        if match:
            now = asyncio.get_event_loop().time()
            if (now - last_update) > 3.5:
                pct = match.group(1)
                speed = match.group(2)
                try:
                    await status_msg.edit_text(
                        f"⚡ **Aria2 Leech Engine**\n\n"
                        f"📊 **Progress:** `{pct}`\n"
                        f"🚀 **Network Speed:** `{speed}/s`\n"
                        f"🌐 **Trackers:** `9 Active Seeder Hubs`"
                    )
                    last_update = now
                except Exception:
                    pass

    await process.wait()

    if process.returncode != 0:
        err = await process.stderr.read()
        logger.error(f"aria2c execution error: {err.decode('utf-8', errors='ignore')}")
        return None

    # Discover the final downloaded file, ignoring metadata and torrent files
    extracted_files = [
        os.path.join(download_dir, f)
        for f in os.listdir(download_dir)
        if not f.endswith(".aria2") and not f.endswith(".torrent")
    ]
    if not extracted_files:
        return None

    return max(extracted_files, key=os.path.getsize)
