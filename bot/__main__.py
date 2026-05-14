"""
Music Bot - Telegram Voice Chat Music Bot
A Python-based bot for streaming high-quality audio into Telegram group voice calls.
"""

import asyncio
import logging
import pyrogram.errors

# Monkey-patch for py-tgcalls compatibility with newer pyrogram versions
if not hasattr(pyrogram.errors, "GroupcallForbidden"):
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
    setup_logging()
    logger = logging.getLogger(__name__)
    logger.info("Starting Music Bot...")

    # 1. Start health server immediately for platform health checks
    await start_health_server()
    
    try:
        # 2. Database & Core Services
        await init_database()
        await init_redis()
        await init_queue_manager()
        await music_backend.init()
        
        # 3. Initialize main Bot Client first (Responsive immediately)
        # This allows the bot to respond to /start while assistants initialize.
        if config.TELEGRAM_ENABLED:
            await init_bot()
            logger.info("Main bot client started and responding to updates.")

        # 4. Initialize Userbots (Assistants) in the background
        # This prevents the bot from being "stuck" if an assistant session is invalid.
        async def init_userbots_with_autoretry():
            while True:
                try:
                    userbots = await init_userbots()
                    logger.info(f"Initialized {len(userbots)} userbot(s)")
                    
                    # 5. Once userbots are ready, initialize Calls
                    await init_calls(userbots)
                    from bot.core.call import call_manager
                    from bot.plugins.play import on_track_end
                    call_manager.on_stream_end_handlers.append(on_track_end)
                    
                    start_scheduler()
                    from bot.utils.time_manager import time_manager
                    time_manager.start()
                    logger.info("Music streaming engine ready.")
                    return userbots
                except Exception as exc:
                    logger.warning(f"Assistant auth issue: {exc}. Retrying in 30s...")
                    await asyncio.sleep(30)
                    continue

        # Start assistant init task without blocking the main bot
        asyncio.create_task(init_userbots_with_autoretry())
        logger.info("Assistant initialization task started in background.")
        
        # 6. Block until termination
        from pyrogram.sync import idle
        await idle()
        
    except Exception as e:
        logger.exception("Failed to start bot")
        raise
    finally:
        logger.info("Shutting down...")
        
        try:
            from bot.core.bot import stop_bot
            await stop_bot()
        except Exception: pass

        try:
            from bot.core.call import call_manager
            if call_manager: await call_manager.stop()
        except Exception: pass

        try:
            from bot.core.userbot import stop_userbots
            await stop_userbots()
        except Exception: pass

        await music_backend.close()

        try:
            from bot.utils.time_manager import time_manager
            time_manager.stop()
        except Exception: pass

        logger.info("Bot shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
