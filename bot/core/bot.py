"""Pyrogram Bot Client initialization."""

import logging
import asyncio
import os
from aiohttp import web
from pyrogram import Client, filters, idle
from pyrogram.handlers import MessageHandler
from config import config

logger = logging.getLogger(__name__)

# Global bot client instance
bot_client = None
_health_runner = None

# Health check server for Railway
async def health_check(request):
    """Simple health check endpoint for Railway."""
    return web.Response(text="OK", status=200)

async def start_health_server():
    """Start health check server on port 8080."""
    global _health_runner

    if _health_runner is not None:
        return _health_runner

    app = web.Application()
    app.router.add_get("/", health_check)
    app.router.add_get("/health", health_check)
    
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", "8080"))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info("Health check server started on port %s", port)
    _health_runner = runner
    return runner


async def init_bot():
    """Initialize and start the bot client.
    
    Auto-loads all plugins from bot/plugins/ directory.
    """
    if not config.TELEGRAM_ENABLED:
        logger.info("TELEGRAM_ENABLED is false; skipping bot client initialization")
        return None

    if not config.BOT_TOKEN or not config.API_ID or not config.API_HASH:
        raise RuntimeError("BOT_TOKEN, API_ID, and API_HASH are required when TELEGRAM_ENABLED is true")

    global bot_client
    bot_client = Client(
        "musicbot",
        api_id=config.API_ID,
        api_hash=config.API_HASH,
        bot_token=config.BOT_TOKEN,
        workdir="./sessions",
        plugins=dict(root="bot/plugins"),
    )

    # Start health check server for Railway
    await start_health_server()

    await bot_client.start()
    bot_info = await bot_client.get_me()
    logger.info(f"Bot started: @{bot_info.username}")

    await idle()
    return bot_client
