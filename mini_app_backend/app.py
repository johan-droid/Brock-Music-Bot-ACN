"""ASGI app for Soul King Telegram Mini App backend."""

from __future__ import annotations

import time
from typing import Set

import socketio
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from bot.core.queue import init_queue_manager
from bot.utils.cache import cache, init_cache
from bot.utils.database import init_database
from mini_app_backend.realtime.socket_server import sio
from mini_app_backend.routers import health, lobby, search, sessions, stream
from mini_app_backend.services.music_service import music_service
from mini_app_backend.settings import settings
from bot.core.bot import init_bot, stop_bot, telegram_webhook
from config import config


api_app = FastAPI(
    title="Soul King Mini App Backend",
    version="0.1.0",
    description="Telegram Mini App backend for lobby + individual playback.",
)

cors_allowed_origins = settings.allowed_origins
api_app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_allowed_origins,
    allow_origin_regex=None,
    allow_credentials=settings.MINI_APP_ALLOW_CREDENTIALS and ("*" not in cors_allowed_origins),
    allow_methods=["*"],
    allow_headers=["*"],
)

_RATE_LIMIT_EXEMPT_PATHS: Set[str] = {
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
}


@api_app.on_event("startup")
async def on_startup() -> None:
    await init_cache()
    await init_database()
    await init_queue_manager()
    await music_service.start()
    
    # Start the Telegram bot client in the same process
    if config.TELEGRAM_ENABLED:
        try:
            import os
            os.environ["FASTAPI_INTEGRATED"] = "true"
            await init_bot()
            print("🤖 Telegram Bot initialized inside Mini App process")
        except Exception as e:
            print(f"❌ Failed to initialize bot: {e}")


@api_app.on_event("shutdown")
async def on_shutdown() -> None:
    await stop_bot()
    await music_service.close()


@api_app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    path = request.url.path
    if path in _RATE_LIMIT_EXEMPT_PATHS or path.startswith("/socket.io"):
        return await call_next(request)

    client_ip = request.client.host if request.client else "unknown"
    minute_bucket = int(time.time() // 60)
    key = f"mini:rl:{client_ip}:{minute_bucket}"

    count = await cache.incr(key, 1)
    if count == 1:
        await cache.expire(key, 65)
    if count > settings.MINI_APP_RATE_LIMIT_PER_MINUTE:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    return await call_next(request)


api_app.include_router(health.router)
api_app.include_router(search.router, prefix="/api/v1")
api_app.include_router(stream.router, prefix="/api/v1")
api_app.include_router(lobby.router, prefix="/api/v1")
api_app.include_router(sessions.router, prefix="/api/v1")

# Telegram Webhook Integration
if config.WEBHOOK_URL:
    webhook_path = config.WEBHOOK_PATH or "/webhook"
    from fastapi.responses import JSONResponse
    @api_app.post(webhook_path)
    async def handle_telegram_webhook(request: Request):
        if not config.WEBHOOK_SECRET:
             return JSONResponse(status_code=200, content={"status": "ok"})
             
        secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
        if secret != config.WEBHOOK_SECRET:
            return JSONResponse(status_code=401, content={"error": "unauthorized"})
            
        try:
            data = await request.json()
            # Feed to pyrogram client if it's running
            from bot.core.bot import bot_client
            if bot_client:
                 # Note: In a production setup, you'd want to use a proper update parser here
                 # For now, we ensure the bot stays 'active' in Telegram's eyes.
                 pass
            return JSONResponse(status_code=200, content={"status": "ok"})
        except Exception:
            return JSONResponse(status_code=500, content={"error": "internal error"})
    print(f"🔗 Telegram Webhook route registered at {webhook_path}")

# Final ASGI app includes Socket.IO endpoint at /socket.io.
app = socketio.ASGIApp(sio, other_asgi_app=api_app, socketio_path="socket.io")

