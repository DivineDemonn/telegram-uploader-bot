import os
import time
import shutil
import asyncio
import logging
from aiohttp import web, ClientSession
from pyrogram import Client, filters
from pyrogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery
)
from pyrogram.errors import FloodWait

import config
import database
from helpers.aria_downloader import download_content
from helpers.media_utils import get_video_metadata, generate_thumbnail, extract_sample_clip
from helpers.progress import ProgressTracker, human_readable_size

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

ACTIVE_TASKS = {}

# --- 1. Health Server ---
async def ping_handler(request):
    return web.Response(text="Bot is running 24/7 on Railway!", status=200)

async def start_health_server():
    app = web.Application()
    app.router.add_get("/", ping_handler)
    app.router.add_get("/health", ping_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", config.PORT)
    await site.start()
    logger.info(f"Health server listening on port {config.PORT}")

# --- 2. Keep-Alive Worker ---
async def keep_alive_worker():
    await asyncio.sleep(30)
    while True:
        url = os.getenv("RAILWAY_PUBLIC_DOMAIN")
        if url:
            target = f"https://{url}/health" if not url.startswith("http") else f"{url}/health"
            try:
                async with ClientSession() as session:
                    async with session.get(target, timeout=10) as resp:
                        logger.info(f"Keep-alive ping sent to {target} | Status: {resp.status}")
            except Exception as e:
                logger.warning(f"Keep-alive ping error: {e}")
        await asyncio.sleep(300)

# --- 3. Stale Temp File Cleaner ---
async def stale_cleanup_worker():
    while True:
        await asyncio.sleep(1800)
        now = time.time()
        for root, dirs, files in os.walk(config.DOWNLOAD_DIR):
            for file in files:
                file_path = os.path.join(root, file)
                try:
                    if os.path.exists(file_path) and (now - os.path.getmtime(file_path) > 1800):
                        os.remove(file_path)
                except Exception as e:
                    logger.error(f"Cleanup error on {file_path}: {e}")

# --- 4. Pyrogram Bot Client ---
bot = Client(
    "railway_uploader_bot",
    api_id=config.API_ID,
    api_hash=config.API_HASH,
    bot_token=config.BOT_TOKEN,
    max_concurrent_transmissions=4
)

# --- 5. Diagnostic Handlers ---
@bot.on_message(filters.command("start"))
async def start_command(_, message: Message):
    user_id = message.from_user.id
    logger.info(f"📩 /start received from User ID: {user_id}")
    
    # Check authorization with a 3-second timeout fallback
    try:
        authorized = await asyncio.wait_for(database.is_user_authorized(user_id), timeout=3.0)
    except Exception as e:
        logger.error(f"Database check timed out or failed: {e}")
        authorized = (user_id == config.OWNER_ID)

    if not authorized:
        return await message.reply_text(
            f"⛔ **Access Denied.**\n"
            f"Your Telegram ID: `{user_id}`\n\n"
            f"Ask the bot owner (`{config.OWNER_ID}`) to authorize you with:\n"
            f"`/auth {user_id}`"
        )
    
    await message.reply_text(
        f"⚡ **Uploader Bot Online!**\n\n"
        f"👤 **Your ID:** `{user_id}`\n"
        f"👑 **Owner ID:** `{config.OWNER_ID}`\n\n"
        "Send me any of the following:\n"
        "• Direct download URLs (`.mp4`, `.mkv`, etc.)\n"
        "• Magnet links (`magnet:?xt=...`)\n"
        "• `.torrent` files"
    )

@bot.on_message(filters.command("users"))
async def users_command(_, message: Message):
    user_id = message.from_user.id
    logger.info(f"📩 /users requested by {user_id}")
    if user_id != config.OWNER_ID:
        return await message.reply_text(f"⛔ Only the owner (`{config.OWNER_ID}`) can view authorized users.")
    
    try:
        users = await database.get_all_users()
        reply = f"👑 **Owner ID:** `{config.OWNER_ID}`\n\n**Authorized Users:**\n"
        if not users:
            reply += "• _No extra authorized users._"
        else:
            reply += "\n".join([f"• `{uid}`" for uid in users])
        await message.reply_text(reply)
    except Exception as e:
        await message.reply_text(f"❌ Database error: {e}")

@bot.on_message(filters.command("auth"))
async def auth_command(_, message: Message):
    if message.from_user.id != config.OWNER_ID:
        return await message.reply_text("⛔ Owner only command.")
    if len(message.command) < 2:
        return await message.reply_text("Usage: `/auth <user_id>`")
    try:
        target_id = int(message.command[1])
        if await database.authorize_user(target_id):
            await message.reply_text(f"✅ User `{target_id}` authorized.")
        else:
            await message.reply_text("⚠️ User is already authorized.")
    except Exception as e:
        await message.reply_text(f"Error: {e}")

# --- 6. Link Receiver ---
@bot.on_message((filters.text | filters.document) & filters.private)
async def incoming_handler(_, message: Message):
    user_id = message.from_user.id
    logger.info(f"📩 Incoming media/link from User ID: {user_id}")

    try:
        authorized = await asyncio.wait_for(database.is_user_authorized(user_id), timeout=3.0)
    except Exception:
        authorized = (user_id == config.OWNER_ID)

    if not authorized:
        return await message.reply_text(f"⛔ You are not authorized. Your ID is `{user_id}`.")

    uri = None
    if message.text:
        text = message.text.strip()
        if text.startswith("http://") or text.startswith("https://") or text.startswith("magnet:?"):
            uri = text
    elif message.document and message.document.file_name.endswith(".torrent"):
        status = await message.reply_text("📥 Receiving .torrent metadata...")
        saved_torrent = await message.download(file_name=os.path.join(config.DOWNLOAD_DIR, f"{message.id}.torrent"))
        uri = saved_torrent
        await status.delete()

    if not uri:
        return

    task_id = str(message.id)
    ACTIVE_TASKS[task_id] = {"uri": uri, "user_id": user_id}

    markup = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎬 Video (Fast Stream)", callback_data=f"up_vid:{task_id}"),
            InlineKeyboardButton("📁 Raw Document", callback_data=f"up_doc:{task_id}")
        ],
        [
            InlineKeyboardButton("✂️ 30s Sample Clip", callback_data=f"sample_30:{task_id}"),
            InlineKeyboardButton("⏱️ 60s Sample Clip", callback_data=f"sample_60:{task_id}")
        ]
    ])

    await message.reply_text("⚡ **Source Accepted!** Select upload mode:", reply_markup=markup)

