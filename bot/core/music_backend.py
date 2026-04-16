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


class SourceRanker:
    """
    Dynamic source prioritization based on query type and source health.
    """
    
    # Base weights for sources (higher = better)
    _BASE_WEIGHTS = {
        "soundcloud": 1.0,
        "audiomack": 0.95,
        "audius": 0.90,
        "ytmusic": 0.5,
        "youtube": 0.4,
        "jiosaavn": 0.4,
        "spotify": 0.8,
    }
    
    # Health tracking: source -> {success: int, fail: int}
    _health: Dict[str, Dict[str, int]] = {}
    
    @classmethod
    def record_success(cls, source: str) -> None:
        """Record a successful extraction from a source."""
        if source not in cls._health:
            cls._health[source] = {"success": 0, "fail": 0}
        cls._health[source]["success"] += 1
    
    @classmethod
    def record_failure(cls, source: str) -> None:
        """Record a failed extraction from a source."""
        if source not in cls._health:
            cls._health[source] = {"success": 0, "fail": 0}
        cls._health[source]["fail"] += 1
    
    @classmethod
    def get_reliability(cls, source: str) -> float:
        """Get reliability score (0.0 - 1.0) for a source."""
        stats = cls._health.get(source, {})
        total = stats.get("success", 0) + stats.get("fail", 0)
        if total < 5:  # Not enough data
            return 0.8  # Neutral
        return stats["success"] / total
    
    @classmethod
    def get_source_priority(cls, source: str, query: str = "") -> int:
        """
        Get priority rank for a source (lower = higher priority).
        Combines base weights, query-type adjustments, and health penalties.
        """
        from bot.utils.title_detector import get_source_weights_for_query
        
        # Get dynamic weights based on query type
        dynamic_weights = get_source_weights_for_query(query)
        
        # Get base weight or default
        base_weight = cls._BASE_WEIGHTS.get(source, 0.5)
        
        # Apply dynamic weight adjustment
        dynamic_weight = dynamic_weights.get(source, base_weight)
        
        # Blend base and dynamic (70% dynamic, 30% base)
        weight = (dynamic_weight * 0.7) + (base_weight * 0.3)
        
        # Apply health penalty if source is unreliable
        reliability = cls.get_reliability(source)
        if reliability < 0.5:
            # Unreliable source gets +10 priority penalty
            weight *= 0.5
        
        # Convert weight to priority rank (inverse relationship)
        # Higher weight = lower rank number = higher priority
        priority = int((1.0 - weight) * 100)
        
        return priority


def calculate_track_quality(track: Track) -> float:
    """
    Calculate quality score (0.0 - 2.0) for a track.
    Higher quality = more complete metadata.
    """
    score = 0.0
    
    # Duration present (+1.0)
    if track.duration and track.duration > 0:
        score += 1.0
        # Penalize very short tracks (likely previews/snippets)
        if track.duration < 30:
            score -= 0.5
    
    # Artist known (+0.5)
    if track.artist and track.artist.lower() not in ("unknown", "unknown artist", ""):
        score += 0.5
    
    # Thumbnail present (+0.3)
    if track.thumbnail:
        score += 0.3
    
    # Track ID present (+0.2) - indicates stable identifier
    if track.track_id:
        score += 0.2
    
    return score


def is_duplicate_track(new_track: Track, existing_tracks: List[Track], threshold: float = 0.85) -> bool:
    """
    Fuzzy deduplication using title, artist, and duration tolerance.
    
    Studio versions, live versions, and extended mixes are NOT treated as duplicates
    even if titles/artists match, because their durations differ significantly.
    
    Duration tolerance: Tracks must be within 15 seconds to be considered duplicates.
    (Allows for padding differences between Spotify and YouTube, etc.)
    """
    from bot.utils.title_detector import calculate_similarity
    
    new_title = new_track.title or ""
    new_artist = new_track.artist or ""
    new_duration = new_track.duration or 0
    
    for existing in existing_tracks:
        existing_title = existing.title or ""
        existing_artist = existing.artist or ""
        existing_duration = existing.duration or 0
        
        # Title similarity (70% weight)
        title_sim = calculate_similarity(new_title, existing_title)
        
        # Artist similarity (30% weight)
        artist_sim = calculate_similarity(new_artist, existing_artist) if new_artist and existing_artist else 0.0
        
        # Combined similarity
        combined_sim = (title_sim * 0.7) + (artist_sim * 0.3)
        
        if combined_sim >= threshold:
            # NEW: Only treat as duplicate if durations are within 15 seconds
            # This prevents studio/live/extended mix confusion
            duration_diff = abs(new_duration - existing_duration)
            
            if duration_diff <= 15:
                # Same song (titles match + durations match)
                # Keep the higher quality track
                new_quality = calculate_track_quality(new_track)
                existing_quality = calculate_track_quality(existing)
                
                if new_quality > existing_quality:
                    # Replace lower quality with higher quality
                    existing_tracks.remove(existing)
                    return False  # Not a duplicate (we want to keep this better one)
                return True  # Duplicate found
            # else: titles match but durations differ significantly -> not a duplicate
    
    return False


