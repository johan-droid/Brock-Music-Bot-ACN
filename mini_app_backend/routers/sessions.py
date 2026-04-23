"""Individual listening session endpoints."""

from __future__ import annotations

import json
import time
from typing import Any, Dict

from fastapi import APIRouter, Depends

import bot.utils.database as database_module
from bot.utils.cache import cache
from mini_app_backend.dependencies import require_auth_context
from mini_app_backend.schemas import AuthContext, SessionState, TrackPayload, UserPreferences
from mini_app_backend.settings import settings


router = APIRouter(prefix="/sessions", tags=["sessions"])


def _session_key(user_id: int) -> str:
    return f"mini:session:{user_id}"


async def _load_session(user_id: int) -> Dict[str, Any]:
    app_db = getattr(database_module, "db", None)
    if app_db is not None and hasattr(app_db, "get_mini_app_session"):
        try:
            row = await app_db.get_mini_app_session(user_id)
            if isinstance(row, dict):
                row.setdefault("user_id", user_id)
                row.setdefault("recent_tracks", [])
                row.setdefault("preferences", {})
                row["updated_at"] = int(time.time())
                return row
        except Exception:
            pass

    raw = await cache.get(_session_key(user_id))
    if not raw:
        return {"user_id": user_id, "recent_tracks": [], "preferences": {}, "updated_at": int(time.time())}

    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("Session payload is not an object")
    except Exception:
        payload = {"user_id": user_id, "recent_tracks": [], "preferences": {}, "updated_at": int(time.time())}

    payload.setdefault("user_id", user_id)
    payload.setdefault("recent_tracks", [])
    payload.setdefault("preferences", {})
    payload["updated_at"] = int(time.time())
    return payload


async def _save_session(payload: Dict[str, Any]) -> None:
    user_id = int(payload["user_id"])
    app_db = getattr(database_module, "db", None)
    if app_db is not None and hasattr(app_db, "upsert_mini_app_session"):
        try:
            await app_db.upsert_mini_app_session(
                user_id=user_id,
                recent_tracks=payload.get("recent_tracks", []),
                preferences=payload.get("preferences", {}),
                last_chat_id=payload.get("last_chat_id"),
            )
        except Exception:
            pass

    await cache.set(
        _session_key(user_id),
        json.dumps(payload),
        ex=settings.MINI_APP_SESSION_TTL_SECONDS,
    )


@router.get("/me", response_model=SessionState)
async def get_my_session(auth: AuthContext = Depends(require_auth_context)) -> SessionState:
    data = await _load_session(auth.user.id)
    return SessionState.model_validate(data)


@router.post("/me/recent", response_model=SessionState)
async def append_recent_track(track: TrackPayload, auth: AuthContext = Depends(require_auth_context)) -> SessionState:
    data = await _load_session(auth.user.id)
    recent_tracks = data.get("recent_tracks", [])

    track_payload = track.model_dump()
    track_payload["added_at"] = int(time.time())
    dedupe_key = (track_payload.get("track_id") or track_payload.get("id") or track_payload.get("stream_url") or "").strip()

    filtered = []
    for item in recent_tracks:
        key = (item.get("track_id") or item.get("id") or item.get("stream_url") or "").strip()
        if key and key == dedupe_key:
            continue
        filtered.append(item)

    filtered.insert(0, track_payload)
    data["recent_tracks"] = filtered[: settings.MINI_APP_SESSION_MAX_RECENT_TRACKS]
    data["updated_at"] = int(time.time())

    await _save_session(data)
    return SessionState.model_validate(data)


@router.patch("/me/preferences", response_model=SessionState)
async def update_preferences(
    preferences: UserPreferences,
    auth: AuthContext = Depends(require_auth_context),
) -> SessionState:
    data = await _load_session(auth.user.id)
    current = data.get("preferences", {})

    incoming = preferences.model_dump(exclude_none=True)
    current.update(incoming)
    data["preferences"] = current
    data["updated_at"] = int(time.time())

    await _save_session(data)
    return SessionState.model_validate(data)
