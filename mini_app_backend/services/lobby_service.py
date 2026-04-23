"""Lobby state orchestration backed by existing queue/cache layers."""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional

import bot.utils.database as database_module
from bot.core import queue as queue_module
from bot.utils.cache import cache

from mini_app_backend.schemas import LobbyParticipant, LobbyState, TrackPayload
from mini_app_backend.settings import settings


class LobbyService:
    def _state_key(self, chat_id: int) -> str:
        return f"mini:lobby:{chat_id}"

    def _participants_key(self, chat_id: int) -> str:
        return f"mini:lobby:participants:{chat_id}"

    async def _load_participants(self, chat_id: int) -> List[LobbyParticipant]:
        raw = await cache.get(self._participants_key(chat_id))
        if not raw:
            return []
        try:
            payload = json.loads(raw)
            if not isinstance(payload, list):
                return []
            return [LobbyParticipant.model_validate(item) for item in payload if isinstance(item, dict)]
        except Exception:
            return []

    async def _save_participants(self, chat_id: int, participants: List[LobbyParticipant]) -> None:
        payload = [item.model_dump() for item in participants]
        await cache.set(
            self._participants_key(chat_id),
            json.dumps(payload),
            ex=settings.MINI_APP_LOBBY_STATE_TTL_SECONDS,
        )

    async def get_state(self, chat_id: int) -> LobbyState:
        cached = await cache.get_lobby_state(chat_id)
        if isinstance(cached, dict):
            try:
                return LobbyState.model_validate(cached)
            except Exception:
                pass

        app_db = getattr(database_module, "db", None)
        if app_db is not None and hasattr(app_db, "get_lobby_snapshot"):
            try:
                persisted = await app_db.get_lobby_snapshot(chat_id)
                if isinstance(persisted, dict):
                    persisted_state = LobbyState(
                        chat_id=chat_id,
                        now_playing=persisted.get("now_playing"),
                        queue=persisted.get("queue") if isinstance(persisted.get("queue"), list) else [],
                        position=int(persisted.get("position_seconds") or 0),
                        status=persisted.get("status") or "idle",
                        participants=[
                            LobbyParticipant.model_validate(item)
                            for item in (persisted.get("participants") or [])
                            if isinstance(item, dict)
                        ],
                        version=int(persisted.get("version") or 1),
                        updated_at=int(time.time()),
                    )
                    await self.set_state(chat_id, persisted_state)
                    return persisted_state
            except Exception:
                pass

        queue_manager = queue_module.queue_manager
        now_playing: Optional[Dict[str, Any]] = None
        queue: List[Dict[str, Any]] = []
        position = 0
        status = "idle"

        if queue_manager is not None:
            now_playing = await queue_manager.get_current(chat_id)
            queue = await queue_manager.get_queue(chat_id)
            position = await queue_manager.get_position(chat_id)
            status = await queue_manager.get_status(chat_id)

        state = LobbyState(
            chat_id=chat_id,
            now_playing=now_playing,
            queue=queue,
            position=position,
            status=status,
            participants=await self._load_participants(chat_id),
            version=1,
            updated_at=int(time.time()),
        )
        await self.set_state(chat_id, state)
        return state

    async def set_state(self, chat_id: int, state: LobbyState) -> LobbyState:
        state.updated_at = int(time.time())
        payload = state.model_dump()
        await cache.set_lobby_state(chat_id, payload, ttl=settings.MINI_APP_LOBBY_STATE_TTL_SECONDS)

        app_db = getattr(database_module, "db", None)
        if app_db is not None and hasattr(app_db, "upsert_lobby_snapshot"):
            try:
                await app_db.upsert_lobby_snapshot(
                    chat_id=chat_id,
                    snapshot={
                        "now_playing": payload.get("now_playing"),
                        "queue": payload.get("queue", []),
                        "status": payload.get("status", "idle"),
                        "position_seconds": payload.get("position", 0),
                        "participants": payload.get("participants", []),
                        "version": payload.get("version", 1),
                    },
                )
            except Exception:
                pass
        return state

    async def bump_version(self, chat_id: int, state: LobbyState) -> LobbyState:
        state.version += 1
        return await self.set_state(chat_id, state)

    async def sync_from_queue(self, chat_id: int) -> LobbyState:
        current = await self.get_state(chat_id)
        queue_manager = queue_module.queue_manager
        if queue_manager is None:
            return current

        current.now_playing = await queue_manager.get_current(chat_id)
        current.queue = await queue_manager.get_queue(chat_id)
        current.position = await queue_manager.get_position(chat_id)
        current.status = await queue_manager.get_status(chat_id)
        return await self.bump_version(chat_id, current)

    async def add_to_queue(self, chat_id: int, track: TrackPayload, user_id: int, play_next: bool = False) -> LobbyState:
        queue_manager = queue_module.queue_manager
        if queue_manager is None:
            raise RuntimeError("Queue manager is not initialized")

        payload = track.model_dump()
        title = payload.get("title") or "Unknown"
        duration = int(payload.get("duration") or 0)
        source = payload.get("source") or "unknown"
        track_id = payload.get("track_id") or payload.get("id")
        thumb = payload.get("thumbnail")
        uploader = payload.get("artist") or payload.get("uploader")
        url = payload.get("stream_url") or payload.get("url") or ""

        if play_next:
            await queue_manager.add_to_front(
                chat_id=chat_id,
                title=title,
                url=url,
                duration=duration,
                thumb=thumb,
                requested_by=user_id,
                source=source,
                track_id=track_id,
                uploader=uploader,
            )
        else:
            await queue_manager.add_to_queue(
                chat_id=chat_id,
                title=title,
                url=url,
                duration=duration,
                thumb=thumb,
                requested_by=user_id,
                source=source,
                track_id=track_id,
                uploader=uploader,
            )

        return await self.sync_from_queue(chat_id)

    async def set_now_playing(self, chat_id: int, track: TrackPayload, position: int = 0) -> LobbyState:
        queue_manager = queue_module.queue_manager
        if queue_manager is None:
            raise RuntimeError("Queue manager is not initialized")

        now_playing = track.model_dump()
        now_playing["position"] = max(0, int(position))
        await cache.set(queue_manager._playing_key(chat_id), json.dumps(now_playing))
        await queue_manager.update_position(chat_id, now_playing["position"])
        await queue_manager.set_status(chat_id, "playing")
        return await self.sync_from_queue(chat_id)

    async def seek(self, chat_id: int, position: int) -> LobbyState:
        queue_manager = queue_module.queue_manager
        if queue_manager is None:
            raise RuntimeError("Queue manager is not initialized")
        await queue_manager.update_position(chat_id, max(0, int(position)))
        return await self.sync_from_queue(chat_id)

    async def join_participant(self, chat_id: int, participant: LobbyParticipant) -> LobbyState:
        state = await self.get_state(chat_id)
        participants = [p for p in state.participants if p.user_id != participant.user_id]
        participants.append(participant)
        state.participants = participants
        await self._save_participants(chat_id, participants)
        return await self.bump_version(chat_id, state)

    async def leave_participant(self, chat_id: int, user_id: int) -> LobbyState:
        state = await self.get_state(chat_id)
        state.participants = [p for p in state.participants if p.user_id != user_id]
        await self._save_participants(chat_id, state.participants)
        return await self.bump_version(chat_id, state)


lobby_service = LobbyService()
