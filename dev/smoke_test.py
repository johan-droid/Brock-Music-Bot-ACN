import asyncio
import os
import sys

# Ensure repository root is on sys.path so `bot` package can be imported
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from bot.utils.formatters import format_track_info
from bot.utils.title_detector import get_source_weights_for_query
from bot.utils.cache import cache, init_redis


def _configure_console_encoding() -> None:
    """Keep smoke output readable on Windows shells with legacy code pages."""
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="backslashreplace")
            except Exception:
                pass


async def main():
    # Init cache (uses SQLite fallback when Redis not configured)
    await init_redis()

    print("--- format_track_info output ---")
    print(format_track_info("Test Song", 215, position=12, source="telegram"))

    print("\n--- source weights (Indian example) ---")
    print(get_source_weights_for_query("Arijit Singh - Tum Hi Ho"))

    print("\n--- cache incr/expire test ---")
    key = "dev:smoke:test:rl"
    val = await cache.incr(key)
    print("incr ->", val)
    ok = await cache.expire(key, 5)
    print("expire set ->", ok)
    # cleanup
    await cache.delete(key)

if __name__ == "__main__":
    _configure_console_encoding()
    asyncio.run(main())
