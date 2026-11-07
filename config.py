import os
import sys

def get_env(key: str, default=None, required: bool = False):
    """Retrieve an environment variable or raise an error if required."""
    val = os.getenv(key, default)
    if required and (val is None or str(val).strip() == ""):
        print(f"❌ CRITICAL CONFIG ERROR: Missing required environment variable '{key}' in Railway!")
        sys.exit(1)
    return val

# Telegram API Credentials
API_ID = int(get_env("API_ID", required=True))
API_HASH = str(get_env("API_HASH", required=True))
BOT_TOKEN = str(get_env("BOT_TOKEN", required=True))

# Owner Identification
OWNER_ID = int(get_env("OWNER_ID", required=True))

# Database Settings
MONGO_URL = str(get_env("MONGO_URL", required=True))
DB_NAME = str(get_env("DB_NAME", default="railway_uploader_bot"))

# Railway Networking & Health Check (Railway injects PORT automatically)
PORT = int(get_env("PORT", default=8080))
RAILWAY_PUBLIC_DOMAIN = get_env("RAILWAY_PUBLIC_DOMAIN", default="")

# Ephemeral File Buffer Directory
DOWNLOAD_DIR = os.path.join(os.getcwd(), "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
