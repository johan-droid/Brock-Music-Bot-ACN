import asyncio
import logging
import aiohttp
import html
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)


@dataclass
class Track:
    """Universal track representation."""
    title: str
    artist: str
    duration: int  # seconds
    stream_url: str
    thumbnail: Optional[str] = None
    source: str = "unknown"  # jiosaavn, youtube, soundcloud
    track_id: Optional[str] = None

    def get(self, key: str, default: Any = None) -> Any:
        # Map common dict keys to attributes
        mapping = {
            "url": "stream_url",
            "uploader": "artist",
            "id": "track_id",
            "thumb": "thumbnail"
        }
        attr = mapping.get(key, key)
        return getattr(self, attr, default)

    def to_dict(self) -> Dict[str, Any]:
        """Convert Track to dictionary."""
        d = asdict(self)
        # Compatibility keys
        d["url"] = self.stream_url
        d["uploader"] = self.artist
        d["id"] = self.track_id
        d["thumb"] = self.thumbnail
        return d


# JioSaavnExtractor is now imported from bot.platforms.jiosaavn


class MusicBackend:
    """
    Unified music backend that tries multiple sources.
    Priority: JioSaavn (legal) → YouTube (fair use) → SoundCloud
    """
    
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
        self.jiosaavn: Optional[JioSaavnExtractor] = None
        self.youtube = None
        self.soundcloud = None
    
    async def init(self):
        """Initialize the shared HTTP session and platform extractors."""
        if not self.session:
            self.session = aiohttp.ClientSession(
                headers={"User-Agent": "Mozilla/5.0 (compatible; SoulKing/1.0; +https://github.com/johan-droid/Music-Bot)"}
            )
            from bot.platforms.jiosaavn import jiosaavn
            self.jiosaavn = jiosaavn
            
            # YouTube and SoundCloud extractors are already in bot/platforms/
            from bot.platforms.youtube import youtube
            from bot.platforms.soundcloud import soundcloud
            self.youtube = youtube
            self.soundcloud = soundcloud
            logger.info("MusicBackend persistent session initialized")

    async def close(self):
        """Gracefully close the HTTP session."""
        if self.session:
            await self.session.close()
            self.session = None
            logger.info("MusicBackend session closed")
    
    async def search(self, query: str, limit: int = 5) -> List[Track]:
        """
        Search across all sources in parallel.
        Returns unified Track objects.
        """
        if not self.session:
            await self.init()

        # Run all searches in parallel for maximum efficiency
        tasks = [
            self.jiosaavn.search(query, limit),
            self.youtube.search(query, limit),
            self.soundcloud.search(query, limit)
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        tracks = []
        
        # 1. Process JioSaavn results
        if not isinstance(results[0], Exception):
            tracks.extend(results[0])
            logger.info(f"JioSaavn found {len(results[0])} tracks")
            
        # 2. Process YouTube results
        if not isinstance(results[1], Exception):
            yt_results = results[1]
            for result in yt_results:
                track = Track(
                    title=result.get("title", "Unknown"),
                    artist=result.get("uploader", "Unknown"),
                    duration=result.get("duration", 0),
                    stream_url=result.get("url", ""),
                    thumbnail=result.get("thumbnail"),
                    source="youtube",
                    track_id=result.get("id")
                )
                # Avoid duplicates
                if not any(t.title.lower() == track.title.lower() for t in tracks):
                    tracks.append(track)
            logger.info(f"YouTube found {len(yt_results)} tracks")

        # 3. Process SoundCloud results
        if not isinstance(results[2], Exception) and len(tracks) < limit * 2:
            sc_results = results[2]
            for result in sc_results:
                track = Track(
                    title=result.get("title", "Unknown"),
                    artist=result.get("artist", "Unknown"),
                    duration=result.get("duration", 0),
                    stream_url=result.get("stream_url", ""),
                    thumbnail=result.get("thumbnail"),
                    source="soundcloud",
                    track_id=result.get("id")
                )
                if not any(t.title.lower() == track.title.lower() for t in tracks):
                    tracks.append(track)
            logger.info(f"SoundCloud found {len(sc_results)} tracks")
        
        return tracks[:limit]
    
    async def get_stream_url(self, track: Track) -> Optional[str]:
        """Resolve stream URL for a track based on its source."""
        if not self.session:
            await self.init()

        if track.source == "jiosaavn":
            tid = track.track_id or track.get("id")
            # stream_url holds the encrypted_media_url captured during search
            encrypted_url = track.stream_url or ""
            if not tid and not encrypted_url:
                logger.error(f"JioSaavn track missing ID and encrypted URL: {track.title}")
                return None
            return await self.jiosaavn.get_stream_url(tid or "", encrypted_url)
        elif track.source == "youtube":
            tid = track.track_id or track.get("id") or track.stream_url
            result = await self.youtube.extract(tid)
            return result.get("url") if result else None
        elif track.source == "soundcloud":
            return track.stream_url if track.stream_url else None
        return None


# Global instance
music_backend = MusicBackend()
