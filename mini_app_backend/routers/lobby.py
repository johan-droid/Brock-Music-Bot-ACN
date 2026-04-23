"""Lobby API for shared group listening state."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from mini_app_backend.dependencies import require_auth_context
from mini_app_backend.schemas import AuthContext, LobbyState, QueueAddRequest, SeekRequest, TrackChangeRequest
from mini_app_backend.services.lobby_service import lobby_service


router = APIRouter(prefix="/lobby", tags=["lobby"])


@router.get("/{chat_id}", response_model=LobbyState)
async def get_lobby_state(chat_id: int, auth: AuthContext = Depends(require_auth_context)) -> LobbyState:
    _ = auth
    return await lobby_service.get_state(chat_id)


@router.post("/{chat_id}/queue/add", response_model=LobbyState)
async def add_track_to_lobby_queue(
    chat_id: int,
    request: QueueAddRequest,
    auth: AuthContext = Depends(require_auth_context),
) -> LobbyState:
    return await lobby_service.add_to_queue(
        chat_id=chat_id,
        track=request.track,
        user_id=auth.user.id,
        play_next=request.play_next,
    )


@router.post("/{chat_id}/seek", response_model=LobbyState)
async def seek_lobby(chat_id: int, request: SeekRequest, auth: AuthContext = Depends(require_auth_context)) -> LobbyState:
    _ = auth
    return await lobby_service.seek(chat_id=chat_id, position=request.position)


@router.post("/{chat_id}/track/change", response_model=LobbyState)
async def change_lobby_track(
    chat_id: int,
    request: TrackChangeRequest,
    auth: AuthContext = Depends(require_auth_context),
) -> LobbyState:
    _ = auth
    return await lobby_service.set_now_playing(chat_id=chat_id, track=request.track, position=request.position)

