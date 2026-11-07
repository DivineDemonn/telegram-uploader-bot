import asyncio
import os
import re
import logging

logger = logging.getLogger(__name__)

async def download_content(uri_or_path: str, download_dir: str, status_msg):
    """
    Downloads direct URLs, tokenized CDN files, magnet links, or .torrent files
    using maximum-speed aria2c parameters.
    """
    cmd = [
        "aria2c",
        "--enable-dht=true",
        "--dht-listen-port=6881",
        "--bt-enable-lpd=true",
        "--enable-peer-exchange=true",
        "--max-connection-per-server=16",
        "--split=16",
        "--min-split-size=1M",
        "--disk-cache=64M",
        "--file-allocation=none",
        "--max-overall-download-limit=0",
        "--max-download-limit=0",
        "--seed-time=0",
        "--summary-interval=3",
        "--allow-overwrite=true",
        f"--dir={download_dir}",
        uri_or_path
    ]

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )

    # Monitor aria2 console output to relay speed and completion percentage
    speed_pattern = re.compile(r"\((\d+%?)\)\s+CN:\d+\s+DL:([0-9\.]+[A-Za-z]+)")
    last_update = 0

    while True:
        line = await process.stdout.readline()
        if not line:
            break
        decoded_line = line.decode("utf-8", errors="ignore").strip()
        match = speed_pattern.search(decoded_line)
        if match:
            now = asyncio.get_event_loop().time()
            if now - last_update > 4:
                progress_pct = match.group(1)
                speed = match.group(2)
                try:
                    await status_msg.edit_text(
                        f"⚡ **Aria2 Leeching in Progress**\n\n"
                        f"📊 **Progress:** `{progress_pct}`\n"
                        f"🚀 **Railway Network Speed:** `{speed}/s`"
                    )
                    last_update = now
                except Exception:
                    pass

    await process.wait()

    if process.returncode != 0:
        err = await process.stderr.read()
        logger.error(f"Aria2 download error: {err.decode('utf-8', errors='ignore')}")
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
