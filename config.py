import os

# Telegram API Credentials
API_ID = int(os.getenv("API_ID", "27758016"))
API_HASH = os.getenv("API_HASH", "8d34cfffe27ab461eabbf0091b1a27df")
BOT_TOKEN = os.getenv("BOT_TOKEN", "8912039309:AAGHvO-9QtmhNzkpUOQjK-Ucxu8Y6qp_FwI")

# Master Owner ID
OWNER_ID = int(os.getenv("OWNER_ID", "8738369449"))

# Railway Network Configuration
PORT = int(os.getenv("PORT", "8080"))
RAILWAY_PUBLIC_DOMAIN = os.getenv("RAILWAY_PUBLIC_DOMAIN", "telegram-uploader-bot-production-1845.up.railway.app")

# Download Storage
DOWNLOAD_DIR = os.path.join(os.getcwd(), "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
