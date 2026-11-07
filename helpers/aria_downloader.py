import asyncio
import os
import glob
import logging

logger = logging.getLogger(__name__)

async def download_file(uri_or_path: str, download_dir: str):
    """
    Downloads via aria2c CLI. Supports direct URLs, magnet URIs, and .torrent files.
    """
    cmd = [
        "aria2c",
        "--enable-dht=true",
        "--dht-listen-port=6881",
        "--bt-enable-lpd=true",
        "--enable-peer-exchange=true",
        "--max-connection-per-server=8",
        "--split=8",
        "--min-split-size=1M",
        "--seed-time=0",
        "--summary-interval=5",
        "--allow-overwrite=true",
        f"--dir={download_dir}",
        uri_or_path
    ]

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )

    stdout, stderr = await process.communicate()

    if process.returncode != 0:
        err = stderr.decode().strip() or stdout.decode().strip()
        logger.error(f"aria2c error: {err}")
        return None

    # Locate the largest file in the target directory (ignores .aria2 metadata)
    files = [
        os.path.join(download_dir, f)
        for f in os.listdir(download_dir)
        if not f.endswith(".aria2") and not f.endswith(".torrent")
    ]
    if not files:
        return None

    # Return the largest downloaded file
    downloaded_file = max(files, key=os.path.getsize)
    return downloaded_file
