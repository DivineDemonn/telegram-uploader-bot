import asyncio
import json
import os
import logging

logger = logging.getLogger(__name__)

async def get_video_metadata(file_path: str):
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
        width, height = 1280, 720
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video":
                width = int(stream.get("width", 1280))
                height = int(stream.get("height", 720))
                break
        return {"width": width, "height": height, "duration": duration}
    except Exception as e:
        logger.error(f"FFprobe metadata error: {e}")
        return {"width": 1280, "height": 720, "duration": 0}

async def generate_thumbnail(video_path: str, thumb_path: str, timestamp_sec: int = 10):
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
    First attempts stream-copying for instant extraction; falls back to ultrafast re-encode.
    """
    cmd = [
        "ffmpeg",
        "-ss", str(start_time),
        "-i", video_path,
        "-t", str(duration),
        "-c", "copy",
        "-map", "0",
        "-y",
        output_path
    ]
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
    await proc.communicate()

    if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
        cmd_reencode = [
            "ffmpeg",
            "-ss", str(start_time),
            "-i", video_path,
            "-t", str(duration),
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-c:a", "aac",
            "-y",
            output_path
        ]
        proc = await asyncio.create_subprocess_exec(*cmd_reencode, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        await proc.communicate()

    return output_path if os.path.exists(output_path) and os.path.getsize(output_path) > 0 else None
