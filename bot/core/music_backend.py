"""Unified music backend that relies on remote microservice endpoints."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

import bot.utils.database as database_module
from bot.core.microservice_client import MusicMicroserviceClient
from bot.utils.circuit_breaker import source_health_tracker
from bot.utils.errors import FallbackExhaustedError
from bot.utils.title_detector import build_title_routing_hints

logger = logging.getLogger(__name__)

_save_semaphore = asyncio.Semaphore(5)
_background_tasks: set[asyncio.Task] = set()
_MAX_BACKGROUND_TASKS = 25

_URL_SCHEME_RX = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://")
_UNSUPPORTED_PAGE_DOMAINS = (
    "youtube.com",
    "youtube-nocookie.com",
    "youtu.be",
    "spotify.com",
    "soundcloud.com",
    "jiosaavn.com",
    "audiomack.com",
)


def _get_multi_cache():
    from bot.utils.multi_tier_cache import multi_cache

    return multi_cache


def _background_task_done(task: asyncio.Task) -> None:
    try:
        task.exception()
    except asyncio.CancelledError:
        pass
    except Exception:
        pass
    finally:
        _background_tasks.discard(task)


def _normalize_source(value: Optional[str]) -> str:
    return (value or "unknown").strip().lower() or "unknown"


def _normalize_url_text(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return text
    if _URL_SCHEME_RX.match(text):
        return text
    if text.startswith("www."):
        return f"https://{text}"
    return text


def _looks_like_unsupported_page_url(value: str) -> bool:
    text = (value or "").strip().lower()
    if not text:
        return False
    return any(domain in text for domain in _UNSUPPORTED_PAGE_DOMAINS)


def _infer_source_from_url(value: str) -> str:
    text = _normalize_url_text(value).strip().lower()
    if not text:
        return "unknown"
    if _looks_like_unsupported_page_url(text):
        return "unsupported"
    if text.startswith("http"):
        return "direct"
    return "unknown"


def _looks_like_url(value: str) -> bool:
    text = (value or "").strip()
    if not text:
        return False
    if _URL_SCHEME_RX.match(text):
        return True
    return text.startswith("www.")


@dataclass
class Track:
    title: str
    artist: str
    duration: int
    stream_url: str
    thumbnail: Optional[str] = None
    source: str = "unknown"
    track_id: Optional[str] = None

    def __init__(self, **kwargs):
        self.title = kwargs.get("title", "Unknown Title")
        self.artist = kwargs.get("artist") or kwargs.get("uploader") or "Unknown Artist"
        self.duration = int(kwargs.get("duration", 0) or 0)
        self.stream_url = _normalize_url_text(
            kwargs.get("stream_url")
            or kwargs.get("url")
            or kwargs.get("audio_url")
            or kwargs.get("audio")
            or kwargs.get("play_url")
            or ""
        )
        self.thumbnail = kwargs.get("thumbnail") or kwargs.get("thumb") or kwargs.get("thumbnail_url")
        self.source = _normalize_source(kwargs.get("source"))
        self.track_id = (
            kwargs.get("track_id")
            or kwargs.get("id")
        )
        if self.track_id is not None:
            self.track_id = str(self.track_id)

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
        "telegram": 1.8,
        "direct": 2.0,
        "global_index": 2.1,
        "unknown": 3.0,
    }
    _health: Dict[str, Dict[str, int]] = {}

    @classmethod
    def record_success(cls, source: str) -> None:
        stats = cls._health.setdefault(_normalize_source(source), {"success": 0, "fail": 0})
        stats["success"] += 1

    @classmethod
    def record_failure(cls, source: str) -> None:
        stats = cls._health.setdefault(_normalize_source(source), {"success": 0, "fail": 0})
        stats["fail"] += 1

    @classmethod
    def get_reliability(cls, source: str) -> float:
        stats = cls._health.get(_normalize_source(source), {"success": 0, "fail": 0})
        total = stats["success"] + stats["fail"]
        if total == 0:
            return 0.8
        return stats["success"] / total

    @classmethod
    def get_source_priority(cls, source: str, query: str = "") -> int:
        _ = query
        source_name = _normalize_source(source)
        base = cls._BASE_WEIGHTS.get(source_name, cls._BASE_WEIGHTS["unknown"])
        reliability = cls.get_reliability(source_name)
        reliability_bonus = (1.0 - reliability) * 0.25
        final_score = base - reliability_bonus
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
    """Search/resolve layer that proxies all music lookups to remote microservices."""

    def __init__(self):
        self._index_misses = 0
        self._index_skip_until = 0.0
        self._client = self._build_client()

    def _build_client(self) -> MusicMicroserviceClient:
        from config import config

        raw_urls = []
        if getattr(config, "MUSIC_MICROSERVICE_URLS", None):
            raw_urls.extend([u.strip() for u in str(config.MUSIC_MICROSERVICE_URLS).split(",")])
        if getattr(config, "MUSIC_MICROSERVICE_URL", None):
            raw_urls.append(str(config.MUSIC_MICROSERVICE_URL).strip())

        return MusicMicroserviceClient(
            base_urls=raw_urls,
            search_path=getattr(config, "MUSIC_MICROSERVICE_SEARCH_PATH", "/search"),
            resolve_path=getattr(config, "MUSIC_MICROSERVICE_RESOLVE_PATH", "/resolve"),
            health_path=getattr(config, "MUSIC_MICROSERVICE_HEALTH_PATH", "/health"),
            timeout_seconds=int(getattr(config, "MUSIC_MICROSERVICE_TIMEOUT", 12) or 12),
            token=getattr(config, "MUSIC_MICROSERVICE_TOKEN", None),
            token_header=getattr(config, "MUSIC_MICROSERVICE_TOKEN_HEADER", "Authorization"),
        )

    async def init(self):
        self._client = self._build_client()
        self._index_misses = 0
        self._index_skip_until = 0.0

        await source_health_tracker.register_source("telegram", base_score=1.05)
        await source_health_tracker.register_source("direct", base_score=1.1)
        await source_health_tracker.register_source("microservice", base_score=1.2)

        if not self._client.is_configured:
            logger.warning("MusicBackend started without MUSIC_MICROSERVICE_URL(S) configured.")
        else:
            logger.info("MusicBackend initialized with %d microservice endpoint(s).", len(self._client.base_urls))

    async def close(self):
        return None

    @staticmethod
    def _normalize_query_key(query: str) -> str:
        return (query or "").strip().lower()

    @staticmethod
    def _clean_search_query(query: str) -> str:
        if not query:
            return ""
        text = query
        text = re.sub(r"\(.*?\)", "", text)
        text = re.sub(r"\[.*?\]", "", text)
        text = re.sub(r"\|.*$", "", text)
        text = re.sub(r"-.*$", "", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text or query

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
        duration = int(metadata.get("duration", row.get("duration", 0)) or 0)
        thumbnail = metadata.get("thumbnail") or row.get("thumbnail") or row.get("thumb")

        sources = row.get("sources") if isinstance(row.get("sources"), list) else []
        track_id = row.get("track_id") or row.get("id") or row.get("jamendo_track_id")
        stream_url = _normalize_url_text(
            row.get("stream_url") or metadata.get("stream_url") or row.get("url") or metadata.get("url") or ""
        )
        source = _normalize_source(row.get("source") or metadata.get("source") or "global_index")

        if sources:
            first = sources[0] if isinstance(sources[0], dict) else {}
            track_id = track_id or first.get("id") or first.get("track_id")
            source = _normalize_source(first.get("source") or source)
            stream_url = stream_url or _normalize_url_text(first.get("stream_url") or first.get("url") or "")

        if source == "global_index":
            guessed = _infer_source_from_url(stream_url)
            if guessed != "unknown":
                source = guessed

        if source == "unsupported":
            return None

        return Track(
            title=title,
            artist=artist,
            duration=duration,
            stream_url=stream_url,
            thumbnail=thumbnail,
            source=source,
            track_id=str(track_id) if track_id is not None else None,
        )

    @staticmethod
    def _item_to_track(item: Dict[str, Any], default_source: str) -> Optional[Track]:
        if not isinstance(item, dict):
            return None

        source = _normalize_source(item.get("source") or default_source or "unknown")
        track_id = item.get("id") or item.get("track_id")
        stream_url = _normalize_url_text(
            item.get("stream_url")
            or item.get("audio_url")
            or item.get("audio")
            or item.get("url")
            or item.get("play_url")
            or ""
        )

        if source == "unsupported":
            return None

        if source == "unknown":
            source = _infer_source_from_url(stream_url)
            if source == "unsupported":
                return None

        if not stream_url and track_id is None:
            return None

        return Track(
            title=item.get("title") or item.get("name") or "Unknown",
            artist=item.get("artist") or item.get("uploader") or item.get("author") or "Unknown Artist",
            duration=int(item.get("duration") or item.get("length") or 0),
            stream_url=stream_url,
            thumbnail=item.get("thumbnail")
            or item.get("thumbnail_url")
            or item.get("image")
            or item.get("album_image")
            or item.get("cover"),
            source=source,
            track_id=str(track_id) if track_id is not None else None,
        )

    async def _search_index(self, query: str, limit: int) -> List[Track]:
        if time.time() < self._index_skip_until:
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
            return []

        tracks: List[Track] = []
        seen: set[str] = set()

        for row in rows or []:
            track = self._row_to_track(row)
            if not track:
                continue

            dedupe_key = (track.track_id or track.stream_url or track.title).strip().lower()
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            tracks.append(track)
            if len(tracks) >= limit:
                break

        if tracks:
            self._index_misses = 0
        else:
            self._index_misses += 1
            if self._index_misses >= 3:
                self._index_skip_until = time.time() + 300

        return tracks

    async def _cache_to_index(self, query: str, tracks: List[Track]) -> None:
        app_db = getattr(database_module, "db", None)
        if app_db is None or not hasattr(app_db, "save_track_to_index") or not tracks:
            return

        async with _save_semaphore:
            try:
                best_track = tracks[0]
                await app_db.save_track_to_index(self._normalize_query_key(query), best_track.to_dict())
            except Exception as exc:
                logger.warning("Failed to cache to database: %s", exc)

    async def _search_microservice(self, query: str, limit: int) -> List[Track]:
        if not self._client.is_configured:
            return []

        routing_hints = build_title_routing_hints(query, limit=limit)
        try:
            raw_results = await self._client.search(query, limit=limit, routing=routing_hints)
            await source_health_tracker.record_success("microservice")
        except Exception as exc:
            await source_health_tracker.record_failure("microservice")
            logger.warning("Microservice search failed for %r: %s", query, exc)
            return []

        tracks: List[Track] = []
        for item in raw_results or []:
            track = self._item_to_track(item, item.get("source", "external"))
            if not track:
                continue
            tracks.append(track)
            if len(tracks) >= limit:
                break
        return tracks

    @staticmethod
    def _dedupe_tracks(items: List[Track], limit: int) -> List[Track]:
        out: List[Track] = []
        seen: set[str] = set()
        for track in items:
            dedupe_key = f"{track.source}:{track.track_id or track.stream_url or track.title}".strip().lower()
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            out.append(track)
            if len(out) >= limit:
                break
        return out

    def _track_to_resolve_payload(self, track: Track) -> Dict[str, Any]:
        routing_hints = build_title_routing_hints(
            f"{track.title} {track.artist}".strip() or track.title or track.artist or "",
            limit=3,
        )
        payload = {
            "title": track.title,
            "artist": track.artist,
            "duration": int(track.duration or 0),
            "stream_url": track.stream_url or "",
            "source": track.source or "unknown",
            "track_id": track.track_id,
            "thumbnail": track.thumbnail,
            "routing": routing_hints,
        }
        # Microservices commonly expect "id" rather than "track_id".
        payload["id"] = track.track_id
        return payload

    def _resolved_to_payload(self, original: Track, resolved: Dict[str, Any], fallback_source: str = "unknown") -> Optional[Dict[str, Any]]:
        resolved_track = self._item_to_track(resolved, resolved.get("source") or fallback_source)
        if not resolved_track:
            return None

        url = resolved_track.stream_url
        if not url and original.stream_url:
            url = original.stream_url
        url = _normalize_url_text(url or "")

        if not url:
            return None
        if _looks_like_unsupported_page_url(url):
            return None

        source = _normalize_source(resolved_track.source or fallback_source or original.source or "unknown")
        if source == "unknown":
            guessed = _infer_source_from_url(url)
            if guessed != "unknown":
                source = guessed

        headers = resolved.get("headers") if isinstance(resolved.get("headers"), dict) else None

        return {
            "url": url,
            "stream_url": url,
            "source": source if source != "unsupported" else "unknown",
            "title": resolved_track.title or original.title,
            "artist": resolved_track.artist or original.artist,
            "duration": int(resolved_track.duration or original.duration or 0),
            "thumbnail": resolved_track.thumbnail or original.thumbnail,
            "id": resolved_track.track_id or original.track_id,
            "track_id": resolved_track.track_id or original.track_id,
            "headers": headers,
        }

    async def search(self, query: str, limit: int = 5) -> List[Track]:
        query = (query or "").strip()
        if not query:
            return []

        if _looks_like_url(query):
            url = _normalize_url_text(query)
            source = _infer_source_from_url(url)
            if source == "unsupported":
                return []
            return [
                Track(
                    title="Direct Link",
                    artist="Unknown Artist",
                    duration=0,
                    stream_url=url,
                    source=source,
                    track_id=url,
                )
            ]

        cache_key = f"search:{query}:{limit}"
        multi_cache = _get_multi_cache()
        cached, _ = await multi_cache.get(cache_key)
        if cached:
            return [self._coerce_track(t) for t in cached]

        from config import config

        tracks_from_service: List[Track] = []
        tracks_from_index: List[Track] = []

        if getattr(config, "PARALLEL_SEARCH", True):
            svc_task = asyncio.create_task(self._search_microservice(query, limit))
            idx_task = asyncio.create_task(self._search_index(query, limit))
            done, pending = await asyncio.wait({svc_task, idx_task}, timeout=30)

            for task in done:
                try:
                    result = task.result()
                except Exception:
                    result = []
                if task is svc_task:
                    tracks_from_service = result
                elif task is idx_task:
                    tracks_from_index = result

            for task in pending:
                task.cancel()
        else:
            if getattr(config, "PRIORITIZE_EXTRACTORS", True):
                tracks_from_service = await self._search_microservice(query, limit)
                if len(tracks_from_service) < limit:
                    tracks_from_index = await self._search_index(query, limit)
            else:
                tracks_from_index = await self._search_index(query, limit)
                if len(tracks_from_index) < limit:
                    tracks_from_service = await self._search_microservice(query, limit)

        tracks = self._dedupe_tracks(tracks_from_service + tracks_from_index, limit)

        if tracks and len(_background_tasks) < _MAX_BACKGROUND_TASKS:
            task = asyncio.create_task(self._cache_to_index(query, tracks))
            _background_tasks.add(task)
            task.add_done_callback(_background_task_done)

        if tracks:
            try:
                multi_cache = _get_multi_cache()
                await multi_cache.set(cache_key, [t.to_dict() for t in tracks], ttl=600)
            except Exception:
                pass

        return tracks

    async def get_stream_payload(self, track: Track) -> Optional[Dict[str, Any]]:
        if not track:
            return None

        source = _normalize_source(track.source)
        if source in {"telegram", "song_hunter", "local"} and track.stream_url and not track.stream_url.startswith("http"):
            local_payload = {
                "url": track.stream_url,
                "stream_url": track.stream_url,
                "source": source,
                "title": track.title,
                "artist": track.artist,
                "duration": int(track.duration or 0),
                "thumbnail": track.thumbnail,
                "id": track.track_id,
                "track_id": track.track_id,
                "headers": None,
            }
            return local_payload

        direct_source = _infer_source_from_url(track.stream_url)
        if track.stream_url and track.stream_url.startswith("http") and direct_source == "direct":
            return self._resolved_to_payload(track, track.to_dict(), fallback_source="direct")

        if source == "unsupported":
            raise FallbackExhaustedError("Unsupported source URL.")

        if self._client.is_configured:
            resolved = await self._client.resolve(self._track_to_resolve_payload(track))
            payload = self._resolved_to_payload(track, resolved or {}, fallback_source=source)
            if payload and payload.get("url"):
                return payload

        # Fallback: search by text and re-resolve one of the results.
        if self._client.is_configured and track.title:
            clean_title = self._clean_search_query(track.title)
            clean_artist = self._clean_search_query(track.artist) if track.artist and track.artist != "Unknown Artist" else ""
            search_query = f"{clean_title} {clean_artist}".strip() or track.title
            search_results = await self._search_microservice(search_query, limit=3)
            for candidate in search_results:
                resolved = await self._client.resolve(self._track_to_resolve_payload(candidate))
                payload = self._resolved_to_payload(track, resolved or {}, fallback_source=candidate.source)
                if payload and payload.get("url"):
                    return payload

        if track.stream_url and track.stream_url.startswith("http") and not _looks_like_unsupported_page_url(track.stream_url):
            fallback = self._resolved_to_payload(track, track.to_dict(), fallback_source=source or "direct")
            if fallback and fallback.get("url"):
                return fallback

        raise FallbackExhaustedError("Could not find a working stream for this track across configured microservices.")

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
                candidate = Track(title="Direct Link", artist="Unknown Artist", duration=0, stream_url=text)
                return await self.get_stream_payload(candidate)
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

    async def health(self) -> Dict[str, Any]:
        return await self._client.health()

    def _coerce_track(self, target: Any) -> Track:
        if isinstance(target, Track):
            return target
        if isinstance(target, str):
            return Track(title="Direct Link", artist="Unknown", duration=0, stream_url=target)
        if isinstance(target, dict):
            return Track(**target)
        return Track(title="Unknown", artist="Unknown", duration=0, stream_url="")


music_backend = MusicBackend()

__all__ = ["Track", "SourceRanker", "calculate_track_quality", "MusicBackend", "music_backend"]
