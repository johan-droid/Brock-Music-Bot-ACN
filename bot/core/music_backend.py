import asyncio
import logging
import re
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

import bot.utils.database as database_module
from bot.utils.circuit_breaker import source_health_tracker
from bot.utils.errors import PreviewOnlyError, SourceExhaustedError, FallbackExhaustedError, BotDetectionError

from bot.utils.multi_tier_cache import multi_cache
logger = logging.getLogger(__name__)

try:
    from bot.platforms.vk import vk_extractor
except Exception as e:
    logger.error(f"Failed to load VK extractor: {e}")
    vk_extractor = None

try:
    from bot.platforms.deezer import deezer_extractor
except Exception as e:
    logger.error(f"Failed to load Deezer extractor: {e}")
    deezer_extractor = None

try:
    from bot.platforms.youtube import youtube_extractor
except Exception as e:
    logger.error(f"Failed to load YouTube extractor: {e}")
    youtube_extractor = None

try:
    from bot.platforms.youtube_wrapper import youtube_wrapper_extractor
except Exception as e:
    logger.error(f"Failed to load YouTube wrapper extractor: {e}")
    youtube_wrapper_extractor = None

try:
    from bot.platforms.jiosaavn import jiosaavn_extractor
except Exception as e:
    logger.error(f"Failed to load JioSaavn extractor: {e}")
    jiosaavn_extractor = None

try:
    from bot.platforms.jiosaavn_wrapper import jiosaavn_wrapper_extractor
except Exception as e:
    logger.error(f"Failed to load JioSaavn wrapper extractor: {e}")
    jiosaavn_wrapper_extractor = None

# Limit the number of concurrent Supabase save requests
_save_semaphore = asyncio.Semaphore(5)
# Keep references to background tasks so they are not garbage-collected
_background_tasks: set = set()
# Max number of pending background tasks before we start dropping them
_MAX_BACKGROUND_TASKS = 25


def _background_task_done(task: asyncio.Task) -> None:
    try:
        exc = task.exception()
        if exc:
            logger.warning("Background task exception: %s", exc, exc_info=True)
    except asyncio.CancelledError:
        pass
    finally:
        try:
            _background_tasks.discard(task)
        except Exception:
            pass


_URL_SCHEME_RX = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://")
_UNSUPPORTED_PAGE_DOMAINS = (
    "youtube.com",
    "youtube-nocookie.com",
    "youtu.be",
    "spotify.com",
    "soundcloud.com",
    # "jiosaavn.com",  # Removed - we have working JioSaavn wrapper with stream extraction
    "audiomack.com",
)


def _looks_like_supported_page_url(value: str) -> bool:
    text = (value or "").strip().lower()
    if not text:
        return False
    return any(domain in text for domain in ("vk.com", "vk.ru", "vkvideo.ru", "deezer.com", "deezer.page.link"))


def _looks_like_unsupported_page_url(value: str) -> bool:
    text = (value or "").strip().lower()
    if not text:
        return False
    return any(domain in text for domain in _UNSUPPORTED_PAGE_DOMAINS)


