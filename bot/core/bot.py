"""Pyrogram Bot Client initialization."""

import asyncio
import logging
import os
from typing import Optional

from fastapi import FastAPI, Request, Response
from fastapi.responses import PlainTextResponse, JSONResponse
import uvicorn
from admin_panel import admin_app
from pyrogram.client import Client
from pyrogram.types import BotCommand
from config import config
from bot.utils.metrics import metrics_collector, log_metrics_periodically

logger = logging.getLogger(__name__)


# Global bot client instance
bot_client: Optional[Client] = None
_health_runner = None


# Health check server for cloud platforms
async def health_check():
    return PlainTextResponse("OK")


async def telegram_webhook(request: Request):
    """Handle incoming updates from Telegram via Webhook."""
    if not bot_client:
        return Response(status_code=503)

    # Security: Verify secret if configured
    if config.WEBHOOK_SECRET:
        secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
        if secret != config.WEBHOOK_SECRET:
            logger.warning("Unauthorized webhook request (invalid secret)")
            return Response(status_code=401)

    try:
        data = await request.json()
        logger.debug("Received webhook update: %s", data)
        # Pyrogram does not expose a stable public webhook feeder here. Keeping
        # this endpoint non-crashing is still useful for health/webhook probes.
        return Response(content="OK", status_code=200)
    except Exception as e:
        logger.error("Error processing webhook: %s", e)
        return Response(status_code=500)


def _build_bot_commands() -> list[BotCommand]:
    """Build the bot command menu shown in Telegram clients."""
    return [
        BotCommand("play", "Play music or add to queue"),
        BotCommand("moodsearch", "Ask Brook for a mood-based search"),
        BotCommand("mooddiscovery", "Browse Brook's mood suggestions"),
        BotCommand("next", "Skip to the next track"),
        BotCommand("prev", "Play the previous track"),
        BotCommand("ping", "Check bot latency"),
        BotCommand("off", "Stop playback and clear the queue"),
        BotCommand("help", "Show the command list"),
        BotCommand("queue", "Show the current queue"),
        BotCommand("now", "Show the currently playing track"),
        BotCommand("pause", "Pause playback"),
        BotCommand("resume", "Resume playback"),
        BotCommand("skip", "Skip the current track"),
        BotCommand("stop", "Stop playback and clear the queue"),
        BotCommand("seek", "Seek within the current track"),
        BotCommand("volume", "Set playback volume"),
        BotCommand("replay", "Replay the current track"),
        BotCommand("vplay", "Play a VK or Deezer track"),
        BotCommand("clearqueue", "Clear the queue"),
        BotCommand("remove", "Remove a queued track"),
        BotCommand("shuffle", "Shuffle the queue"),
        BotCommand("loop", "Toggle loop mode"),
        BotCommand("setaggressive", "Toggle aggressive play mode"),
        BotCommand("plcreate", "Create a Soul King setlist"),
        BotCommand("pllist", "List your saved setlists"),
        BotCommand("pladd", "Add a track to a setlist"),
        BotCommand("plplay", "Perform a saved setlist"),
        BotCommand("serverhealth", "Check Brook's music relay"),
        BotCommand("userbotjoin", "Join or create the voice chat"),
        BotCommand("vcdebug", "Inspect voice chat state"),
        BotCommand("addsudo", "Grant sudo access"),
        BotCommand("delsudo", "Revoke sudo access"),
        BotCommand("sudolist", "List sudo users"),
        BotCommand("gban", "Globally ban a user"),
        BotCommand("ungban", "Remove a global ban"),
        BotCommand("block", "Block a user in the current group"),
        BotCommand("unblock", "Unblock a user in the current group"),
        BotCommand("stats", "Show bot statistics"),
        BotCommand("broadcast", "Broadcast a message"),
        BotCommand("maintenance", "Toggle maintenance mode"),
        BotCommand("restart", "Restart the bot"),
    ]


async def _register_bot_commands(client: Client) -> None:
    """Register Telegram bot commands, with compatibility fallback."""
    commands = _build_bot_commands()
    setter = getattr(client, "set_bot_commands", None) or getattr(client, "set_my_commands", None)
    if setter is None:
        logger.debug("Bot command registration is unavailable on this Pyrogram build")
        return

    try:
        await setter(commands)
        logger.info("Registered %d Telegram bot commands", len(commands))
    except Exception as exc:
        logger.warning("Failed to register Telegram bot commands: %s", exc)


def _get_valid_port() -> Optional[int]:
    """Return a safe platform health-server port, or None in worker mode."""
    port_str = os.getenv("PORT")
    if not port_str:
        logger.info("PORT environment variable not found. Skipping health check server (Worker mode).")
        return None

    try:
        port = int(port_str)
    except (TypeError, ValueError):
        logger.warning("Invalid PORT=%r. Skipping health check server instead of crashing.", port_str)
        return None

    if port <= 0 or port > 65535:
        logger.warning("PORT=%s is outside valid TCP range. Skipping health check server.", port)
        return None

    return port


