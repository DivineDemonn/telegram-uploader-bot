import asyncio

# Initialize event loop before Pyrogram imports to prevent Python 3.12+ crash
try:
    asyncio.get_event_loop()
except RuntimeError:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

import os
import re
import time
import shutil
import logging
from pyrogram import Client, filters, idle
from pyrogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery
)
from pyrogram.errors import FloodWait, MessageNotModified

import config
import database
from helpers.aria_downloader import download_content
from helpers.media_utils import get_video_metadata, generate_thumbnail, extract_sample_clip
from helpers.progress import ProgressTracker, human_readable_size

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

ACTIVE_TASKS = {}

# --- 1. Periodic Temp Storage Cleaner ---
async def disk_cleanup_worker():
    """Wipes orphaned files older than 30 minutes to preserve dyno disk."""
    while True:
        await asyncio.sleep(1800)
        now = time.time()
        for root, _, files in os.walk(config.DOWNLOAD_DIR):
            for file in files:
                file_path = os.path.join(root, file)
                try:
                    if os.path.exists(file_path) and (now - os.path.getmtime(file_path) > 1800):
                        os.remove(file_path)
                except Exception:
                    pass

# --- 2. Pyrogram Client ---
bot = Client(
    "heroku_uploader_bot",
    api_id=config.API_ID,
    api_hash=config.API_HASH,
    bot_token=config.BOT_TOKEN,
    max_concurrent_transmissions=4
)

# --- 3. Timing & Range Parser Helper ---
def parse_time_seconds(time_val: str) -> int:
    if not time_val:
        return 0
    parts = time_val.strip().split(":")
    try:
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(float(parts[2]))
        elif len(parts) == 2:
            return int(parts[0]) * 60 + int(float(parts[1]))
        elif len(parts) == 1:
            return int(float(parts[0]))
    except Exception:
        return 0
    return 0

def format_seconds(seconds: int) -> str:
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"

def parse_sample_arguments(args: list):
    clean_args = []
    extracted_uri = None
    for a in args:
        if a.startswith("http://") or a.startswith("https://") or a.startswith("magnet:?"):
            extracted_uri = a
        else:
            clean_args.append(a)

    raw_timing = " ".join(clean_args).strip()
    start_str = "00:01:00"
    duration = 30

    if not raw_timing:
        return start_str, duration, extracted_uri

    # Format: "00:05:00 to 00:05:55"
    if " to " in raw_timing.lower():
        parts = re.split(r"\s+to\s+", raw_timing, flags=re.IGNORECASE)
        if len(parts) == 2:
            s_sec = parse_time_seconds(parts[0])
            e_sec = parse_time_seconds(parts[1])
            dur = (e_sec - s_sec) if e_sec > s_sec else 30
            return format_seconds(s_sec), dur, extracted_uri

    # Format: "00:05:00 - 00:05:55"
    if "-" in raw_timing and not raw_timing.startswith("-"):
        parts = raw_timing.split("-")
        if len(parts) == 2:
            s_sec = parse_time_seconds(parts[0])
            e_sec = parse_time_seconds(parts[1])
            dur = (e_sec - s_sec) if e_sec > s_sec else 30
            return format_seconds(s_sec), dur, extracted_uri

    # Format: "00:05:00 45"
    if len(clean_args) >= 2:
        arg1, arg2 = clean_args[0], clean_args[1]
        s_sec = parse_time_seconds(arg1)
        if ":" in arg2:
            e_sec = parse_time_seconds(arg2)
            dur = (e_sec - s_sec) if e_sec > s_sec else 30
            return format_seconds(s_sec), dur, extracted_uri
        elif arg2.isdigit():
            return format_seconds(s_sec), int(arg2), extracted_uri

    # Single argument: "00:05:00" or "45"
    if len(clean_args) == 1:
        arg = clean_args[0]
        if ":" in arg:
            return format_seconds(parse_time_seconds(arg)), 30, extracted_uri
        elif arg.isdigit():
            return "00:01:00", int(arg), extracted_uri

    return start_str, duration, extracted_uri

