from motor.motor_asyncio import AsyncIOMotorClient
import config

client = AsyncIOMotorClient(config.MONGO_URL)
db = client[config.DB_NAME]
users_col = db["allowed_users"]

async def is_user_authorized(user_id: int) -> bool:
    """Check if a user is the owner or in the authorized list."""
    if user_id == config.OWNER_ID:
        return True
    user = await users_col.find_one({"user_id": user_id})
    return user is not None

async def authorize_user(user_id: int) -> bool:
    """Authorize a new user."""
    if await users_col.find_one({"user_id": user_id}):
        return False
    await users_col.insert_one({"user_id": user_id})
    return True

async def unauthorize_user(user_id: int) -> bool:
    """Revoke user access."""
    result = await users_col.delete_one({"user_id": user_id})
    return result.deleted_count > 0

async def get_all_users() -> list:
    """Retrieve all authorized user IDs."""
    cursor = users_col.find({}, {"_id": 0, "user_id": 1})
    return [doc["user_id"] async for doc in cursor]
  
