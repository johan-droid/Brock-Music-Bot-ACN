import logging
import asyncio
from typing import List, Dict, Any, Optional
from config import config

from bot.core.jamendo_client import jamendo_client

logger = logging.getLogger(__name__)

class Track:
    title: str
    artist: str
    duration: int
    stream_url: str
    thumbnail: Optional[str] = None
    source: str = "jamendo"
    track_id: Optional[str] = None

    def __init__(self, **kwargs):
        self.title = kwargs.get("title", "Unknown Title")
        self.artist = kwargs.get("artist", "Unknown Artist")
        self.duration = kwargs.get("duration", 0)
        self.stream_url = kwargs.get("stream_url", "")
        self.thumbnail = kwargs.get("thumbnail")
        self.source = kwargs.get("source", "jamendo")
        self.track_id = kwargs.get("track_id") or kwargs.get("id")

    def get(self, key: str, default: Any = None) -> Any:
        mapping = {
            "url": "stream_url",
            "uploader": "artist",
            "id": "track_id",
            "thumb": "thumbnail",
        }
        actual_key = mapping.get(key, key)
        return getattr(self, actual_key, default)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "artist": self.artist,
            "duration": self.duration,
            "stream_url": self.stream_url,
            "url": self.stream_url,
            "thumbnail": self.thumbnail,
            "source": self.source,
            "track_id": self.track_id,
            "id": self.track_id,
        }

class MusicBackend:
    """
    Jamendo Music API primary extractor with database cache.
    """
    def __init__(self):
        pass

    async def init(self):
        logger.info("Music backend initialized (Jamendo)")

    async def search(self, query: str, limit: int = 5) -> List[Track]:
        query = query.strip()
        if not query:
            return []

        results = await jamendo_client.search_tracks(query, limit=limit)
        tracks = []
        for res in results:
            tracks.append(Track(**res))
        return tracks

    async def get_stream_payload(self, track: Track) -> Optional[Dict[str, Any]]:
        """Return the direct stream url from Jamendo."""
        if not track or not track.stream_url:
            return None

        return {
            "id": track.track_id,
            "title": track.title,
            "artist": track.artist,
            "duration": track.duration,
            "url": track.stream_url,
            "stream_url": track.stream_url,
            "thumbnail": track.thumbnail,
            "source": track.source,
            "headers": None
        }

    async def resolve(self, target: Any) -> Optional[Dict[str, Any]]:
        if isinstance(target, str):
            text = target.strip()
            if not text:
                return None
            results = await self.search(text, limit=1)
            if not results:
                return None
            return await self.get_stream_payload(results[0])
        return await self.get_stream_payload(self._coerce_track(target))

    async def get_stream_url(self, track: Track) -> Optional[str]:
        payload = await self.get_stream_payload(track)
        if not payload:
            return None
        return payload.get("url") or payload.get("stream_url")

    def get_source_headers(self, source: str) -> Optional[Dict[str, str]]:
        return None

    def _coerce_track(self, target: Any) -> Track:
        if isinstance(target, Track):
            return target
        if isinstance(target, str):
            return Track(title="Direct Link", artist="Unknown", duration=0, stream_url=target)
        if isinstance(target, dict):
            return Track(**target)
        return Track(title="Unknown", artist="Unknown", duration=0, stream_url="")

music_backend = MusicBackend()

__all__ = ["Track", "MusicBackend", "music_backend"]
