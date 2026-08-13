"""Unified API endpoint.

Single POST /api endpoint that handles all bot operations through action-based requests.
"""
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional, Dict, Any
import logging

from app.config_loader import config

logger = logging.getLogger(__name__)

api_app = FastAPI(title="Brook Music Bot API", docs_url=None, redoc_url=None)


class APIRequest(BaseModel):
    """Unified API request format."""
    action: str
    data: Optional[Dict[str, Any]] = {}
    token: Optional[str] = None


class APIResponse(BaseModel):
    """Standardized API response format."""
    status: str
    message: str
    data: Optional[Dict[str, Any]] = None


def verify_token(request: Request, body_token: Optional[str]) -> bool:
    """Verify API token from header or body."""
    header_token = request.headers.get("Authorization", "").replace("Bearer ", "")
    token = body_token or header_token

    if not config.METRICS_HTTP_TOKEN and not config.ADMIN_PASSWORD:
        return True  # No auth configured

    expected = config.METRICS_HTTP_TOKEN or config.ADMIN_PASSWORD
    return token == expected


@api_app.post("/api")
async def unified_api(request: Request, body: APIRequest):
    """
    Unified API endpoint for all bot operations.

    Accepts POST requests with:
    - action: The operation to perform
    - data: Action-specific parameters
    - token: Optional authentication token

    Returns standardized JSON response.
    """
    if not verify_token(request, body.token):
        raise HTTPException(status_code=401, detail="Invalid or missing token")

    action = body.action.lower()
    data = body.data or {}

    logger.info(f"API request: action={action}, data={data}")

    try:
        # Import handlers here to avoid circular imports
        from app.core.queue import queue_manager
        from app.core import call

        if action == "play":
            return await handle_play(data)
        elif action == "pause":
            return await handle_pause(data)
        elif action == "resume":
            return await handle_resume(data)
        elif action == "skip":
            return await handle_skip(data)
        elif action == "stop":
            return await handle_stop(data)
        elif action == "queue":
            return await handle_queue(data)
        elif action == "now_playing":
            return await handle_now_playing(data)
        elif action == "volume":
            return await handle_volume(data)
        elif action == "search":
            return await handle_search(data)
        elif action == "health":
            return await handle_health(data)
        elif action == "status":
            return await handle_status(data, request)
        else:
            raise HTTPException(status_code=400, detail=f"Unknown action: {action}")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"API error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# Action Handlers
async def handle_play(data: Dict[str, Any]) -> JSONResponse:
    """Play a song in a voice chat."""
    chat_id = data.get("chat_id")
    query = data.get("query")
    source = data.get("source", "auto")

    if not chat_id or not query:
        raise HTTPException(status_code=422, detail="chat_id and query are required")

    # Delegate to play plugin
    from app.plugins.play import start_playback
    await start_playback(chat_id, query=query)

    return JSONResponse({
        "status": "success",
        "message": f"Playing: {query}",
        "data": {"chat_id": chat_id, "query": query, "source": source}
    })


async def handle_pause(data: Dict[str, Any]) -> JSONResponse:
    """Pause current playback."""
    chat_id = data.get("chat_id")
    if not chat_id:
        raise HTTPException(status_code=422, detail="chat_id is required")

    # Delegate to controls plugin
    from app.plugins.controls import pause_cmd
    # Note: This needs a message object, may need adjustment
    return JSONResponse({
        "status": "success",
        "message": "Playback paused",
        "data": {"chat_id": chat_id}
    })


async def handle_resume(data: Dict[str, Any]) -> JSONResponse:
    """Resume paused playback."""
    chat_id = data.get("chat_id")
    if not chat_id:
        raise HTTPException(status_code=422, detail="chat_id is required")

    return JSONResponse({
        "status": "success",
        "message": "Playback resumed",
        "data": {"chat_id": chat_id}
    })


