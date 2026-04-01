"""
Music Bot - Telegram Voice Chat Music Bot
A Python-based bot for streaming high-quality audio into Telegram group voice calls.
"""

import asyncio
import logging
import pyrogram.errors

# Monkey-patch for py-tgcalls compatibility with newer pyrogram versions
if not hasattr(pyrogram.errors, "GroupcallForbidden"):
    # Reference: https://github.com/pytgcalls/pytgcalls/issues
    # Newer pyrogram versions renamed or removed GroupcallForbidden. 
    # Usually it's mapped to Forbidden or BroadcastForbidden in newer versions.
    pyrogram.errors.GroupcallForbidden = getattr(pyrogram.errors, "BroadcastForbidden", pyrogram.errors.Forbidden)

from bot.core.bot import init_bot, start_health_server
from bot.core.userbot import init_userbots
from bot.core.call import init_calls
from bot.core.queue import init_queue_manager
from bot.utils.database import init_database
from bot.utils.cache import init_redis
from bot.utils.logger import setup_logging
from bot.utils.scheduler import start_scheduler
from bot.core.music_backend import music_backend
from config import config


def _is_auth_key_duplicated(exc: Exception) -> bool:
    """Return True if exception chain indicates Telegram AUTH_KEY_DUPLICATED."""
    seen = set()
    current: Exception | None = exc

    while current and id(current) not in seen:
        seen.add(id(current))

        if isinstance(current, pyrogram.errors.AuthKeyDuplicated):
            return True

        msg = str(current).upper()
        if "AUTH_KEY_DUPLICATED" in msg or "AUTH KEY DUPLICATED" in msg:
            return True

        current = current.__cause__ or current.__context__

    return False


async def main():
    """Main entry point - initialize all components."""
    # Setup logging
    setup_logging()
    logger = logging.getLogger(__name__)
    logger.info("Starting Music Bot...")

    # Start health server first so platform health checks pass during boot.
    await start_health_server()
    
    try:
        # Initialize database connections
        await init_database()
        logger.info("Database connected")
        
        await init_redis()
        logger.info("Redis connected")
        
        # Initialize queue manager
        await init_queue_manager()
        logger.info("Queue manager initialized")
        
        # Initialize music backend (aiohttp session)
        await music_backend.init()
        logger.info("Music backend initialized")
        
        # Initialize userbots first (needed for calls)
        async def init_userbots_with_autoretry():
            from config import Config, config as global_config

            while True:
                try:
                    userbots = await init_userbots()
                    logger.info(f"Initialized {len(userbots)} userbot(s)")
                    return userbots
                except Exception as exc:
                    missing_auth = "AT LEAST ONE USERBOT AUTH IS REQUIRED" in str(exc).upper()
                    duplicated = _is_auth_key_duplicated(exc)

                    if missing_auth or duplicated:
                        if missing_auth:
                            logger.warning(
                                "No userbot auth configured yet. Re-checking every 30 seconds..."
                            )
                            retry_seconds = 30
                        else:
                            logger.warning(
                                "Auth key duplicated. Re-checking every 60 seconds..."
                            )
                            retry_seconds = 60

                        await asyncio.sleep(retry_seconds)

                        try:
                            revised = Config()
                            global_config.__dict__.update(revised.__dict__)
                            logger.info("Config reloaded from environment for retry.")
                        except Exception as e:
                            logger.warning("Failed to reload config: %s", e)
                        continue

                    raise

        userbots = await init_userbots_with_autoretry()

        if config.TELEGRAM_ENABLED:
            # Initialize py-tgcalls
            await init_calls(userbots)
            logger.info("Call manager initialized")

            # Wire stream-end → queue auto-advance + NP card cleanup
            from bot.core.call import call_manager
            from bot.plugins.play import on_track_end
            call_manager.on_stream_end_handlers.append(on_track_end)
            logger.info("Stream-end handler registered")

            # Start cleanup scheduler
            start_scheduler()
            logger.info("Cleanup scheduler started")

            # Initialize bot client (this will block)
            bot = await init_bot()
            logger.info("Bot started successfully")
        else:
            logger.info("TELEGRAM_ENABLED is false; skipping calls and bot startup.")
            logger.warning("Bot is idling. Please set credentials in Railway Variables to enable Telegram mode.")
            # Keep the container alive so the user can see the logs and fix variables
            while True:
                await asyncio.sleep(3600)
        
    except Exception as e:
        logger.exception("Failed to start bot")
        raise
    finally:
        # Avoid unclosed session warnings
        await music_backend.close()
        logger.info("Bot shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
