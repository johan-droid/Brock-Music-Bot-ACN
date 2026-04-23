"""Pydantic schemas for mini app API and socket contracts."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class TelegramUser(BaseModel):
    id: int
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    language_code: Optional[str] = None
    is_premium: Optional[bool] = None


class AuthContext(BaseModel):
    user: TelegramUser
    query_id: Optional[str] = None
    auth_date: int
    chat_type: Optional[str] = None
    chat_instance: Optional[str] = None
    raw_init_data: str


class TrackPayload(BaseModel):
    title: str = "Unknown"
    artist: str = "Unknown Artist"
    duration: int = 0
    source: str = "unknown"
    track_id: Optional[str] = None
    url: Optional[str] = None
    stream_url: Optional[str] = None
    thumbnail: Optional[str] = None
    uploader: Optional[str] = None
    id: Optional[str] = None


class SearchResponse(BaseModel):
    query: str
    limit: int
    count: int
    items: List[Dict[str, Any]]


class LobbyParticipant(BaseModel):
    user_id: int
    username: Optional[str] = None
    first_name: Optional[str] = None
    is_admin: bool = False


class LobbyState(BaseModel):
    chat_id: int
    now_playing: Optional[Dict[str, Any]] = None
    queue: List[Dict[str, Any]] = Field(default_factory=list)
    position: int = 0
    status: str = "idle"
    participants: List[LobbyParticipant] = Field(default_factory=list)
    version: int = 1
    updated_at: int


class QueueAddRequest(BaseModel):
    track: TrackPayload
    play_next: bool = False


class SeekRequest(BaseModel):
    position: int = Field(..., ge=0)


class TrackChangeRequest(BaseModel):
    track: TrackPayload
    position: int = Field(default=0, ge=0)


class UserPreferences(BaseModel):
    autoplay: Optional[bool] = None
    visualizer_enabled: Optional[bool] = None
    theme: Optional[str] = None
    equalizer_preset: Optional[str] = None


class SessionState(BaseModel):
    user_id: int
    recent_tracks: List[Dict[str, Any]] = Field(default_factory=list)
    preferences: Dict[str, Any] = Field(default_factory=dict)
    updated_at: int