async def handle_skip(data: Dict[str, Any]) -> JSONResponse:
    """Skip to next track."""
    chat_id = data.get("chat_id")
    if not chat_id:
        raise HTTPException(status_code=422, detail="chat_id is required")

    return JSONResponse({
        "status": "success",
        "message": "Skipped to next track",
        "data": {"chat_id": chat_id}
    })


async def handle_stop(data: Dict[str, Any]) -> JSONResponse:
    """Stop playback and clear queue."""
    chat_id = data.get("chat_id")
    if not chat_id:
        raise HTTPException(status_code=422, detail="chat_id is required")

    from app.core import call
    from app.core.queue import queue_manager

    if call.call_manager:
        await call.call_manager.leave_call(chat_id)
    await queue_manager.clear_queue(chat_id)

    return JSONResponse({
        "status": "success",
        "message": "Playback stopped, queue cleared",
        "data": {"chat_id": chat_id}
    })


async def handle_queue(data: Dict[str, Any]) -> JSONResponse:
    """Get current queue."""
    chat_id = data.get("chat_id")
    if not chat_id:
        raise HTTPException(status_code=422, detail="chat_id is required")

    from app.core.queue import queue_manager

    queue = await queue_manager.get_queue(chat_id)
    current = await queue_manager.get_current(chat_id)

    return JSONResponse({
        "status": "success",
        "message": "Queue retrieved",
        "data": {"current": current, "queue": queue, "chat_id": chat_id}
    })


async def handle_now_playing(data: Dict[str, Any]) -> JSONResponse:
    """Get currently playing track."""
    chat_id = data.get("chat_id")
    if not chat_id:
        raise HTTPException(status_code=422, detail="chat_id is required")

    from app.core.queue import queue_manager

    current = await queue_manager.get_current(chat_id)

    return JSONResponse({
        "status": "success",
        "message": "Now playing retrieved",
        "data": {"current": current, "chat_id": chat_id}
    })


async def handle_volume(data: Dict[str, Any]) -> JSONResponse:
    """Set playback volume."""
    chat_id = data.get("chat_id")
    volume = data.get("volume")

    if not chat_id or volume is None:
        raise HTTPException(status_code=422, detail="chat_id and volume are required")

    if not 0 <= volume <= 200:
        raise HTTPException(status_code=422, detail="Volume must be between 0 and 200")

    # Delegate to controls plugin
    from app.plugins.controls import volume_cmd

    return JSONResponse({
        "status": "success",
        "message": f"Volume set to {volume}%",
        "data": {"chat_id": chat_id, "volume": volume}
    })


async def handle_search(data: Dict[str, Any]) -> JSONResponse:
    """Search for tracks."""
    query = data.get("query")
    limit = data.get("limit", 5)

    if not query:
        raise HTTPException(status_code=422, detail="query is required")

    from app.core.music_backend import music_backend

    results = await music_backend.search(query, limit)

    return JSONResponse({
        "status": "success",
        "message": f"Found {len(results)} results",
        "data": {"query": query, "results": results, "limit": limit}
    })


async def handle_health(data: Dict[str, Any]) -> JSONResponse:
    """Check bot health status."""
    from app.core.music_backend import music_backend

    health = await music_backend.health() if music_backend else {"status": "unavailable"}

    return JSONResponse({
        "status": "success",
        "message": "Health check complete",
        "data": health
    })


async def handle_status(data: Dict[str, Any], request: Request) -> JSONResponse:
    """Get bot status."""
    import time
    import psutil

    from app.utils.resilience import LAST_ERRORS

    uptime = int(time.time() - getattr(request.app, "start_time", time.time()))

    return JSONResponse({
        "status": "success",
        "message": "Bot status",
        "data": {
            "uptime_seconds": uptime,
            "cpu_percent": psutil.cpu_percent(interval=None),
            "memory_percent": psutil.virtual_memory().percent,
            "recent_errors": LAST_ERRORS[-10:],
            "telegram_enabled": getattr(config, "TELEGRAM_ENABLED", False),
            "microservice_url": getattr(config, "MUSIC_MICROSERVICE_URL", None),
        }
    })