def _normalize_url_text(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return text
    if _URL_SCHEME_RX.match(text):
        return text
    if text.startswith(("www.", "vk.com", "m.vk.com", "vkvideo.ru", "deezer.com", "deezer.page.link")):
        return f"https://{text}"
    return text


def _normalize_source(value: Optional[str]) -> str:
    return (value or "unknown").strip().lower() or "unknown"


def _infer_source_from_url(value: str) -> str:
    text = _normalize_url_text(value).strip().lower()
    if not text:
        return "direct"
    if text.startswith("vk://"):
        return "vk"
    if text.startswith("deezer://"):
        return "deezer"
    if _looks_like_unsupported_page_url(text):
        return "unsupported"
    if _looks_like_supported_page_url(text):
        if "deezer" in text:
            return "deezer"
        return "vk"
    if text.startswith("http"):
        return "direct"
    return "direct"


def _looks_like_url(value: str) -> bool:
    text = (value or "").strip()
    if not text:
        return False
    if _URL_SCHEME_RX.match(text):
        return True
    return text.startswith((
        "www.",
        "vk.com",
        "m.vk.com",
        "vkvideo.ru",
        "deezer.com",
        "deezer.page.link",
    ))


def _looks_like_page_url(value: str) -> bool:
    source = _infer_source_from_url(value)
    return source in {"vk", "deezer"}


@dataclass
class Track:
    title: str
    artist: str
    duration: int
    stream_url: str
    thumbnail: Optional[str] = None
    source: str = "vk"
    track_id: Optional[str] = None

    def get(self, key: str, default: Any = None) -> Any:
        mapping = {
            "url": "stream_url",
            "uploader": "artist",
            "id": "track_id",
            "thumb": "thumbnail",
        }
        return getattr(self, mapping.get(key, key), default)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data.update(
            {
                "url": self.stream_url,
                "uploader": self.artist,
                "id": self.track_id,
                "thumb": self.thumbnail,
            }
        )
        return data


class SourceRanker:
    """Compatibility ranking helper used by the selection logic in play.py."""

    _BASE_WEIGHTS = {
        # YouTube - BEST (cookies working, no bot detection issues)
        "youtube": 1.0,
        "jiosaavn": 1.2,     # JioSaavn - Good but preview URLs are geo-restricted
        "vk": 1.3,
        "deezer": 1.4,
        "global_index": 1.5,
        "telegram": 2.5,
        "direct": 2.5,
        "unknown": 3.0,
    }
    _health: Dict[str, Dict[str, int]] = {}

    @classmethod
    def record_success(cls, source: str) -> None:
        stats = cls._health.setdefault(_normalize_source(source), {
                                       "success": 0, "fail": 0})
        stats["success"] += 1

    @classmethod
    def record_failure(cls, source: str) -> None:
        stats = cls._health.setdefault(_normalize_source(source), {
                                       "success": 0, "fail": 0})
        stats["fail"] += 1

    @classmethod
    def get_reliability(cls, source: str) -> float:
        stats = cls._health.get(_normalize_source(
            source), {"success": 0, "fail": 0})
        total = stats["success"] + stats["fail"]
        if total == 0:
            return 0.8
        return stats["success"] / total

    @classmethod
    def get_source_priority(cls, source: str, query: str = "") -> int:
        _ = query
        source_name = _normalize_source(source)
        # Lower base weight = better priority (JioSaavn 1.0 beats YouTube 2.0)
        base = cls._BASE_WEIGHTS.get(source_name, cls._BASE_WEIGHTS["unknown"])
        reliability = cls.get_reliability(source_name)
        # Combine base weight with reliability factor
        # Reliability bonus: up to -0.25 reduction for perfect reliability
        reliability_bonus = (1.0 - reliability) * 0.25
        final_score = base - reliability_bonus
        # Return score * 100 for integer precision (lower = better rank)
        return int(final_score * 100)


def calculate_track_quality(track: Track) -> float:
    """Compatibility quality scorer used by the selection logic in play.py."""

    score = 0.0

    if track.duration and track.duration > 0:
        score += 1.0
        if track.duration < 30:
            score -= 0.5

    if track.artist and track.artist.lower() not in ("unknown", "unknown artist", ""):
        score += 0.5

    if track.thumbnail:
        score += 0.3

    if track.track_id:
        score += 0.2

    return score


class MusicBackend:
    """
    YouTube Music primary extractor with VK/Deezer/JioSaavn fallback and database cache.
    Search order: YouTube -> JioSaavn (Indian) -> Deezer -> VK -> Database Index (when PRIORITIZE_EXTRACTORS=True)
                  Database Index -> YouTube -> JioSaavn -> Deezer -> VK (when PRIORITIZE_EXTRACTORS=False)
    YouTube Music works globally; JioSaavn specializes in Indian/Bollywood music.
    """

    @property
    def extractors_map(self):
        return {
            "youtube_wrapper": youtube_wrapper_extractor,
            "youtube": youtube_extractor,
            "jiosaavn_wrapper": jiosaavn_wrapper_extractor,
            "jiosaavn": jiosaavn_extractor,
            "deezer": deezer_extractor,
            "vk": vk_extractor
        }

    async def init(self):
        self._index_misses = 0
        self._index_skip_until = 0.0
        logger.info(
            "MusicBackend initialized (YouTube + JioSaavn Wrapper + Fallback Chain)")
        if not youtube_wrapper_extractor:
            logger.warning(
                "YouTube wrapper not available - falling back to direct YouTube (may fail on Heroku)")
        if not jiosaavn_wrapper_extractor:
            logger.warning(
                "JioSaavn wrapper not available - set JIOSAAVN_API_BASE_URL for Indian music")
        if not jiosaavn_extractor:
            logger.info("JioSaavn direct extractor not available")
        if not deezer_extractor:
            logger.info("Deezer extractor not available")
        if not vk_extractor:
            logger.info("VK extractor not available")

    async def close(self):
        return None

    @staticmethod
    def _normalize_query_key(query: str) -> str:
        return (query or "").strip().lower()

    @staticmethod
    def _extract_metadata(row: Dict[str, Any]) -> Dict[str, Any]:
        metadata = row.get("metadata")
        return metadata if isinstance(metadata, dict) else {}

    @classmethod
    def _row_to_track(cls, row: Dict[str, Any]) -> Optional[Track]:
        if not isinstance(row, dict):
            return None

        title = row.get("title") or "Unknown"
        artist = row.get("artist") or row.get("uploader") or "Unknown Artist"
        metadata = cls._extract_metadata(row)

        duration = metadata.get("duration", row.get("duration", 0)) or 0
        thumbnail = metadata.get("thumbnail") or row.get(
            "thumbnail") or row.get("thumb") or None

        sources = row.get("sources") if isinstance(
            row.get("sources"), list) else []
        track_id = row.get("track_id") or row.get("id")
        stream_url = _normalize_url_text(row.get("stream_url") or metadata.get(
            "stream_url") or row.get("url") or metadata.get("url") or "")
        source = _normalize_source(
            row.get("source") or metadata.get("source") or "global_index")

        if sources:
            first = sources[0] if isinstance(sources[0], dict) else {}
            track_id = track_id or first.get("id") or first.get("track_id")
            source = _normalize_source(first.get("source") or source)
            stream_url = stream_url or _normalize_url_text(
                first.get("stream_url") or first.get("url") or "")

        if not stream_url and track_id:
            if source == "vk":
                stream_url = f"vk://{track_id}"
            elif source == "deezer":
                stream_url = f"deezer://{track_id}"

        if not stream_url:
            return None

        if source == "global_index":
            source = _infer_source_from_url(stream_url)

        if source == "unsupported":
            return None

        if source not in {"vk", "deezer", "telegram", "direct", "unknown"}:
            source = _infer_source_from_url(stream_url)

        if source == "unsupported":
            return None

        return Track(
            title=title,
            artist=artist,
            duration=int(duration),
            stream_url=stream_url,
            thumbnail=thumbnail,
            source=source,
            track_id=str(track_id) if track_id is not None else None,
        )

    @staticmethod
    def _item_to_track(item: Dict[str, Any], default_source: str) -> Optional[Track]:
        if not isinstance(item, dict):
            return None

        source = _normalize_source(
            item.get("source") or default_source or "unknown")
        track_id = item.get("id") or item.get(
            "track_id") or item.get("vk_id") or item.get("deezer_id")
        # For sources with ID-based extraction (JioSaavn, YouTube), only use stream_url if available
        # Don't fall back to 'url' (web page) as that breaks playback
        if source in {"jiosaavn", "youtube"}:
            stream_url = _normalize_url_text(item.get("stream_url") or "")
        else:
            stream_url = _normalize_url_text(
                item.get("stream_url") or item.get("url") or item.get("play_url") or "")

        if not stream_url and track_id:
            if source == "vk":
                stream_url = f"vk://{track_id}"
            elif source == "deezer":
                stream_url = f"deezer://{track_id}"

        # Allow tracks without stream_url for sources that support extraction by ID
        if not stream_url and source not in {"youtube", "jiosaavn"}:
            return None

        if source == "unsupported":
            return None

        # Whitelist known sources to preserve their identity
        if source not in {"youtube", "jiosaavn", "vk", "deezer", "telegram", "direct", "unknown"}:
            source = _infer_source_from_url(stream_url)

        if source == "unsupported":
            return None

        return Track(
            title=item.get("title") or item.get("name") or "Unknown",
            artist=item.get("artist") or item.get(
                "uploader") or item.get("author") or "Unknown Artist",
            duration=int(item.get("duration") or item.get("length") or 0),
            stream_url=stream_url,
            thumbnail=item.get("thumbnail") or item.get("cover") or None,
            source=source,
            track_id=str(track_id) if track_id is not None else None,
        )

    async def _search_index(self, query: str, limit: int) -> List[Track]:
        import time
        if time.time() < self._index_skip_until:
            logger.debug(
                "Skipping unreliable global index (circuit breaker active)")
            return []

        app_db = getattr(database_module, "db", None)
        if app_db is None or not hasattr(app_db, "search_global_music_index"):
            return []

        try:
            rows = await app_db.search_global_music_index(query, limit)
        except Exception as exc:
            logger.warning("Global index lookup failed for %r: %s", query, exc)
            self._index_misses += 1
            if self._index_misses >= 3:
                self._index_skip_until = time.time() + 300
                logger.warning(
                    "Global index circuit breaker triggered! Bypassing for 5 minutes.")
            return []

        tracks: List[Track] = []
        seen: set[str] = set()

        for row in rows or []:
            track = self._row_to_track(row)
            if not track:
                continue

            dedupe_key = (
                track.track_id or track.stream_url or track.title).strip().lower()
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            tracks.append(track)

            if len(tracks) >= limit:
                break

        if tracks:
            logger.info("Global index hit for %r with %s track(s)",
                        query, len(tracks))
            self._index_misses = 0  # Reset miss counter on success
        else:
            self._index_misses += 1
            if self._index_misses >= 3:
                self._index_skip_until = time.time() + 300
                logger.info(
                    "Global index is repeatedly empty; bypassing for 5 minutes.")

        return tracks

    async def _cache_to_index(self, query: str, tracks: List[Track]) -> None:
        """Background task to save track results to the active database index."""
        app_db = getattr(database_module, "db", None)
        if app_db is None or not hasattr(app_db, "save_track_to_index") or not tracks:
            return

        async with _save_semaphore:
            try:
                best_track = tracks[0]
                await app_db.save_track_to_index(self._normalize_query_key(query), best_track.to_dict())
                logger.debug("Cached %r to database index", best_track.title)
            except Exception as exc:
                logger.warning("Failed to cache to database: %s", exc)

    async def _search_with_extractor(self, extractor: Any, query: str, limit: int, default_source: str) -> List[Track]:
        if not extractor or not hasattr(extractor, "search"):
            logger.info(
                "Skipping extractor %s for query=%s because it is unavailable", default_source, query)
            return []

        logger.info("Calling %s extractor for query=%s", default_source, query)
        try:
            raw_results = await extractor.search(query, limit)
        except Exception as exc:
            logger.warning("%s search failed for %r: %s",
                           default_source, query, exc)
            return []

        tracks: List[Track] = []
        for item in raw_results or []:
            track = self._item_to_track(item, default_source)
            if not track:
                continue

            tracks.append(track)
            if len(tracks) >= limit:
                break

        return tracks

    async def search(self, query: str, limit: int = 5) -> List[Track]:
        query = query.strip()
        if not query:
            return []

        cache_key = f"search:{query}:{limit}"
        cached, _ = await multi_cache.get(cache_key)
        if cached:
            return [self._coerce_track(t) for t in cached]

            return []

        from config import config

        sorted_sources = await source_health_tracker.get_sorted_sources()
        if not sorted_sources:
            # Fallback if tracker is empty
            sorted_sources = ["youtube_wrapper", "youtube",
                              "jiosaavn_wrapper", "jiosaavn", "deezer", "vk"]

        tracks = []

        # If parallel search
        if config.PARALLEL_SEARCH:
            tasks = []
            for src_name in sorted_sources:
                extractor = self.extractors_map.get(src_name)
                if extractor and hasattr(extractor, "search"):
                    tasks.append(self._search_with_extractor(
                        extractor, query, limit, src_name))

            if config.PRIORITIZE_EXTRACTORS:
                tasks.append(self._search_index(query, limit))

            results = await asyncio.gather(*tasks, return_exceptions=True)

            combined = []
            seen = set()

            for res in results:
                if isinstance(res, Exception) or not res:
                    continue
                for t in res:
                    norm = re.sub(r'[^a-zA-Z0-9]', '',
                                  f"{t.title}{t.artist}").lower()
                    if norm not in seen:
                        seen.add(norm)
                        combined.append(t)

            tracks = combined[:limit]
        else:
            # Sequential search using health tracker
            if not config.PRIORITIZE_EXTRACTORS:
                tracks = await self._search_index(query, limit)

            if not tracks:
                for src_name in sorted_sources:
                    extractor = self.extractors_map.get(src_name)
                    if extractor and hasattr(extractor, "search"):
                        try:
                            tracks = await self._search_with_extractor(extractor, query, limit, src_name.split("_")[0])
                            if tracks:
                                break
                        except Exception as e:
                            logger.debug(f"Search failed for {src_name}: {e}")

            if not tracks and config.PRIORITIZE_EXTRACTORS:
                tracks = await self._search_index(query, limit)

        if tracks and len(_background_tasks) < _MAX_BACKGROUND_TASKS:
            task = asyncio.create_task(self._save_to_index(tracks))
            _background_tasks.add(task)
            task.add_done_callback(_background_tasks.discard)

        return tracks

    async def get_stream_payload(self, track: Track) -> Optional[Dict[str, Any]]:
        if not track:
            return None

        # Check direct URL
        if track.stream_url and track.stream_url.startswith("http") and _infer_source_from_url(track.stream_url) == "direct":
            return self._build_payload(track, None, "direct")

        resolved = None
        source = track.source or "unknown"

        # Primary source extraction
        if source != "unknown":
            primary_wrapper = f"{source}_wrapper"
            primary_direct = source

            for src_name in [primary_wrapper, primary_direct]:
                extractor = self.extractors_map.get(src_name)
                if extractor and hasattr(extractor, "extract"):
                    try:
                        resolved = await extractor.extract(track.track_id)
                        if resolved:
                            source = src_name.split("_")[0]
                            break
                    except PreviewOnlyError:
                        logger.warning(
                            f"Preview only error from {src_name}, falling back...")
                        resolved = None
                    except BotDetectionError:
                        logger.warning(
                            f"Bot detection error from {src_name}, falling back...")
                        resolved = None
                    except Exception as e:
                        logger.debug(f"Extraction failed for {src_name}: {e}")
                        resolved = None

        # Intelligent Fallback Chain
        if not resolved and track.track_id:
            logger.info(
                f"Primary extraction failed for {track.title}, engaging intelligent fallback...")

            sorted_sources = await source_health_tracker.get_sorted_sources()
            if not sorted_sources:
                sorted_sources = ["youtube_wrapper", "youtube",
                                  "jiosaavn_wrapper", "jiosaavn", "deezer", "vk"]

            for src_name in sorted_sources:
                # Skip what we already tried
                if src_name in [f"{track.source}_wrapper", track.source]:
                    continue

                extractor = self.extractors_map.get(src_name)
                if extractor and hasattr(extractor, "extract"):
                    try:
                        # Attempt to use the same track_id. Note: cross-platform ID matching is rare,
                        # but if an extractor handles standard IDs, it might work. Otherwise, we fallback to search.
                        # Realistically, if track_id is a YT id, Jiosaavn won't resolve it.
                        # We will skip direct extraction and go to search fallback below.
                        pass
                    except Exception:
                        pass

        # FINAL FALLBACK: Search for the track by title across healthy sources
        if not resolved and track.title:
            logger.info(
                f"ID-based extraction failed, trying search fallback for '{track.title}'")
            search_query = f"{track.title} {track.artist}" if track.artist and track.artist != "Unknown Artist" else track.title

            sorted_sources = await source_health_tracker.get_sorted_sources()
            for src_name in sorted_sources:
                extractor = self.extractors_map.get(src_name)
                if extractor and hasattr(extractor, "search") and hasattr(extractor, "extract"):
                    try:
                        search_res = await extractor.search(search_query, limit=1)
                        if search_res:
                            track_id = search_res[0].get("id")
                            if track_id:
                                resolved = await extractor.extract(track_id)
                                if resolved:
                                    logger.info(
                                        f"Fallback search success via {src_name} for {track.title}")
                                    source = src_name.split("_")[0]
                                    break
                    except PreviewOnlyError:
                        logger.warning(
                            f"Preview only error during fallback search on {src_name}")
                        continue
                    except BotDetectionError:
                        logger.warning(
                            f"Bot detection during fallback search on {src_name}")
                        continue
                    except Exception as e:
                        logger.debug(
                            f"Fallback search failed for {src_name}: {e}")
                        continue

        if resolved:
            payload = self._build_payload(track, resolved, source)
            if payload["url"] and not _looks_like_unsupported_page_url(payload["url"]):
                logger.info(
                    f"Successfully resolved stream URL for {track.title} from {source}")
                return payload

        if track.stream_url and track.stream_url.startswith("http") and _infer_source_from_url(track.stream_url) == "direct":
            return self._build_payload(track, None, source or "direct")

        # Raise a user-friendly error if we exhaust all fallbacks
        raise FallbackExhaustedError(
            "Could not find a working stream for this track across all sources.")

    async def _resolve_from_search(self, query: str) -> Optional[Dict[str, Any]]:
        results = await self.search(query, limit=1)
        if not results:
            return None
        return await self.get_stream_payload(results[0])

    async def resolve(self, target: Any) -> Optional[Dict[str, Any]]:
        if isinstance(target, str):
            text = target.strip()
            if not text:
                return None
            if _looks_like_url(text):
                source = _infer_source_from_url(text)
                if source == "unsupported":
                    return None
                return await self.get_stream_payload(self._coerce_track(text))
            return await self._resolve_from_search(text)

        return await self.get_stream_payload(self._coerce_track(target))

    async def _resolve_fallback_payload(self, track: Track) -> Optional[Dict[str, Any]]:
        return await self.get_stream_payload(track)

    async def get_stream_url(self, track: Track) -> Optional[str]:
        payload = await self.get_stream_payload(track)
        if not payload:
            return None
        return payload.get("url") or payload.get("stream_url")


music_backend = MusicBackend()

__all__ = ["Track", "SourceRanker", "calculate_track_quality",
           "MusicBackend", "music_backend"]
