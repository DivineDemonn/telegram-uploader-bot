import logging
from motor.motor_asyncio import AsyncIOMotorClient
import config

logger = logging.getLogger(__name__)

# Fail-safe 5000ms connection timeout to eliminate hanging bugs
client = AsyncIOMotorClient(config.MONGO_URL, serverSelectionTimeoutMS=5000)
db = client[config.DB_NAME]
users_col = db["allowed_users"]

async def is_user_authorized(user_id: int, username: str = None) -> bool:
    """Checks if a user is the owner or explicitly whitelisted."""
    if user_id == config.OWNER_ID:
        return True
    try:
        query = {"$or": [{"user_id": user_id}]}
        if username:
            query["$or"].append({"username": username.lower().replace("@", "")})
        user = await users_col.find_one(query)
        return user is not None
    except Exception as e:
        logger.error(f"MongoDB authorization lookup error: {e}")
        # Default fallback to owner only if DB is unreachable
        return user_id == config.OWNER_ID

async def authorize_user(identifier: str) -> tuple[bool, str]:
    """Adds a User ID or @Username to the database whitelist."""
    try:
        clean = identifier.strip().replace("@", "")
        if clean.isdigit():
            user_id = int(clean)
            existing = await users_col.find_one({"user_id": user_id})
            if existing:
                return False, f"User ID `{user_id}` is already authorized."
            await users_col.insert_one({"user_id": user_id, "username": None})
            return True, f"User ID `{user_id}` successfully authorized."
        else:
            uname = clean.lower()
            existing = await users_col.find_one({"username": uname})
            if existing:
                return False, f"Username `@{uname}` is already authorized."
            await users_col.insert_one({"user_id": None, "username": uname})
            return True, f"Username `@{uname}` successfully authorized."
    except Exception as e:
        logger.error(f"MongoDB insert error: {e}")
        return False, f"Database error: {e}"

async def unauthorize_user(identifier: str) -> tuple[bool, str]:
    """Removes a User ID or @Username from the database."""
    try:
        clean = identifier.strip().replace("@", "")
        if clean.isdigit():
            res = await users_col.delete_one({"user_id": int(clean)})
        else:
            res = await users_col.delete_one({"username": clean.lower()})
        
        if res.deleted_count > 0:
            return True, f"Access revoked for `{identifier}`."
        return False, f"`{identifier}` was not found in authorized list."
    except Exception as e:
        return False, f"Database error: {e}"

async def get_all_authorized_users() -> list:
    """Returns all whitelisted records."""
    try:
        records = []
        async for doc in users_col.find():
            if doc.get("user_id"):
                records.append(f"`{doc['user_id']}`")
            elif doc.get("username"):
                records.append(f"@{doc['username']}")
        return records
    except Exception as e:
        logger.error(f"Error fetching authorized list: {e}")
        return []
