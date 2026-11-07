import os
import shutil
import asyncio
from aiohttp import web
from pyrogram import Client, filters
from pyrogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery
)

import config
import database
from helpers.aria_downloader import download_content
from helpers.media_utils import get_video_metadata, generate_thumbnail, extract_sample_clip
from helpers.progress import ProgressTracker, human_readable_size

ACTIVE_TASKS = {}

# --- 1. Railway Container Health Server ---
async def ping_handler(request):
    return web.Response(text="Railway Uploader Bot Active & Healthy.")

async def start_health_server():
    app = web.Application()
    app.router.add_get("/", ping_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", config.PORT)
    await site.start()
    print(f"Health check running on port {config.PORT}")

# --- 2. Pyrogram Bot Client ---
bot = Client(
    "railway_uploader_bot",
    api_id=config.API_ID,
    api_hash=config.API_HASH,
    bot_token=config.BOT_TOKEN,
    max_concurrent_transmissions=4
)

# --- 3. Whitelist & Management Commands ---
@bot.on_message(filters.command("start"))
async def start_command(_, message: Message):
    user_id = message.from_user.id
    if not await database.is_user_authorized(user_id):
        return await message.reply_text("⛔ **Access Denied.** You are not authorized to use this bot.")
    
    await message.reply_text(
        f"⚡ **Welcome {message.from_user.first_name}!**\n\n"
        "**Send me any of the following to download and upload:**\n"
        "• Direct File URLs (`.mkv`, `.mp4`, zip files, tokenized CDN links)\n"
        "• Magnet links (`magnet:?xt=...`)\n"
        "• `.torrent` document files\n\n"
        "You can upload as **Streamable Video**, **Raw Document**, or generate a **Sample Video Clip**."
    )

@bot.on_message(filters.command("auth") & filters.user(config.OWNER_ID))
async def auth_command(_, message: Message):
    if len(message.command) < 2:
        return await message.reply_text("Usage: `/auth <user_id>`")
    try:
        target_id = int(message.command[1])
        if await database.authorize_user(target_id):
            await message.reply_text(f"✅ User `{target_id}` added to authorized list.")
        else:
            await message.reply_text("⚠️ User is already authorized.")
    except ValueError:
        await message.reply_text("Invalid User ID format.")

@bot.on_message(filters.command("unauth") & filters.user(config.OWNER_ID))
async def unauth_command(_, message: Message):
    if len(message.command) < 2:
        return await message.reply_text("Usage: `/unauth <user_id>`")
    try:
        target_id = int(message.command[1])
        if await database.unauthorize_user(target_id):
            await message.reply_text(f"🚫 User `{target_id}` removed from authorized list.")
        else:
            await message.reply_text("User was not found in authorized list.")
    except ValueError:
        await message.reply_text("Invalid User ID format.")

@bot.on_message(filters.command("users") & filters.user(config.OWNER_ID))
async def users_command(_, message: Message):
    users = await database.get_all_users()
    reply = f"👑 **Owner ID:** `{config.OWNER_ID}`\n\n**Authorized Users:**\n"
    if not users:
        reply += "• _No additional users authorized._"
    else:
        reply += "\n".join([f"• `{uid}`" for uid in users])
    await message.reply_text(reply)

# --- 4. Task Reception ---
@bot.on_message((filters.text | filters.document) & filters.private)
async def incoming_handler(_, message: Message):
    user_id = message.from_user.id
    if not await database.is_user_authorized(user_id):
        return await message.reply_text("⛔ You are not authorized to use this bot.")

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
    ACTIVE_TASKS[task_id] = {
        "uri": uri,
        "user_id": user_id
    }

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

    await message.reply_text(
        "⚡ **Source Link / Torrent Accepted!**\n\nSelect upload mode:",
        reply_markup=markup
    )

# --- 5. Interactive Action Execution ---
@bot.on_callback_query(filters.regex("^(up_vid|up_doc|sample_30|sample_60):"))
async def process_task_callback(_, query: CallbackQuery):
    action, task_id = query.data.split(":")
    task = ACTIVE_TASKS.get(task_id)

    if not task:
        return await query.answer("This task has expired or was already cleared.", show_alert=True)
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

        # Handle Sample Extraction
        if action in ("sample_30", "sample_60"):
            sample_duration = 30 if action == "sample_30" else 60
            await status_msg.edit_text(f"✂️ **Extracting {sample_duration}s sample clip with ffmpeg...**")
            meta = await get_video_metadata(downloaded_file)
            
            # Start 60 seconds into the video if long enough, else start at 5s
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

        # Handle Video Upload
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

        # Handle Document Upload
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

    except Exception as e:
        await status_msg.edit_text(f"❌ **Operational error:** `{str(e)}`")
    finally:
        shutil.rmtree(task_dir, ignore_errors=True)
        ACTIVE_TASKS.pop(task_id, None)

# --- 6. Main Runner ---
async def main():
    await start_health_server()
    await bot.start()
    print("Telegram Leech Bot running with Railway network optimizations.")
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