class MusicBackend:
    """
    Unified music backend that tries multiple sources.
    Priority: JioSaavn → SoundCloud → YT Music → YouTube → Audiomack
    (JioSaavn prioritized for stability on free tier)
    """
    
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
        self.jiosaavn: Optional[JioSaavnExtractor] = None
        self.youtube = None
        self.soundcloud = None
        self.ytmusic = None
        self.audiomack = None
        self.audius = None
        # Add request tracking for session rotation
        self._request_count = 0
        self._MAX_REQUESTS_PER_SESSION = 50
    
    async def init(self):
        """Initialize the shared HTTP session and platform extractors."""
        if not self.session:
            await self._create_fresh_session()
            from bot.platforms.jiosaavn import jiosaavn
            from bot.platforms.youtube import youtube
            from bot.platforms.soundcloud import soundcloud
            from bot.platforms.ytmusic import ytmusic
            from bot.platforms.audiomack import audiomack
            from bot.platforms.audius import audius
            
            self.jiosaavn = jiosaavn
            self.youtube = youtube
            self.soundcloud = soundcloud
            self.ytmusic = ytmusic
            self.audiomack = audiomack
            self.audius = audius
            logger.info("MusicBackend persistent session initialized")

    async def _create_fresh_session(self):
        """Helper to create a fresh session to bypass provider cache blocks."""
        if self.session:
            await self.session.close()
        self.session = aiohttp.ClientSession(
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
            }
        )
        self._request_count = 0
        logger.info("Created a fresh HTTP session for MusicBackend")

    async def _check_session_rotation(self):
        """Check if session needs rotation to avoid stale cache blocks."""
        self._request_count += 1
        if self._request_count > self._MAX_REQUESTS_PER_SESSION:
            logger.info("Rotating HTTP session to prevent provider blocks...")
            await self._create_fresh_session()

    async def close(self):
        """Gracefully close the HTTP session."""
        if self.session:
            await self.session.close()
            self.session = None
            logger.info("MusicBackend session closed")
    
    async def search(self, query: str, limit: int = 5) -> List[Track]:
        """
        Search across all sources in parallel with dynamic prioritization.
        Returns unified Track objects ranked by quality and relevance.
        """
        if not self.session:
            await self.init()

        # Check for rotation before searching
        await self._check_session_rotation()

        # Determine search order based on query type
        from bot.utils.title_detector import detect_query_type
        query_type = detect_query_type(query)
        
        # Build task list with source-specific timeouts
        tasks = []
        source_order = []
        
        # JioSaavn: Fast, reliable for Indian music
        tasks.append(asyncio.wait_for(self.jiosaavn.search(query, limit), timeout=8))
        source_order.append("jiosaavn")
        
        # SoundCloud: Good for electronic/remixes
        tasks.append(asyncio.wait_for(self.soundcloud.search(query, limit), timeout=12))
        source_order.append("soundcloud")
        
        # Audiomack: Good for hip-hop
        tasks.append(asyncio.wait_for(self.audiomack.search(query, limit), timeout=10))
        source_order.append("audiomack")

        # Audius: decentralized open-source catalog
        if self.audius:
            tasks.append(asyncio.wait_for(self.audius.search(query, limit), timeout=10))
            source_order.append("audius")
        
        # YouTube Music: Best for official western releases
        if self.ytmusic and query_type.get("western_pop", 0) > 0.6:
            try:
                tasks.append(asyncio.wait_for(self.ytmusic.search(query, limit), timeout=15))
                source_order.append("ytmusic")
            except Exception:
                pass  # ytmusic might not be available
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        tracks = []
        source_stats = {source: {"found": 0, "added": 0} for source in source_order}
        
        for idx, (result, source) in enumerate(zip(results, source_order)):
            if isinstance(result, Exception):
                logger.warning(f"{source} search failed: {result}")
                SourceRanker.record_failure(source)
                if source in ("jiosaavn", "soundcloud"):
                    asyncio.create_task(self._create_fresh_session())
                continue
            
            SourceRanker.record_success(source)
            source_stats[source]["found"] = len(result)
            
            for item in result:
                # Create Track object
                if source == "jiosaavn":
                    track = Track(
                        title=item.get("title", "Unknown"),
                        artist=item.get("uploader", "Unknown Artist"),
                        duration=item.get("duration", 0),
                        stream_url=item.get("url", ""),
                        thumbnail=item.get("thumbnail"),
                        source="jiosaavn",
                        track_id=item.get("id")
                    )
                elif source == "soundcloud":
                    track = Track(
                        title=item.get("title", "Unknown"),
                        artist=item.get("artist", "Unknown"),
                        duration=item.get("duration", 0),
                        stream_url=item.get("stream_url", ""),
                        thumbnail=item.get("thumbnail"),
                        source="soundcloud",
                        track_id=item.get("id")
                    )
                elif source == "audiomack":
                    track = Track(
                        title=item.get("title", "Unknown"),
                        artist=item.get("uploader", "Unknown Artist"),
                        duration=item.get("duration", 0),
                        stream_url=item.get("url", ""),
                        thumbnail=item.get("thumbnail"),
                        source="audiomack",
                        track_id=item.get("id")
                    )
                elif source == "ytmusic":
                    track = Track(
                        title=item.get("title", "Unknown"),
                        artist=item.get("artist", "Unknown Artist"),
                        duration=item.get("duration", 0),
                        stream_url=item.get("url", ""),
                        thumbnail=item.get("thumbnail"),
                        source="ytmusic",
                        track_id=item.get("id")
                    )
                elif source == "audius":
                    track = Track(
                        title=item.get("title", "Unknown"),
                        artist=item.get("artist", "Unknown Artist"),
                        duration=item.get("duration", 0),
                        stream_url=item.get("url", ""),
                        thumbnail=item.get("thumbnail"),
                        source="audius",
                        track_id=item.get("id")
                    )
                else:
                    continue
                
                # Fuzzy deduplication - check for similar tracks
                if not is_duplicate_track(track, tracks, threshold=0.85):
                    tracks.append(track)
                    source_stats[source]["added"] += 1
        
        # Log source performance
        for source, stats in source_stats.items():
            if stats["found"] > 0:
                logger.info(f"{source}: found {stats['found']}, added {stats['added']} (reliability: {SourceRanker.get_reliability(source):.2f})")
        
        # Rank by quality and source priority
        def rank_key(track):
            quality = calculate_track_quality(track)
            source_priority = SourceRanker.get_source_priority(track.source, query)
            return (source_priority, -quality)
        
        tracks.sort(key=rank_key)
        
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

        # Prioritize Heroku-friendly sources first to avoid JioSaavn IP blocking.
        fallback_chain = [
            ("soundcloud", self.soundcloud.extract),
            ("audiomack", self.audiomack.extract),
            ("audius", self.audius.extract),
            ("ytmusic", self.ytmusic.extract),
            ("jiosaavn", self.jiosaavn.extract),
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

        if source in ("youtube", "ytmusic"):
            # Skip YouTube extraction (blocked), use fallback directly
            logger.debug(f"Skipping YouTube extraction for: {track.title[:60]}")
            return await self._resolve_fallback_payload(track)

        if source == "soundcloud":
            if track.stream_url:
                result = await self.soundcloud.extract(track.stream_url)
                if result and result.get("url"):
                    return {
                        "url": result["url"],
                        "source": "soundcloud",
                        "headers": None,
                    }
            return await self._resolve_fallback_payload(track)

        if source == "audiomack":
            tid = track.track_id or track.get("id") or track.stream_url
            result = await self.audiomack.extract(tid)
            if result and result.get("url"):
                return {"url": result["url"], "source": "audiomack", "headers": None}
            return await self._resolve_fallback_payload(track)

        if source == "audius":
            if track.stream_url:
                return {"url": track.stream_url, "source": "audius", "headers": None}
            if track.track_id:
                result = await self.audius.extract(track.track_id)
                if result and result.get("url"):
                    return {"url": result["url"], "source": "audius", "headers": None}
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
