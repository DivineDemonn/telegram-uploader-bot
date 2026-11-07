import asyncio
import json
import os
import logging

logger = logging.getLogger(__name__)

async def get_video_metadata(file_path: str):
    """Fetches width, height, and duration of a video file using ffprobe."""
    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        file_path
    ]
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    stdout, _ = await proc.communicate()
    
    try:
        data = json.loads(stdout.decode())
        duration = int(float(data.get("format", {}).get("duration", 0)))
        width, height = 0, 0
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video":
                width = int(stream.get("width", 0))
                height = int(stream.get("height", 0))
                break
        return {"width": width, "height": height, "duration": duration}
    except Exception as e:
        logger.error(f"Error reading metadata: {e}")
        return {"width": 0, "height": 0, "duration": 0}

async def generate_thumbnail(video_path: str, thumb_path: str, timestamp_sec: int = 5):
    """Extracts a frame from the video as a thumbnail."""
    cmd = [
        "ffmpeg",
        "-ss", str(timestamp_sec),
        "-i", video_path,
        "-vframes", "1",
        "-q:v", "2",
        "-y",
        thumb_path
    ]
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
    await proc.communicate()
    return thumb_path if os.path.exists(thumb_path) else None

async def extract_sample_clip(video_path: str, start_time: str, duration: int, output_path: str):
    """
    Extracts a sample clip.
    start_time: 'HH:MM:SS' or seconds
    duration: duration of sample in seconds
    """
    cmd = [
        "ffmpeg",
        "-ss", str(start_time),
        "-i", video_path,
        "-t", str(duration),
        "-c", "copy",
        "-y",
        output_path
    ]
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
    await proc.communicate()

    # If stream copy fails, re-encode quickly
    if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
        cmd_fallback = [
            "ffmpeg",
            "-ss", str(start_time),
            "-i", video_path,
            "-t", str(duration),
            "-preset", "ultrafast",
            "-y",
            output_path
        ]
        proc = await asyncio.create_subprocess_exec(*cmd_fallback, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        await proc.communicate()

    return output_path if os.path.exists(output_path) and os.path.getsize(output_path) > 0 else None
