"""Adapter around the existing shared MusicBackend."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from bot.core.music_backend import music_backend


class MiniAppMusicService:
    async def start(self) -> None:
        await music_backend.init()

    async def close(self) -> None:
        await music_backend.close()

    async def search(self, query: str, limit: int = 20) -> List[Dict[str, Any]]:
        tracks = await music_backend.search(query=query, limit=limit)
        return [track.to_dict() for track in tracks]

    async def resolve(self, track: Any) -> Optional[Dict[str, Any]]:
        return await music_backend.get_stream_payload(track)


music_service = MiniAppMusicService()

