import os

def get_env(key: str, default=None):
    return os.getenv(key, default)

# Telegram API Credentials
API_ID = int(get_env("API_ID", "27758016"))
API_HASH = str(get_env("API_HASH", "8d34cfffe27ab461eabbf0091b1a27df"))
BOT_TOKEN = str(get_env("BOT_TOKEN", "8912039309:AAGHvO-9QtmhNzkpUOQjK-Ucxu8Y6qp_FwI"))

# Master Owner Identification
OWNER_ID = int(get_env("OWNER_ID", "8738369449"))

# MongoDB Configuration
MONGO_URL = str(get_env("MONGO_URL", "mongodb+srv://marwin2002:marwin2002@cluster0.uavio6c.mongodb.net/"))
DB_NAME = str(get_env("DB_NAME", "telegram_uploader_bot"))

# Storage paths
DOWNLOAD_DIR = os.path.join(os.getcwd(), "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
