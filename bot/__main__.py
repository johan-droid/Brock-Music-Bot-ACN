"""
Music Bot - Telegram Voice Chat Music Bot
A Python-based bot for streaming high-quality audio into Telegram group voice calls.
"""

import asyncio
import contextlib
import logging
import os

import pyrogram.errors

# Monkey-patch for py-tgcalls compatibility with newer pyrogram versions
if not hasattr(pyrogram.errors, "GroupcallForbidden"):
    setattr(
        pyrogram.errors,
        "GroupcallForbidden",
        getattr(pyrogram.errors, "BroadcastForbidden", pyrogram.errors.Forbidden),
    )

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
from bot.utils.resilience import global_watchdog, log_error, notify_owner


async def _cleanup_streaming_stack(logger: logging.Logger) -> None:
    """Clean partially-started voice/userbot state before retrying startup."""
    try:
        from bot.core import call

        if call.call_manager:
            await call.call_manager.stop()
            call.call_manager = None
    except Exception as exc:
        logger.debug("Streaming cleanup: call manager stop failed: %s", exc)

    try:
        from bot.core.userbot import stop_userbots

        await stop_userbots()
    except Exception as exc:
        logger.debug("Streaming cleanup: userbot stop failed: %s", exc)

    try:
        from bot.utils.time_manager import time_manager

        time_manager.stop()
    except Exception as exc:
        logger.debug("Streaming cleanup: time manager stop failed: %s", exc)


async def _assistant_bootstrap_loop(logger: logging.Logger) -> None:
    """
    Initialize assistant userbots and py-tgcalls without blocking the main bot.

    The old flow retried after failures but left partially-started sessions/call
    managers alive. On cloud hosts this can look like random crashes because the
    next retry reuses the same Telegram auth key while the previous client is
    still connected. This loop always cleans partial state before retrying and
    uses bounded exponential backoff to avoid aggressive restart storms.
    """
    retry = 0

    while True:
        try:
            await _cleanup_streaming_stack(logger)

            userbots = await init_userbots()
            logger.info("Initialized %d userbot(s)", len(userbots))

            await init_calls(userbots)

            from bot.core import call
            from bot.plugins.play import on_track_end

            if call.call_manager and on_track_end not in call.call_manager.on_stream_end_handlers:
                call.call_manager.on_stream_end_handlers.append(on_track_end)

            start_scheduler()

            from bot.utils.time_manager import time_manager

            time_manager.start()
            logger.info("Music streaming engine ready.")
            return

        except asyncio.CancelledError:
            logger.info("Assistant initialization task cancelled")
            await _cleanup_streaming_stack(logger)
            raise
        except Exception as exc:
            retry += 1
            log_error("Assistant/music engine initialization failed", exc)
            await _cleanup_streaming_stack(logger)

            delay = min(300, 10 * (2 ** min(retry - 1, 5)))
            logger.warning(
                "Assistant/music engine is not ready yet: %s. Retrying in %ss (attempt %d).",
                exc,
                delay,
                retry,
            )
            await asyncio.sleep(delay)


def _log_task_result(task: asyncio.Task) -> None:
    """Log unexpected background task termination instead of silently losing it."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc:
        logging.getLogger(__name__).exception("Background startup task failed", exc_info=exc)


async def main():
    try:
        await _main_impl()
    except Exception as e:
        log_error("Critical unhandled exception in main loop", e)
        await notify_owner(f"Bot crashed! Restarting. Error: {str(e)}")
        os._exit(1)  # Force the platform supervisor to restart the process


async def _main_impl():
    """Main entry point - initialize all components."""
    setup_logging()
    logger = logging.getLogger(__name__)
    logger.info("Starting Music Bot...")
    global_watchdog.start()

    assistant_task: asyncio.Task | None = None

    # 1. Start health server immediately for platform health checks
    await start_health_server()

    try:
        # 2. Database & Core Services
        await init_database()
        await init_redis()
        await init_queue_manager()
        await music_backend.init()

        # 3. Initialize main Bot Client first (responsive immediately).
        if config.TELEGRAM_ENABLED:
            await init_bot()
            logger.info("Main bot client started and responding to updates.")
        else:
            logger.warning("Telegram client is disabled. Health server will stay up for diagnostics.")

        # 4. Initialize assistants/calls in the background.
        assistant_task = asyncio.create_task(_assistant_bootstrap_loop(logger))
        assistant_task.add_done_callback(_log_task_result)
        logger.info("Assistant initialization task started in background.")

        # 5. Block until termination.
        from pyrogram.sync import idle

        await idle()

    except Exception:
        logger.exception("Failed to start bot")
        raise
    finally:
        logger.info("Shutting down...")
        global_watchdog.stop()

        if assistant_task is not None and not assistant_task.done():
            assistant_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await assistant_task

        try:
            from bot.core.bot import stop_bot

            await stop_bot()
        except Exception:
            pass

        await _cleanup_streaming_stack(logger)
        await music_backend.close()

        logger.info("Bot shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
