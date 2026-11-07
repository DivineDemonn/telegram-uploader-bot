import os

# Telegram API Credentials
API_ID = int(os.getenv("API_ID", "27758016"))
API_HASH = os.getenv("API_HASH", "8d34cfffe27ab461eabbf0091b1a27df")
BOT_TOKEN = os.getenv("BOT_TOKEN", "8891356051:AAHm-3K3vVXb0laIR20i-cPKQUhzEVwnTvU")

# Owner Configuration
OWNER_ID = int(os.getenv("OWNER_ID", "8738369449"))

# MongoDB Configuration
MONGO_URL = os.getenv("MONGO_URL", "mongodb+srv://marwin2002:marwin2002@cluster0.uavio6c.mongodb.net/")
DB_NAME = "railway_uploader_bot"

# Railway Port (Web Service Health Check)
PORT = int(os.getenv("PORT", "8080"))

# File storage buffers
DOWNLOAD_DIR = os.path.join(os.getcwd(), "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
