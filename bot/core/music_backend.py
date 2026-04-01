import asyncio
import logging
import aiohttp
import html
from typing import Optional, Dict, Any, List, TYPE_CHECKING
from dataclasses import dataclass, asdict

if TYPE_CHECKING:
    from bot.platforms.jiosaavn import JioSaavnExtractor

logger = logging.getLogger(__name__)


@dataclass
class Track:
    """Universal track representation."""
    title: str
    artist: str
    duration: int  # seconds
    stream_url: str
    thumbnail: Optional[str] = None
    source: str = "unknown"  # jiosaavn, youtube, soundcloud, ytmusic, audiomack
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
    Priority: YT Music → YouTube → JioSaavn → SoundCloud → Audiomack
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
            from bot.platforms.ytmusic import ytmusic
            from bot.platforms.audiomack import audiomack
            
            self.youtube = youtube
            self.soundcloud = soundcloud
            self.ytmusic = ytmusic
            self.audiomack = audiomack
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
            self.ytmusic.search(query, limit),
            self.youtube.search(query, limit),
            self.jiosaavn.search(query, limit),
            self.soundcloud.search(query, limit),
            self.audiomack.search(query, limit),
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        tracks = []
        
        # 1. Process YT Music results (user requested primary priority)
        if not isinstance(results[0], Exception):
            ytm_results = results[0]
            for result in ytm_results:
                track = Track(
                    title=result.get("title", "Unknown"),
                    artist=result.get("uploader", "Unknown Artist"),
                    duration=result.get("duration", 0),
                    stream_url=result.get("url", ""),
                    thumbnail=result.get("thumbnail"),
                    source="ytmusic",
                    track_id=result.get("id")
                )
                if not any(t.title.lower() == track.title.lower() for t in tracks):
                    tracks.append(track)
            logger.info(f"YT Music found {len(ytm_results)} tracks")

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
                if not any(t.title.lower() == track.title.lower() for t in tracks):
                    tracks.append(track)
            logger.info(f"YouTube found {len(yt_results)} tracks")

        # 3. Process JioSaavn results
        if not isinstance(results[2], Exception):
            js_results = results[2]
            for result in js_results:
                track = Track(
                    title=result.get("title", "Unknown"),
                    artist=result.get("uploader", "Unknown Artist"),
                    duration=result.get("duration", 0),
                    stream_url=result.get("url", ""),
                    thumbnail=result.get("thumbnail"),
                    source="jiosaavn",
                    track_id=result.get("id")
                )
                if not any(t.title.lower() == track.title.lower() for t in tracks):
                    tracks.append(track)
            logger.info(f"JioSaavn found {len(js_results)} tracks")

        # 4. Process SoundCloud results
        if not isinstance(results[3], Exception):
            sc_results = results[3]
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

        # 5. Process Audiomack results
        if not isinstance(results[4], Exception):
            am_results = results[4]
            for result in am_results:
                track = Track(
                    title=result.get("title", "Unknown"),
                    artist=result.get("uploader", "Unknown Artist"),
                    duration=result.get("duration", 0),
                    stream_url=result.get("url", ""),
                    thumbnail=result.get("thumbnail"),
                    source="audiomack",
                    track_id=result.get("id")
                )
                if not any(t.title.lower() == track.title.lower() for t in tracks):
                    tracks.append(track)
            logger.info(f"Audiomack found {len(am_results)} tracks")
        
        return tracks[:limit]

    @staticmethod
    def _build_fallback_query(track: Track) -> str:
        """Build a robust text query for cross-platform fallback extraction."""
        title = (track.title or "").strip()
        artist = (track.artist or "").strip()
        if title and artist and artist.lower() not in ("unknown", "unknown artist"):
            return f"{artist} - {title}"
        return title or artist

    @staticmethod
    def get_source_headers(source: str) -> Optional[Dict[str, str]]:
        """Return source-specific headers required for stable CDN playback."""
        if source == "jiosaavn":
            return {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Referer": "https://www.jiosaavn.com/",
            }
        return None

    async def _resolve_fallback_payload(self, track: Track) -> Optional[Dict[str, Any]]:
        """Resolve a playable URL from non-YouTube sources when primary extraction fails."""
        query = self._build_fallback_query(track)
        if not query:
            return None

        # Legal/high-quality first to stay policy-safe and avoid repeated YT anti-bot hits.
        fallback_chain = [
            ("ytmusic", self.ytmusic.extract),
            ("jiosaavn", self.jiosaavn.extract),
            ("soundcloud", self.soundcloud.extract),
            ("audiomack", self.audiomack.extract),
        ]

        for source_name, resolver in fallback_chain:
            try:
                result = await resolver(query)
            except Exception as exc:
                logger.debug(f"Fallback resolver error [{source_name}] for '{query}': {exc}")
                continue

            if result and result.get("url"):
                headers = self.get_source_headers(source_name)
                logger.info(f"Fallback stream resolved via {source_name}: {track.title[:60]}")
                return {
                    "url": result["url"],
                    "source": source_name,
                    "headers": headers,
                }

        return None

    async def get_stream_payload(self, track: Track) -> Optional[Dict[str, Any]]:
        """Resolve stream payload with URL, effective source, and optional headers."""
        if not self.session:
            await self.init()

        source = track.source or "unknown"

        if source == "jiosaavn":
            tid = track.track_id or track.get("id")
            encrypted_url = track.stream_url or ""
            if not tid and not encrypted_url:
                logger.error(f"JioSaavn track missing ID and encrypted URL: {track.title}")
                return None
            url = await self.jiosaavn.get_stream_url(tid or "", encrypted_url)
            if not url:
                return await self._resolve_fallback_payload(track)
            return {"url": url, "source": "jiosaavn", "headers": self.get_source_headers("jiosaavn")}

        if source == "youtube":
            tid = track.track_id or track.get("id") or track.stream_url
            result = await self.youtube.extract(tid)
            if result and result.get("url"):
                return {"url": result["url"], "source": "youtube", "headers": None}

            logger.warning(f"YouTube extraction blocked/failed, attempting fallback: {track.title[:60]}")
            return await self._resolve_fallback_payload(track)

        if source == "ytmusic":
            tid = track.track_id or track.get("id") or track.stream_url
            result = await self.ytmusic.extract(tid)
            if result and result.get("url"):
                return {"url": result["url"], "source": "ytmusic", "headers": None}

            logger.warning(f"YT Music extraction failed, attempting fallback: {track.title[:60]}")
            return await self._resolve_fallback_payload(track)

        if source == "soundcloud":
            if track.stream_url:
                return {"url": track.stream_url, "source": "soundcloud", "headers": None}
            return await self._resolve_fallback_payload(track)

        if source == "audiomack":
            tid = track.track_id or track.get("id") or track.stream_url
            result = await self.audiomack.extract(tid)
            if result and result.get("url"):
                return {"url": result["url"], "source": "audiomack", "headers": None}
            return await self._resolve_fallback_payload(track)

        # Unknown source: try existing URL first, then legal-first fallback.
        if track.stream_url:
            return {"url": track.stream_url, "source": source, "headers": self.get_source_headers(source)}
        return await self._resolve_fallback_payload(track)
    
    async def get_stream_url(self, track: Track) -> Optional[str]:
        """Backward-compatible URL-only resolver."""
        payload = await self.get_stream_payload(track)
        return payload.get("url") if payload else None


# Global instance
music_backend = MusicBackend()
