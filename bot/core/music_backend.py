import asyncio
import logging
import aiohttp
import html
from typing import Optional, Dict, Any, List, TYPE_CHECKING, Awaitable
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
    # Base weights for sources (higher = better)
    # NOTE: `piped` is a fallback-only resolver (used when direct extraction
    # fails). It is not part of the regular search pipeline and therefore
    # should not influence search ranking. Set its weight to 0.0 so it
    # doesn't contribute to SourceRanker priority calculations.
    _BASE_WEIGHTS = {
        "piped": 0.0,
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
        self.piped = None
        # Add request tracking for session rotation
        self._request_count = 0
        self._MAX_REQUESTS_PER_SESSION = 50
        # Session concurrency primitives (initialized on first async call)
        self._session_lock = None  # type: Optional[asyncio.Lock]
        self._active_requests = 0
        self._needs_rotation = False
    
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
            from bot.platforms.piped import piped
            
            self.jiosaavn = jiosaavn
            self.youtube = youtube
            self.soundcloud = soundcloud
            self.ytmusic = ytmusic
            self.audiomack = audiomack
            self.audius = audius
            self.piped = piped
            logger.info("MusicBackend persistent session initialized")

    async def _create_fresh_session(self):
        """Acquire session lock and create a fresh session.

        This wrapper ensures session swaps are atomic. The actual work is
        performed by `_do_create_fresh_session()` so callers that already
        hold the lock can call the inner function directly.
        """
        if self._session_lock is None:
            self._session_lock = asyncio.Lock()
        async with self._session_lock:
            await self._do_create_fresh_session()

    async def _do_create_fresh_session(self):
        """Create/replace the aiohttp session without acquiring the lock.

        This function should only be called while holding `_session_lock`.
        """
        try:
            if self.session:
                try:
                    await self.session.close()
                except Exception:
                    pass
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
        except Exception as e:
            logger.error(f"Failed to create fresh HTTP session: {e}")

    async def _check_session_rotation(self):
        """Check if session needs rotation to avoid stale cache blocks.

        Instead of rotating immediately (which can close the session while
        other coroutines are still using it), mark the session for rotation
        and perform the actual rotation at a safe point when there are no
        active requests.
        """
        self._request_count += 1
        if self._request_count > self._MAX_REQUESTS_PER_SESSION:
            logger.info("Marking session for rotation to prevent provider blocks...")
            self._needs_rotation = True

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

        # Register this coroutine as an active request and check rotation.
        self._active_requests += 1
        # Check for rotation before searching
        await self._check_session_rotation()

        # Determine search order based on query type
        from bot.utils.title_detector import detect_query_type
        query_type = detect_query_type(query)

        # Local extractor references (avoid Optional member access warnings)
        jiosaavn = self.jiosaavn
        soundcloud = self.soundcloud
        audiomack = self.audiomack
        audius = self.audius
        ytmusic = self.ytmusic

        # Build task list with source-specific timeouts
        tasks: List[Awaitable[Any]] = []
        source_order = []

        if jiosaavn and hasattr(jiosaavn, "search"):
            tasks.append(asyncio.wait_for(jiosaavn.search(query, limit), timeout=8))
            source_order.append("jiosaavn")

        if soundcloud and hasattr(soundcloud, "search"):
            tasks.append(asyncio.wait_for(soundcloud.search(query, limit), timeout=12))
            source_order.append("soundcloud")

        if audiomack and hasattr(audiomack, "search"):
            tasks.append(asyncio.wait_for(audiomack.search(query, limit), timeout=10))
            source_order.append("audiomack")

        if audius and hasattr(audius, "search"):
            tasks.append(asyncio.wait_for(audius.search(query, limit), timeout=10))
            source_order.append("audius")

        if ytmusic and hasattr(ytmusic, "search") and query_type.get("western_pop", 0) > 0.6:
            try:
                tasks.append(asyncio.wait_for(ytmusic.search(query, limit), timeout=15))
                source_order.append("ytmusic")
            except Exception:
                # ytmusic might be flaky or unavailable
                pass

        try:
            if not tasks:
                return []

            results = await asyncio.gather(*tasks, return_exceptions=True)

            tracks: List[Track] = []
            source_stats = {s: {"found": 0, "added": 0} for s in source_order}

            for result, source in zip(results, source_order):
                if isinstance(result, BaseException):
                    logger.warning(f"{source} search failed: {result}")
                    SourceRanker.record_failure(source)
                    if source in ("jiosaavn", "soundcloud"):
                        # Defer session rotation to a safe point
                        self._needs_rotation = True
                        logger.debug("Marked session for rotation after current operations due to source failure.")
                    continue

                if not isinstance(result, list):
                    logger.warning(f"{source} search returned unexpected payload type: {type(result).__name__}")
                    SourceRanker.record_failure(source)
                    continue

                SourceRanker.record_success(source)
                try:
                    source_stats[source]["found"] = len(result)
                except Exception:
                    source_stats[source]["found"] = 0

                for item in result:
                    if not isinstance(item, dict):
                        continue
                    try:
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

                        if not is_duplicate_track(track, tracks, threshold=0.85):
                            tracks.append(track)
                            source_stats[source]["added"] += 1
                    except Exception as e:
                        logger.debug(f"Error processing search item for {source}: {e}")
                        continue

            # Log source performance
            for source, stats in source_stats.items():
                if stats["found"] > 0:
                    logger.info(f"{source}: found {stats['found']}, added {stats['added']} (reliability: {SourceRanker.get_reliability(source):.2f})")

            # Rank by quality and source priority
            def rank_key(track: Track):
                quality = calculate_track_quality(track)
                source_priority = SourceRanker.get_source_priority(track.source, query)
                return (source_priority, -quality)

            tracks.sort(key=rank_key)
            result_tracks = tracks[:limit]

            return result_tracks
        finally:
            # Decrement active count and perform deferred rotation if this was the last active request.
            try:
                self._active_requests = max(0, self._active_requests - 1)
            except Exception:
                self._active_requests = 0

            if self._needs_rotation:
                if self._session_lock is None:
                    self._session_lock = asyncio.Lock()
                async with self._session_lock:
                    if self._active_requests == 0 and self._needs_rotation:
                        try:
                            await self._do_create_fresh_session()
                        except Exception as e:
                            logger.error(f"Failed to rotate session: {e}")
                        self._needs_rotation = False

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
        """Resolve a playable URL using the Piped Proxy database to avoid Heroku IP blocks."""
        query = self._build_fallback_query(track)
        if not query:
            return None

        logger.info(f"Attempting unblocked proxy fallback search for: {query}")

        # Prefer the `self.piped` instance initialized by `init()` to avoid repeated imports.
        if not self.piped:
            logger.error("Piped extractor not initialized. Call MusicBackend.init() before using this resolver.")
            return None

        extractor = self.piped
        if not hasattr(extractor, "extract"):
            logger.error("Piped extractor missing `extract` method.")
            return None

        try:
            result = await extractor.extract(query)
            if result and result.get("url"):
                logger.info("✅ Fallback stream successfully resolved via Piped Proxy")
                return result
        except Exception as exc:
            logger.error(f"Piped fallback failed: {exc}")

        logger.error("❌ All fallback proxies failed.")
        return None

    async def get_stream_payload(self, track: Track) -> Optional[Dict[str, Any]]:
        """Resolve stream payload with URL, effective source, and optional headers."""
        if not self.session:
            await self.init()

        source = track.source or "unknown"
        # Local extractor refs to avoid Optional member access issues
        jiosaavn = self.jiosaavn
        audiomack = self.audiomack
        audius = self.audius

        if source == "jiosaavn":
            if not jiosaavn or not hasattr(jiosaavn, "get_stream_url"):
                logger.error("JioSaavn extractor not initialized. Falling back to proxy resolver.")
                return await self._resolve_fallback_payload(track)
            tid = track.track_id or track.get("id")
            encrypted_url = track.stream_url or ""
            if not tid and not encrypted_url:
                logger.error(f"JioSaavn track missing ID and encrypted URL: {track.title}")
                return None
            url = await jiosaavn.get_stream_url(tid or "", encrypted_url)
            if not url:
                return await self._resolve_fallback_payload(track)
            return {"url": url, "source": "jiosaavn", "headers": self.get_source_headers("jiosaavn")}

        if source in ("youtube", "ytmusic"):
            # Skip YouTube extraction (blocked), use fallback directly
            logger.debug(f"Skipping YouTube extraction for: {track.title[:60]}")
            return await self._resolve_fallback_payload(track)

        if source == "soundcloud":
            # Avoid SoundCloud extraction on Heroku; route directly through Piped proxy.
            logger.debug(f"Bypassing SoundCloud extraction for: {track.title[:60]}")
            return await self._resolve_fallback_payload(track)

        if source == "audiomack":
            if not audiomack or not hasattr(audiomack, "extract"):
                logger.debug("Audiomack extractor not initialized; falling back to proxy resolver.")
                return await self._resolve_fallback_payload(track)
            tid = track.track_id or track.get("id") or track.stream_url
            result = await audiomack.extract(tid)
            if result and result.get("url"):
                return {"url": result["url"], "source": "audiomack", "headers": None}
            return await self._resolve_fallback_payload(track)

        if source == "audius":
            if track.stream_url:
                return {"url": track.stream_url, "source": "audius", "headers": None}
            # Ensure the audius extractor is initialized and has an extract() method
            if self.audius and hasattr(self.audius, "extract"):
                if track.track_id:
                    try:
                        result = await self.audius.extract(track.track_id)
                        if result and result.get("url"):
                            return {"url": result["url"], "source": "audius", "headers": None}
                    except Exception as e:
                        logger.warning(f"audius.extract failed: {e}")
            else:
                logger.debug("Audius extractor not initialized; falling back to proxy resolver.")
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
