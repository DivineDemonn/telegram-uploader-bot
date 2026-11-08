import time
import math

def human_readable_size(size_bytes: int) -> str:
    if not size_bytes or size_bytes <= 0:
        return "0 B"
    units = ("B", "KB", "MB", "GB", "TB")
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return f"{s} {units[i]}"

def human_readable_time(seconds: int) -> str:
    if seconds <= 0:
        return "0s"
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h}h {m}m {s}s"
    if m > 0:
        return f"{m}m {s}s"
    return f"{s}s"

class ProgressTracker:
    def __init__(self, message, action_title: str):
        self.message = message
        self.action_title = action_title
        self.start_time = time.time()
        self.last_update_time = time.time()

    async def progress_callback(self, current: int, total: int):
        now = time.time()
        # Rate limit to updates every 3.5 seconds
        if (now - self.last_update_time) < 3.5 and current != total:
            return

        self.last_update_time = now
        elapsed = now - self.start_time
        speed = current / elapsed if elapsed > 0 else 0
        eta = round((total - current) / speed) if speed > 0 and total > current else 0
        percentage = (current / total) * 100 if total > 0 else 0

        # High-visibility filled/empty block bar
        blocks = int(percentage // 10)
        bar = "▰" * blocks + "▱" * (10 - blocks)

        ui_text = (
            f"⚡ **{self.action_title}**\n\n"
            f"[{bar}] `{percentage:.1f}%`\n"
            f"🚀 **Speed:** `{human_readable_size(speed)}/s`\n"
            f"📦 **Done:** `{human_readable_size(current)}` / `{human_readable_size(total)}`\n"
            f"⏱️ **ETA:** `{human_readable_time(eta)}`"
        )

        try:
            await self.message.edit_text(ui_text)
        except Exception:
            pass
