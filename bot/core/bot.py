"""Pyrogram Bot Client initialization."""

import logging
import asyncio
from typing import Optional
import os
from aiohttp import web
from pyrogram.client import Client
from pyrogram.sync import idle
from config import config
from bot.utils.metrics import metrics_collector, log_metrics_periodically

logger = logging.getLogger(__name__)


# Global bot client instance
bot_client: Optional[Client] = None
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

    # Optional metrics endpoints (guarded by config flags)
    try:
        if getattr(config, "METRICS_HTTP_ENABLED", False):
            async def _metrics_json(request):
                # Token can be supplied via `Authorization: Bearer <token>` or ?token=<token>
                import hmac
                import secrets
                
                token = None
                auth = request.headers.get("Authorization")
                if auth:
                    # Extract Bearer token or use full header
                    auth_stripped = auth.strip()
                    if auth_stripped.lower().startswith("bearer "):
                        token = auth_stripped[7:].strip()  # Remove "bearer " prefix
                    else:
                        # Reject non-Bearer auth schemes for security
                        return web.Response(status=401, text="Unauthorized: Use Bearer token")
                
                if token is None:
                    # Check query parameter as fallback
                    token = request.rel_url.query.get("token", "").strip()

                # Validate token using constant-time comparison to prevent timing attacks
                expected_token = getattr(config, "METRICS_HTTP_TOKEN", None)
                if expected_token:
                    if not token:
                        return web.Response(status=401, text="Unauthorized: Token required")
                    
                    # Use secrets.compare_digest for timing-safe comparison
                    try:
                        if not secrets.compare_digest(token, expected_token):
                            return web.Response(status=401, text="Unauthorized: Invalid token")
                    except Exception:
                        # secrets.compare_digest requires same-length strings
                        return web.Response(status=401, text="Unauthorized: Invalid token")

                payload = metrics_collector.export_json()
                return web.Response(text=payload, content_type="application/json")

            app.router.add_get("/metrics", _metrics_json)
            logger.info("Metrics HTTP endpoint enabled at /metrics")

        if getattr(config, "METRICS_PROMETHEUS_ENABLED", False):
            async def _metrics_prom(request):
                stats = metrics_collector.get_stats_by_action()
                lines = []
                lines.append('# HELP musicbot_callback_total Total callbacks received per action')
                lines.append('# TYPE musicbot_callback_total counter')
                for action, s in stats.items():
                    count = s.get("count", 0)
                    avg = s.get("avg_time_ms", 0)
                    lines.append(f'musicbot_callback_total{{action="{action}"}} {count}')
                    lines.append(f'musicbot_callback_avg_ms{{action="{action}"}} {avg}')
                # Overall samples
                lines.append(f'musicbot_total_samples {len(metrics_collector.metrics)}')
                text = "\n".join(lines)
                return web.Response(text=text, content_type="text/plain; version=0.0.4")

            app.router.add_get("/metrics/prometheus", _metrics_prom)
            logger.info("Prometheus metrics endpoint enabled at /metrics/prometheus")
    except Exception:
        logger.exception("Failed to register metrics endpoints")

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

    session_dir = os.getenv("SESSION_DIR")
    if session_dir:
        os.makedirs(session_dir, exist_ok=True)
    else:
        try:
            os.makedirs("./sessions", exist_ok=True)
            session_dir = "./sessions"
        except OSError:
            import tempfile
            session_dir = os.path.join(tempfile.gettempdir(), "musicbot_sessions")
            os.makedirs(session_dir, exist_ok=True)

    global bot_client
    bot_client = Client(
        "musicbot",
        api_id=config.API_ID,
        api_hash=config.API_HASH,
        bot_token=config.BOT_TOKEN,
        workdir=session_dir,
        plugins=dict(root="bot/plugins"),
    )

    # Start health check server for Railway
    await start_health_server()

    await bot_client.start()
    bot_info = await bot_client.get_me()
    logger.info(f"Bot started: @{bot_info.username} (id={bot_info.id})")

    if config.BOT_ID and bot_info.id != config.BOT_ID:
        logger.warning(
            f"Configured BOT_ID={config.BOT_ID} does not match actual bot id {bot_info.id}."
        )

    if config.BOT_USERNAME and bot_info.username and config.BOT_USERNAME.lower().strip("@") != bot_info.username.lower():
        logger.warning(
            f"Configured BOT_USERNAME={config.BOT_USERNAME} does not match actual bot username @{bot_info.username}."
        )

    if not config.BOT_USERNAME and bot_info.username:
        config.BOT_USERNAME = bot_info.username
        logger.info(f"BOT_USERNAME was not set; using @{config.BOT_USERNAME} from Telegram API")

    if bot_info.username and config.BOT_USERNAME_ALT and bot_info.username.lower() == config.BOT_USERNAME_ALT.lower().strip("@"):
        logger.info("Bot username matches configured BOT_USERNAME_ALT")

    # Start metrics collection background task
    metrics_task = getattr(bot_client, "metrics_task", None)
    if metrics_task is None or metrics_task.done():
        metrics_task = asyncio.create_task(log_metrics_periodically(interval_seconds=300))
        setattr(bot_client, "metrics_task", metrics_task)
        logger.info("Metrics collection started (300s interval)")
    else:
        logger.debug("Metrics task already running, skipping creation")

    await idle()
    return bot_client


async def stop_bot():
    """Stop the bot client and cancel background tasks cleanly."""
    global bot_client
    if bot_client is None:
        return

    metrics_task = getattr(bot_client, "metrics_task", None)
    if metrics_task is not None:
        metrics_task.cancel()
        try:
            await metrics_task
        except asyncio.CancelledError:
            pass
        finally:
            setattr(bot_client, "metrics_task", None)
            logger.info("Metrics collection task cancelled")

    try:
        await bot_client.stop()
        logger.info("Bot client stopped")
    except Exception as exc:
        logger.error(f"Error stopping bot client: {exc}")
    finally:
        bot_client = None