# --- 4. Core Bot Commands ---
@bot.on_message(filters.command("start"))
async def start_command(_, message: Message):
    user_id = message.from_user.id
    username = message.from_user.username
    is_owner = (user_id == config.OWNER_ID)
    
    authorized = await database.is_user_authorized(user_id, username)
    status_badge = "👑 **OWNER**" if is_owner else ("✅ **AUTHORIZED**" if authorized else "⛔ **UNAUTHORIZED**")

    ui_text = (
        f"⚡ **High-Speed Leech & Uploader Bot**\n\n"
        f"🆔 **Your User ID:** `{user_id}`\n"
        f"👑 **Owner ID:** `{config.OWNER_ID}`\n"
        f"🔰 **Access Status:** {status_badge}\n\n"
        "**Supported Inputs:**\n"
        "• Direct Download Links (`.mp4`, `.mkv`, zip files)\n"
        "• Magnet links (`magnet:?xt=...`)\n"
        "• `.torrent` files\n"
        "• Forwarded Telegram Videos & Documents\n\n"
        "**Sample Video Commands:**\n"
        "• Reply to any file or link with:\n"
        "  `/sample 00:05:00 to 00:05:55`\n"
        "  `/sample 00:05:00 45`\n"
        "• Or send direct with link:\n"
        "  `/sample 00:05:00 30 [link]`"
    )
    await message.reply_text(ui_text)

@bot.on_message(filters.command(["allow", "auth"]) & filters.user(config.OWNER_ID))
async def allow_command(_, message: Message):
    if len(message.command) < 2:
        return await message.reply_text("Usage:\n`/allow 123456789`\nor\n`/allow @username`")
    target = message.command[1]
    success, msg = await database.authorize_user(target)
    await message.reply_text(msg)

@bot.on_message(filters.command(["ban", "unauth"]) & filters.user(config.OWNER_ID))
async def ban_command(_, message: Message):
    if len(message.command) < 2:
        return await message.reply_text("Usage:\n`/ban 123456789`\nor\n`/ban @username`")
    target = message.command[1]
    success, msg = await database.unauthorize_user(target)
    await message.reply_text(msg)

@bot.on_message(filters.command("users") & filters.user(config.OWNER_ID))
async def users_command(_, message: Message):
    users = await database.get_all_authorized_users()
    reply = f"👑 **Master Owner ID:** `{config.OWNER_ID}`\n\n**MongoDB Whitelisted Users:**\n"
    reply += "\n".join([f"• {u}" for u in users]) if users else "• _No external users whitelisted._"
    await message.reply_text(reply)

# --- 5. Custom /sample Video Handler ---
@bot.on_message(filters.command("sample") & filters.private)
async def sample_command_handler(_, message: Message):
    user_id = message.from_user.id
    username = message.from_user.username
    if not await database.is_user_authorized(user_id, username):
        return await message.reply_text("⛔ You are not authorized to use this bot.")

    args = message.command[1:]
    start_time, duration, uri = parse_sample_arguments(args)
    telegram_target = None

    if message.reply_to_message:
        replied = message.reply_to_message
        if replied.video or replied.document:
            if replied.document and replied.document.file_name and replied.document.file_name.lower().endswith(".torrent"):
                uri = await replied.download(file_name=os.path.join(config.DOWNLOAD_DIR, f"{replied.id}.torrent"))
            else:
                telegram_target = replied
        
        if not telegram_target and not uri:
            text = replied.text or replied.caption or ""
            for word in text.split():
                if word.startswith("http://") or word.startswith("https://") or word.startswith("magnet:?"):
                    uri = word.strip()
                    break

    if not uri and not telegram_target:
        return await message.reply_text(
            "ℹ️ **How to use /sample:**\n\n"
            "**1. Reply to any video / .mkv file in Telegram:**\n"
            "`/sample 00:05:00 to 00:05:55`\n"
            "`/sample 00:05:00 45`\n\n"
            "**2. With a direct link or magnet:**\n"
            "`/sample 00:05:00 to 00:05:55 [link]`\n"
            "`/sample 00:05:00 30 [link]`"
        )

    task_id = f"sample_{message.id}"
    task_dir = os.path.join(config.DOWNLOAD_DIR, task_id)
    os.makedirs(task_dir, exist_ok=True)
    status_msg = await message.reply_text(f"⏳ **Preparing source for {duration}s clip from `{start_time}`...**")

    try:
        downloaded_file = None

        if telegram_target:
            await status_msg.edit_text("📥 **Downloading source video from Telegram servers...**")
            tracker = ProgressTracker(status_msg, "Telegram Media Download")
            media_obj = telegram_target.video or telegram_target.document
            raw_name = getattr(media_obj, "file_name", None) or f"video_{telegram_target.id}.mp4"
            dest_path = os.path.join(task_dir, raw_name)
            
            downloaded_file = await telegram_target.download(
                file_name=dest_path,
                progress=tracker.progress_callback
            )
        elif uri:
            downloaded_file = await download_content(uri, task_dir, status_msg)

        if not downloaded_file or not os.path.exists(downloaded_file):
            return await status_msg.edit_text("❌ Failed to obtain source video.")

        await status_msg.edit_text(f"✂️ **Slicing clip:** `{start_time}` (+`{duration}s`)...")
        
        sample_output = os.path.join(task_dir, f"sample_{duration}s.mp4")
        clip = await extract_sample_clip(downloaded_file, start_time, duration, sample_output)
        
        if not clip or not os.path.exists(clip):
            return await status_msg.edit_text("❌ Failed to crop sample. Ensure timestamp is within video duration.")

        sample_thumb = os.path.join(task_dir, "sample_thumb.jpg")
        await generate_thumbnail(clip, sample_thumb, timestamp_sec=2)

        tracker = ProgressTracker(status_msg, "Uploading Sample Clip")
        await bot.send_video(
            chat_id=message.chat.id,
            video=clip,
            caption=(
                f"✂️ **Sample Video ({duration}s)**\n\n"
                f"⏱️ **Timestamp:** `{start_time}`\n"
                f"⏳ **Duration:** `{duration}s`\n"
                f"🎬 **Source File:** `{os.path.basename(downloaded_file)}`"
            ),
            thumb=sample_thumb if os.path.exists(sample_thumb) else None,
            supports_streaming=True,
            progress=tracker.progress_callback
        )
        await status_msg.delete()

    except Exception as e:
        logger.error(f"Sample slicing error: {e}")
        await status_msg.edit_text(f"❌ **Error:** `{str(e)}`")
    finally:
        shutil.rmtree(task_dir, ignore_errors=True)

