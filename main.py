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
from helpers.aria_downloader import download_file
from helpers.media_utils import get_video_metadata, generate_thumbnail, extract_sample_clip

# Global task state cache
PENDING_TASKS = {}

# --- 1. Hugging Face Spaces Port 7860 Web Server ---
async def health_check(request):
    return web.Response(text="Bot is running smoothly on Hugging Face Spaces!")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", config.PORT)
    await site.start()

# --- 2. Pyrogram Bot Instance ---
bot = Client(
    "leech_uploader_bot",
    api_id=config.API_ID,
    api_hash=config.API_HASH,
    bot_token=config.BOT_TOKEN
)

# --- 3. Authorization & Management Commands ---
@bot.on_message(filters.command("start"))
async def start_handler(_, message: Message):
    user_id = message.from_user.id
    if not await database.is_user_authorized(user_id):
        return await message.reply_text("⛔ **Access Denied.** You are not authorized to use this bot.")
    
    await message.reply_text(
        f"👋 **Welcome {message.from_user.first_name}!**\n\n"
        "Send me any of the following to download and upload to Telegram:\n"
        "• Direct download link (`.mp4`, `.mkv`, etc.)\n"
        "• Magnet URI (`magnet:?xt=...`)\n"
        "• `.torrent` file\n\n"
        "Options will appear allowing you to upload as **Video**, **Document**, or get a **Sample Clip**."
    )

@bot.on_message(filters.command("auth") & filters.user(config.OWNER_ID))
async def auth_user_handler(_, message: Message):
    if len(message.command) < 2:
        return await message.reply_text("Usage: `/auth <user_id>`")
    try:
        target_id = int(message.command[1])
        if await database.authorize_user(target_id):
            await message.reply_text(f"✅ User `{target_id}` is now authorized.")
        else:
            await message.reply_text("User is already authorized.")
    except ValueError:
        await message.reply_text("Invalid User ID.")

@bot.on_message(filters.command("unauth") & filters.user(config.OWNER_ID))
async def unauth_user_handler(_, message: Message):
    if len(message.command) < 2:
        return await message.reply_text("Usage: `/unauth <user_id>`")
    try:
        target_id = int(message.command[1])
        if await database.unauthorize_user(target_id):
            await message.reply_text(f"🚫 User `{target_id}` has been unauthorized.")
        else:
            await message.reply_text("User was not found in the authorized list.")
    except ValueError:
        await message.reply_text("Invalid User ID.")

@bot.on_message(filters.command("users") & filters.user(config.OWNER_ID))
async def list_users_handler(_, message: Message):
    users = await database.get_all_users()
    if not users:
        return await message.reply_text(f"👑 **Owner ID:** `{config.OWNER_ID}`\nNo extra authorized users.")
    text = f"👑 **Owner ID:** `{config.OWNER_ID}`\n\n**Authorized Users:**\n"
    text += "\n".join([f"• `{uid}`" for uid in users])
    await message.reply_text(text)

# --- 4. Link & Torrent Receiver ---
@bot.on_message((filters.text | filters.document) & filters.private)
async def incoming_task_handler(_, message: Message):
    user_id = message.from_user.id
    if not await database.is_user_authorized(user_id):
        return await message.reply_text("⛔ You are not authorized to use this bot.")

    uri = None
    if message.text:
        text = message.text.strip()
        if text.startswith("http://") or text.startswith("https://") or text.startswith("magnet:?"):
            uri = text
    elif message.document and message.document.file_name.endswith(".torrent"):
        status = await message.reply_text("📥 Saving .torrent file...")
        torrent_path = await message.download(file_name=os.path.join(config.DOWNLOAD_DIR, f"{message.id}.torrent"))
        uri = torrent_path
        await status.delete()

    if not uri:
        return

    # Store task details
    task_id = str(message.id)
    PENDING_TASKS[task_id] = {
        "uri": uri,
        "user_id": user_id
    }

    buttons = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📹 Upload as Video", callback_data=f"up_video:{task_id}"),
            InlineKeyboardButton("📁 Upload as File", callback_data=f"up_doc:{task_id}")
        ],
        [
            InlineKeyboardButton("✂️ 30s Sample Clip", callback_data=f"sample:{task_id}")
        ]
    ])

    await message.reply_text(
        "🔗 **Link / Torrent Detected!**\n\nChoose how you want to process this file:",
        reply_markup=buttons
    )