async def start_health_server():
    """Start health check server using FastAPI."""
    global _health_runner

    if _health_runner is not None:
        return _health_runner

    port = _get_valid_port()
    if port is None:
        return None

    app = FastAPI(title="Health Server")

    app.mount("/admin", admin_app)

    @app.get("/")
    @app.get("/health")
    async def _health():
        return await health_check()

    if config.WEBHOOK_URL:
        webhook_path = config.WEBHOOK_PATH or "/webhook"
        if not webhook_path.startswith("/"):
            webhook_path = f"/{webhook_path}"
            config.WEBHOOK_PATH = webhook_path
        app.post(webhook_path)(telegram_webhook)
        logger.info("Webhook endpoint registered at %s", webhook_path)

    try:
        if getattr(config, "METRICS_HTTP_ENABLED", False):
            @app.get("/metrics")
            async def _metrics_json(request: Request):
                import secrets
                token = None
                auth = request.headers.get("Authorization")
                if auth:
                    auth_stripped = auth.strip()
                    if auth_stripped.lower().startswith("bearer "):
                        token = auth_stripped[7:].strip()
                    else:
                        return Response(content="Unauthorized: Use Bearer token", status_code=401)

                if token is None:
                    token = request.query_params.get("token", "").strip()

                expected_token = getattr(config, "METRICS_HTTP_TOKEN", None)
                if expected_token:
                    if not token:
                        return Response(content="Unauthorized: Token required", status_code=401)
                    try:
                        if not secrets.compare_digest(token, expected_token):
                            return Response(content="Unauthorized: Invalid token", status_code=401)
                    except Exception:
                        return Response(content="Unauthorized: Invalid token", status_code=401)

                payload = metrics_collector.export_json()
                return JSONResponse(content=payload)
            logger.info("Metrics HTTP endpoint enabled at /metrics")

        if getattr(config, "METRICS_PROMETHEUS_ENABLED", False):
            @app.get("/metrics/prometheus")
            async def _metrics_prom():
                stats = metrics_collector.get_stats_by_action()
                lines = [
                    '# HELP musicbot_callback_total Total callbacks received per action',
                    '# TYPE musicbot_callback_total counter',
                ]
                for action, s in stats.items():
                    count = s.get("count", 0)
                    avg = s.get("avg_time_ms", 0)
                    lines.append(f'musicbot_callback_total{{action="{action}"}} {count}')
                    lines.append(f'musicbot_callback_avg_ms{{action="{action}"}} {avg}')
                lines.append(f'musicbot_total_samples {len(metrics_collector.metrics)}')
                text = "\n".join(lines)
                return PlainTextResponse(content=text)
            logger.info("Prometheus metrics endpoint enabled at /metrics/prometheus")
    except Exception:
        logger.exception("Failed to register metrics endpoints")

    # Configure and run uvicorn server in background.
    u_config = uvicorn.Config(app, host="0.0.0.0", port=port, loop="asyncio", log_level="warning")
    runner = uvicorn.Server(u_config)
    task = asyncio.create_task(runner.serve())
    task.add_done_callback(lambda t: logger.exception("Health server stopped unexpectedly", exc_info=t.exception()) if not t.cancelled() and t.exception() else None)

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

    # Start health check server (only if PORT is available and valid)
    await start_health_server()

    # Determine update method: Webhook vs Polling.
    if config.WEBHOOK_URL and _get_valid_port() is not None:
        webhook_addr = f"{config.WEBHOOK_URL.rstrip('/')}{config.WEBHOOK_PATH}"
        logger.info("Setting webhook to: %s", webhook_addr)
        await bot_client.set_webhook(
            url=webhook_addr,
            secret_token=config.WEBHOOK_SECRET,
            max_connections=int(os.getenv("WEBHOOK_MAX_CONNECTIONS", "40")),
            drop_pending_updates=True,
        )
        webhook_info = await bot_client.get_webhook_info()
        logger.info("Webhook status: %s", webhook_info)
        await bot_client.connect()
        logger.info("Bot connected in WEBHOOK mode.")
    else:
        if config.WEBHOOK_URL:
            logger.warning("WEBHOOK_URL is set but no valid PORT exists. Falling back to POLLING.")

        try:
            await bot_client.delete_webhook()
            logger.info("Stale webhooks cleared.")
        except Exception:
            pass
        await bot_client.start()
        logger.info("Bot started in POLLING mode (Worker).")

    bot_info = await bot_client.get_me()
    logger.info("Bot info: @%s (id=%s)", bot_info.username, bot_info.id)

    if config.BOT_ID and bot_info.id != config.BOT_ID:
        logger.warning(
            "Configured BOT_ID=%s does not match actual bot id %s.",
            config.BOT_ID,
            bot_info.id,
        )

    if config.BOT_USERNAME and bot_info.username and config.BOT_USERNAME.lower().strip("@") != bot_info.username.lower():
        logger.warning(
            "Configured BOT_USERNAME=%s does not match actual bot username @%s.",
            config.BOT_USERNAME,
            bot_info.username,
        )

    if not config.BOT_USERNAME and bot_info.username:
        config.BOT_USERNAME = bot_info.username
        logger.info("BOT_USERNAME was not set; using @%s from Telegram API", config.BOT_USERNAME)

    if bot_info.username and config.BOT_USERNAME_ALT and bot_info.username.lower() == config.BOT_USERNAME_ALT.lower().strip("@"):
        logger.info("Bot username matches configured BOT_USERNAME_ALT")

    await _register_bot_commands(bot_client)

    # Start metrics collection background task
    metrics_task = getattr(bot_client, "metrics_task", None)
    if metrics_task is None or metrics_task.done():
        metrics_task = asyncio.create_task(log_metrics_periodically(interval_seconds=300))
        setattr(bot_client, "metrics_task", metrics_task)
        logger.info("Metrics collection started (300s interval)")
    else:
        logger.debug("Metrics task already running, skipping creation")

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
        logger.error("Error stopping bot client: %s", exc)
    finally:
        bot_client = None