# --- 6. Incoming Media & Link Intake ---
@bot.on_message((filters.text | filters.document | filters.video) & filters.private)
async def intake_handler(_, message: Message):
    if message.text and message.text.startswith("/"):
        return

    user_id = message.from_user.id
    username = message.from_user.username
    if not await database.is_user_authorized(user_id, username):
        return await message.reply_text(
            f"⛔ **Access Denied.**\nYour ID: `{user_id}`\nAsk owner (`{config.OWNER_ID}`) to `/allow {user_id}`"
        )

    uri = None
    is_tg_file = False

    if message.text:
        text = message.text.strip()
        if text.startswith("http://") or text.startswith("https://") or text.startswith("magnet:?"):
            uri = text
    elif message.document:
        if message.document.file_name and message.document.file_name.lower().endswith(".torrent"):
            status = await message.reply_text("📥 Receiving .torrent metadata...")
            saved_torrent = await message.download(file_name=os.path.join(config.DOWNLOAD_DIR, f"{message.id}.torrent"))
            uri = saved_torrent
            await status.delete()
        else:
            is_tg_file = True
    elif message.video:
        is_tg_file = True

    if not uri and not is_tg_file:
        return

    task_id = str(message.id)
    ACTIVE_TASKS[task_id] = {
        "uri": uri,
        "is_tg_file": is_tg_file,
        "message": message,
        "user_id": user_id
    }

    # Attractive, streamlined action keyboard
    markup = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎬 Video (Fast Stream)", callback_data=f"up_vid:{task_id}"),
            InlineKeyboardButton("📁 Raw Document", callback_data=f"up_doc:{task_id}")
        ],
        [
            InlineKeyboardButton("✂️ 30s Sample", callback_data=f"sample_30:{task_id}"),
            InlineKeyboardButton("⏱️ 60s Sample", callback_data=f"sample_60:{task_id}")
        ],
        [
            InlineKeyboardButton("❌ Cancel Task", callback_data=f"cancel:{task_id}")
        ]
    ])

    await message.reply_text("⚡ **Source Accepted!** Choose upload mode:", reply_markup=markup)