# --- 7. Task Callbacks ---
@bot.on_callback_query(filters.regex("^(up_vid|up_doc|sample_30|sample_60):"))
async def process_task_callback(_, query: CallbackQuery):
    action, task_id = query.data.split(":")
    task = ACTIVE_TASKS.get(task_id)

    if not task:
        return await query.answer("This task has expired or was cleared.", show_alert=True)
    if query.from_user.id != task["user_id"]:
        return await query.answer("You are not the initiator of this task.", show_alert=True)

    await query.message.edit_reply_markup(reply_markup=None)
    status_msg = await query.message.reply_text("🚀 **Initializing Railway gigabit network download...**")
    
    task_dir = os.path.join(config.DOWNLOAD_DIR, f"task_{task_id}")
    os.makedirs(task_dir, exist_ok=True)

    try:
        downloaded_file = await download_content(task["uri"], task_dir, status_msg)
        if not downloaded_file or not os.path.exists(downloaded_file):
            return await status_msg.edit_text("❌ Download failed or empty file received.")

        file_size = os.path.getsize(downloaded_file)
        file_size_human = human_readable_size(file_size)

        if file_size > (2000 * 1024 * 1024):
            return await status_msg.edit_text(f"❌ File size (`{file_size_human}`) exceeds Telegram's 2 GB limit.")

        if action in ("sample_30", "sample_60"):
            sample_duration = 30 if action == "sample_30" else 60
            await status_msg.edit_text(f"✂️ **Extracting {sample_duration}s sample clip with ffmpeg...**")
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
            await status_msg.edit_text("🎞️ **Generating video thumbnail & parsing stream parameters...**")
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
    except Exception as e:
        logger.error(f"Task processing error: {e}")
        await status_msg.edit_text(f"❌ **Operational error:** `{str(e)}`")
    finally:
        shutil.rmtree(task_dir, ignore_errors=True)
        ACTIVE_TASKS.pop(task_id, None)

# --- 8. Main Loop ---
async def main():
    await start_health_server()
    asyncio.create_task(keep_alive_worker())
    asyncio.create_task(stale_cleanup_worker())
    
    while True:
        try:
            logger.info("Starting Telegram Bot client...")
            await bot.start()
            logger.info("Telegram Bot is running 24/7.")
            while bot.is_connected:
                await asyncio.sleep(5)
        except Exception as e:
            logger.error(f"Bot connection drop: {e}. Reconnecting in 5 seconds...")
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())
