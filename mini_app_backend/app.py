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


@api_app.on_event("shutdown")
async def on_shutdown() -> None:
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

# Final ASGI app includes Socket.IO endpoint at /socket.io.
app = socketio.ASGIApp(sio, other_asgi_app=api_app, socketio_path="socket.io")