# --- 7. Interactive Callback Engine ---
@bot.on_callback_query(filters.regex("^(up_vid|up_doc|sample_30|sample_60|cancel):"))
async def process_task_callback(_, query: CallbackQuery):
    action, task_id = query.data.split(":")
    task = ACTIVE_TASKS.get(task_id)

    if action == "cancel":
        ACTIVE_TASKS.pop(task_id, None)
        await query.message.edit_text("❌ **Task Cancelled.**")
        return await query.answer("Cancelled.")

    if not task:
        return await query.answer("This task expired.", show_alert=True)
    if query.from_user.id != task["user_id"]:
        return await query.answer("You didn't initiate this task.", show_alert=True)

    await query.message.edit_reply_markup(reply_markup=None)
    status_msg = await query.message.reply_text("🚀 **Initializing high-speed process...**")
    
    task_dir = os.path.join(config.DOWNLOAD_DIR, f"task_{task_id}")
    os.makedirs(task_dir, exist_ok=True)

    try:
        downloaded_file = None

        if task.get("is_tg_file"):
            orig_msg = task["message"]
            media = orig_msg.video or orig_msg.document
            file_name = getattr(media, "file_name", None) or f"video_{orig_msg.id}.mp4"
            dest_path = os.path.join(task_dir, file_name)
            tracker = ProgressTracker(status_msg, "Telegram Media Download")
            downloaded_file = await orig_msg.download(
                file_name=dest_path,
                progress=tracker.progress_callback
            )
        else:
            downloaded_file = await download_content(task["uri"], task_dir, status_msg)

        if not downloaded_file or not os.path.exists(downloaded_file):
            return await status_msg.edit_text("❌ Download failed or empty file received.")

        file_size = os.path.getsize(downloaded_file)
        file_size_human = human_readable_size(file_size)

        if file_size > (2000 * 1024 * 1024):
            return await status_msg.edit_text(f"❌ File size (`{file_size_human}`) exceeds Telegram's 2 GB limit.")

        if action in ("sample_30", "sample_60"):
            sample_duration = 30 if action == "sample_30" else 60
            await status_msg.edit_text(f"✂️ **Extracting {sample_duration}s preview clip with ffmpeg...**")
            meta = await get_video_metadata(downloaded_file)
            start_timestamp = 60 if meta["duration"] > (sample_duration + 60) else 5
            sample_output = os.path.join(task_dir, f"sample_{sample_duration}s.mp4")
            
            clip = await extract_sample_clip(downloaded_file, start_timestamp, sample_duration, sample_output)
            if not clip:
                return await status_msg.edit_text("❌ Failed to slice video clip.")

            sample_thumb = os.path.join(task_dir, "sample_thumb.jpg")
            await generate_thumbnail(clip, sample_thumb, timestamp_sec=2)

            tracker = ProgressTracker(status_msg, "Uploading Sample Clip")
            await bot.send_video(
                chat_id=query.message.chat.id,
                video=clip,
                caption=f"✂️ **Sample ({sample_duration}s)**\nSource: `{os.path.basename(downloaded_file)}`",
                thumb=sample_thumb if os.path.exists(sample_thumb) else None,
                supports_streaming=True,
                progress=tracker.progress_callback
            )
            await status_msg.delete()
            return

        if action == "up_vid":
            await status_msg.edit_text("🎞️ **Generating video thumbnail & parsing parameters...**")
            meta = await get_video_metadata(downloaded_file)
            thumb_path = os.path.join(task_dir, "thumb.jpg")
            await generate_thumbnail(downloaded_file, thumb_path, timestamp_sec=15)

            tracker = ProgressTracker(status_msg, "Uploading Streamable Video")
            await bot.send_video(
                chat_id=query.message.chat.id,
                video=downloaded_file,
                caption=f"🎬 `{os.path.basename(downloaded_file)}`\n📦 **Size:** `{file_size_human}`",
                duration=meta["duration"],
                width=meta["width"],
                height=meta["height"],
                thumb=thumb_path if os.path.exists(thumb_path) else None,
                supports_streaming=True,
                progress=tracker.progress_callback
            )
            await status_msg.delete()
            return

        if action == "up_doc":
            thumb_path = os.path.join(task_dir, "thumb.jpg")
            await generate_thumbnail(downloaded_file, thumb_path, timestamp_sec=10)

            tracker = ProgressTracker(status_msg, "Uploading Document")
            await bot.send_document(
                chat_id=query.message.chat.id,
                document=downloaded_file,
                caption=f"📁 `{os.path.basename(downloaded_file)}`\n📦 **Size:** `{file_size_human}`",
                thumb=thumb_path if os.path.exists(thumb_path) else None,
                progress=tracker.progress_callback
            )
            await status_msg.delete()
            return

    except FloodWait as f:
        await asyncio.sleep(f.value)
    except MessageNotModified:
        pass
    except Exception as e:
        logger.error(f"Task processing error: {e}")
        await status_msg.edit_text(f"❌ **Error:** `{str(e)}`")
    finally:
        shutil.rmtree(task_dir, ignore_errors=True)
        ACTIVE_TASKS.pop(task_id, None)

# --- 8. Runner ---
async def start_all():
    asyncio.create_task(disk_cleanup_worker())
    logger.info("Starting Pyrogram bot...")
    await bot.start()
    logger.info("Pyrogram listener initialized.")
    await idle()
    await bot.stop()

if __name__ == "__main__":
    bot.run(start_all())
