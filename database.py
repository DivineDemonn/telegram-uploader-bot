import json
import os
import config

DB_FILE = "authorized_users.json"

def _load_users() -> list:
    if not os.path.exists(DB_FILE):
        return [config.OWNER_ID]
    try:
        with open(DB_FILE, "r") as f:
            users = json.load(f)
            if config.OWNER_ID not in users:
                users.append(config.OWNER_ID)
            return users
    except Exception:
        return [config.OWNER_ID]

def _save_users(users: list):
    try:
        with open(DB_FILE, "w") as f:
            json.dump(users, f, indent=2)
    except Exception as e:
        print(f"Error saving users: {e}")

async def is_user_authorized(user_id: int) -> bool:
    if user_id == config.OWNER_ID:
        return True
    return user_id in _load_users()

async def authorize_user(user_id: int) -> bool:
    users = _load_users()
    if user_id in users:
        return False
    users.append(user_id)
    _save_users(users)
    return True

async def unauthorize_user(user_id: int) -> bool:
    users = _load_users()
    if user_id in users:
        users.remove(user_id)
        _save_users(users)
        return True
    return False

async def get_all_users() -> list:
    return _load_users()
