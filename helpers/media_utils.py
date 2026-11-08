import asyncio
import json
import os
import logging

logger = logging.getLogger(__name__)

async def get_video_metadata(file_path: str):
    """Safely extracts width, height, and duration with zero JSON decoding crashes."""
    if not file_path or not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
        return {"width": 1280, "height": 720, "duration": 0}

    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration:stream=width,height,codec_type",
        "-of", "json",
        file_path
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        
        if not stdout or not stdout.strip():
            logger.warning(f"FFprobe returned empty stdout for {file_path}")
            return {"width": 1280, "height": 720, "duration": 0}

        data = json.loads(stdout.decode("utf-8", errors="ignore"))
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
    """Extracts a clean image frame without audio or subtitle interference."""
    if not video_path or not os.path.exists(video_path):
        return None

    cmd = [
        "ffmpeg",
        "-ss", str(timestamp_sec),
        "-i", video_path,
        "-map", "0:v:0",
        "-an",
        "-sn",
        "-vframes", "1",
        "-q:v", "2",
        "-y",
        thumb_path
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL
    )
    await proc.communicate()

    # Fallback to second 1 if timestamp_sec exceeds total video length
    if not os.path.exists(thumb_path) or os.path.getsize(thumb_path) == 0:
        cmd_fallback = [
            "ffmpeg",
            "-ss", "1",
            "-i", video_path,
            "-map", "0:v:0",
            "-an",
            "-sn",
            "-vframes", "1",
            "-q:v", "2",
            "-y",
            thumb_path
        ]
        proc_fb = await asyncio.create_subprocess_exec(
            *cmd_fallback,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL
        )
        await proc_fb.communicate()

    return thumb_path if os.path.exists(thumb_path) and os.path.getsize(thumb_path) > 0 else None

async def extract_sample_clip(video_path: str, start_time: str, duration: int, output_path: str):
    """
    3-Tier Sample Slicer:
    Tier 1: Video stream copy + 2-channel AAC transcode + Subtitle strip (-sn) + HEVC tag.
    Tier 2: Ultrafast libx264 re-encode with yuv420p color matrix.
    Tier 3: Stream copy into MKV container fallback.
    """
    if os.path.exists(output_path):
        try:
            os.remove(output_path)
        except Exception:
            pass

    # Tier 1: Instant Stream Copy Video + Stereo AAC Audio (Bypasses MKV subtitle crashes)
    cmd_tier1 = [
        "ffmpeg",
        "-ss", str(start_time),
        "-i", video_path,
        "-t", str(duration),
        "-map", "0:v:0",
        "-map", "0:a:0?",
        "-sn",
        "-dn",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "128k",
        "-ac", "2",
        "-tag:v", "hvc1",
        "-avoid_negative_ts", "make_zero",
        "-movflags", "+faststart",
        "-y",
        output_path
    ]
    proc1 = await asyncio.create_subprocess_exec(
        *cmd_tier1,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    _, stderr1 = await proc1.communicate()

    if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
        return output_path

    # Tier 2: Universal Ultrafast Re-encode
    logger.warning(f"Tier 1 copy failed: {stderr1.decode(errors='ignore')[:200]}. Attempting Tier 2 re-encode...")
    cmd_tier2 = [
        "ffmpeg",
        "-ss", str(start_time),
        "-i", video_path,
        "-t", str(duration),
        "-map", "0:v:0",
        "-map", "0:a:0?",
        "-sn",
        "-dn",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "26",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "128k",
        "-ac", "2",
        "-avoid_negative_ts", "make_zero",
        "-movflags", "+faststart",
        "-y",
        output_path
    ]
    proc2 = await asyncio.create_subprocess_exec(
        *cmd_tier2,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    _, stderr2 = await proc2.communicate()

    if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
        return output_path

    # Tier 3: Native MKV Container Fallback
    logger.warning(f"Tier 2 failed: {stderr2.decode(errors='ignore')[:200]}. Attempting Tier 3 MKV container fallback...")
    output_mkv = output_path.rsplit(".", 1)[0] + ".mkv"
    cmd_tier3 = [
        "ffmpeg",
        "-ss", str(start_time),
        "-i", video_path,
        "-t", str(duration),
        "-map", "0:v:0",
        "-map", "0:a:0?",
        "-sn",
        "-dn",
        "-c", "copy",
        "-y",
        output_mkv
    ]
    proc3 = await asyncio.create_subprocess_exec(
        *cmd_tier3,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    _, stderr3 = await proc3.communicate()

    if os.path.exists(output_mkv) and os.path.getsize(output_mkv) > 1000:
        return output_mkv

    logger.error(f"All sample generation tiers failed! Last error: {stderr3.decode(errors='ignore')}")
    return None