# --- 5. Action Callback Handler ---
@bot.on_callback_query(filters.regex("^(up_video|up_doc|sample):"))
async def handle_callback(_, query: CallbackQuery):
    action, task_id = query.data.split(":")
    task = PENDING_TASKS.get(task_id)

    if not task:
        return await query.answer("Task expired or not found.", show_alert=True)

    if query.from_user.id != task["user_id"]:
        return await query.answer("This is not your task.", show_alert=True)

    await query.message.edit_reply_markup(reply_markup=None)
    status_msg = await query.message.reply_text("⚡ **Initializing download via aria2c...**")

    # Unique directory for this task
    user_download_dir = os.path.join(config.DOWNLOAD_DIR, f"task_{task_id}")
    os.makedirs(user_download_dir, exist_ok=True)

    try:
        # Download
        await status_msg.edit_text("⏳ **Downloading content...** (This may take some time)")
        downloaded_file = await download_file(task["uri"], user_download_dir)

        if not downloaded_file or not os.path.exists(downloaded_file):
            return await status_msg.edit_text("❌ Download failed or file was empty.")

        file_size_mb = os.path.getsize(downloaded_file) / (1024 * 1024)
        if file_size_mb > 2000:
            return await status_msg.edit_text(f"❌ File size ({file_size_mb:.2f} MB) exceeds Telegram's 2000 MB (2 GB) limit.")

        # Handle Sample Generation
        if action == "sample":
            await status_msg.edit_text("✂️ **Generating 30s sample clip with ffmpeg...**")
            meta = await get_video_metadata(downloaded_file)
            start_sec = 60 if meta["duration"] > 120 else 5
            sample_path = os.path.join(user_download_dir, f"sample_{os.path.basename(downloaded_file)}.mp4")
            
            clip = await extract_sample_clip(downloaded_file, start_sec, 30, sample_path)
            if not clip:
                return await status_msg.edit_text("❌ Failed to extract sample clip.")
            
            await status_msg.edit_text("📤 **Uploading sample clip...**")
            thumb_path = os.path.join(user_download_dir, "sample_thumb.jpg")
            thumb = await generate_thumbnail(clip, thumb_path, timestamp_sec=2)
            
            await bot.send_video(
                chat_id=query.message.chat.id,
                video=clip,
                caption=f"✂️ **Sample Clip (30s)**\nOriginal File: `{os.path.basename(downloaded_file)}`",
                thumb=thumb,
                supports_streaming=True
            )
            await status_msg.delete()
            return

        # Handle Video Upload
        if action == "up_video":
            await status_msg.edit_text("📤 **Extracting metadata & uploading as video...**")
            meta = await get_video_metadata(downloaded_file)
            thumb_path = os.path.join(user_download_dir, "thumb.jpg")
            thumb = await generate_thumbnail(downloaded_file, thumb_path, timestamp_sec=10)

            await bot.send_video(
                chat_id=query.message.chat.id,
                video=downloaded_file,
                caption=f"🎬 `{os.path.basename(downloaded_file)}`\n📦 Size: `{file_size_mb:.2f} MB`",
                duration=meta["duration"],
                width=meta["width"],
                height=meta["height"],
                thumb=thumb,
                supports_streaming=True
            )
            await status_msg.delete()
            return

        # Handle Document Upload
        if action == "up_doc":
            await status_msg.edit_text("📤 **Uploading as document...**")
            thumb_path = os.path.join(user_download_dir, "thumb.jpg")
            thumb = await generate_thumbnail(downloaded_file, thumb_path, timestamp_sec=10)

            await bot.send_document(
                chat_id=query.message.chat.id,
                document=downloaded_file,
                caption=f"📁 `{os.path.basename(downloaded_file)}`\n📦 Size: `{file_size_mb:.2f} MB`",
                thumb=thumb
            )
            await status_msg.delete()
            return

    except Exception as e:
        await status_msg.edit_text(f"❌ **An error occurred:** `{str(e)}`")
    finally:
        # Clean up temporary storage
        shutil.rmtree(user_download_dir, ignore_errors=True)
        PENDING_TASKS.pop(task_id, None)

# --- 6. Main Entrypoint ---
async def main():
    await start_web_server()
    print("Web server listening on port 7860.")
    await bot.start()
    print("Bot is online and polling!")
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
