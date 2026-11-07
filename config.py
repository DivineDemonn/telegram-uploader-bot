import os

# Telegram API credentials
API_ID = int(os.getenv("API_ID", "27758016"))
API_HASH = os.getenv("API_HASH", "8d34cfffe27ab461eabbf0091b1a27df")
BOT_TOKEN = os.getenv("BOT_TOKEN", "8891356051:AAHm-3K3vVXb0laIR20i-cPKQUhzEVwnTvU")

# Owner configuration
OWNER_ID = int(os.getenv("OWNER_ID", "8738369449"))

# MongoDB configuration
MONGO_URL = os.getenv("MONGO_URL", "mongodb+srv://marwin2002:marwin2002@cluster0.uavio6c.mongodb.net/")
DB_NAME = "uploader_bot"

# Port for Hugging Face health check
PORT = int(os.getenv("PORT", "7860"))

# Temp download storage
DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
