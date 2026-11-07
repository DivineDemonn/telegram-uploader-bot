import math
import time

def human_readable_size(size_bytes: int) -> str:
    if size_bytes == 0:
        return "0 B"
    size_name = ("B", "KB", "MB", "GB", "TB")
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return f"{s} {size_name[i]}"

class ProgressTracker:
    def __init__(self, message, action_title: str):
        self.message = message
        self.action_title = action_title
        self.last_update_time = time.time()

    async def progress_callback(self, current: int, total: int):
        now = time.time()
        # Update Telegram UI only every 4 seconds to eliminate rate limits
        if (now - self.last_update_time) < 4.0 and current != total:
            return

        self.last_update_time = now
        percentage = (current / total) * 100 if total > 0 else 0
        filled_blocks = int(percentage // 10)
        bar = "▰" * filled_blocks + "▱" * (10 - filled_blocks)
        
        text = (
            f"⚡ **{self.action_title}**\n\n"
            f"[{bar}] `{percentage:.1f}%`\n"
            f"**Processed:** `{human_readable_size(current)}` of `{human_readable_size(total)}`"
        )
        try:
            await self.message.edit_text(text)
        except Exception:
            pass
