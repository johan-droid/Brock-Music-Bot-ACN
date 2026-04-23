"""Socket.IO event handlers for lobby sync."""

from __future__ import annotations

from typing import Any, Dict

import socketio

from mini_app_backend.auth import InitDataError, validate_init_data
from mini_app_backend.schemas import LobbyParticipant, TrackPayload
from mini_app_backend.services.lobby_service import lobby_service
from mini_app_backend.settings import settings


sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins=settings.allowed_origins or [],
)

_sid_user_map: Dict[str, Dict[str, Any]] = {}


def _room(chat_id: int) -> str:
    return f"lobby:{chat_id}"


@sio.event
async def connect(sid: str, environ: Dict[str, Any], auth: Dict[str, Any] | None):
    init_data = ""
    if isinstance(auth, dict):
        init_data = str(auth.get("initData") or auth.get("init_data") or "")

    try:
        context = validate_init_data(
            init_data=init_data,
            bot_token=settings.BOT_TOKEN or "",
            max_age_seconds=settings.MINI_APP_INITDATA_MAX_AGE_SECONDS,
        )
    except InitDataError:
        return False

    _sid_user_map[sid] = {
        "user_id": context.user.id,
        "username": context.user.username,
        "first_name": context.user.first_name,
    }
    return True


@sio.event
async def disconnect(sid: str):
    _sid_user_map.pop(sid, None)


@sio.event
async def join_lobby(sid: str, data: Dict[str, Any]):
    chat_id = int((data or {}).get("chat_id") or 0)
    if chat_id <= 0:
        return {"ok": False, "error": "chat_id is required"}

    await sio.enter_room(sid, _room(chat_id))

    user_info = _sid_user_map.get(sid)
    if user_info:
        participant = LobbyParticipant(
            user_id=int(user_info["user_id"]),
            username=user_info.get("username"),
            first_name=user_info.get("first_name"),
        )
        state = await lobby_service.join_participant(chat_id, participant)
        await sio.emit("lobby_state", state.model_dump(), room=_room(chat_id))
    else:
        state = await lobby_service.get_state(chat_id)
        await sio.emit("lobby_state", state.model_dump(), room=sid)

    return {"ok": True}


@sio.event
async def leave_lobby(sid: str, data: Dict[str, Any]):
    chat_id = int((data or {}).get("chat_id") or 0)
    if chat_id <= 0:
        return {"ok": False, "error": "chat_id is required"}

    await sio.leave_room(sid, _room(chat_id))

    user_info = _sid_user_map.get(sid)
    if user_info:
        state = await lobby_service.leave_participant(chat_id, int(user_info["user_id"]))
        await sio.emit("lobby_state", state.model_dump(), room=_room(chat_id))

    return {"ok": True}


@sio.event
async def seek(sid: str, data: Dict[str, Any]):
    _ = sid
    chat_id = int((data or {}).get("chat_id") or 0)
    position = int((data or {}).get("position") or 0)
    if chat_id <= 0:
        return {"ok": False, "error": "chat_id is required"}

    state = await lobby_service.seek(chat_id, position)
    await sio.emit("lobby_state", state.model_dump(), room=_room(chat_id))
    return {"ok": True, "version": state.version}


@sio.event
async def track_change(sid: str, data: Dict[str, Any]):
    _ = sid
    chat_id = int((data or {}).get("chat_id") or 0)
    payload = (data or {}).get("track")
    position = int((data or {}).get("position") or 0)
    if chat_id <= 0 or not isinstance(payload, dict):
        return {"ok": False, "error": "chat_id and track are required"}

    track = TrackPayload.model_validate(payload)
    state = await lobby_service.set_now_playing(chat_id=chat_id, track=track, position=position)
    await sio.emit("lobby_state", state.model_dump(), room=_room(chat_id))
    return {"ok": True, "version": state.version}


@sio.event
async def queue_update(sid: str, data: Dict[str, Any]):
    _ = sid
    chat_id = int((data or {}).get("chat_id") or 0)
    payload = (data or {}).get("track")
    play_next = bool((data or {}).get("play_next") or False)
    if chat_id <= 0 or not isinstance(payload, dict):
        return {"ok": False, "error": "chat_id and track are required"}

    user_info = _sid_user_map.get(sid) or {}
    user_id = int(user_info.get("user_id") or 0)
    if user_id <= 0:
        return {"ok": False, "error": "missing socket user context"}

    track = TrackPayload.model_validate(payload)
    state = await lobby_service.add_to_queue(chat_id=chat_id, track=track, user_id=user_id, play_next=play_next)
    await sio.emit("lobby_state", state.model_dump(), room=_room(chat_id))
    return {"ok": True, "version": state.version}

