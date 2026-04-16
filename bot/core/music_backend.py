import logging
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

from bot.platforms.piped import piped

logger = logging.getLogger(__name__)


@dataclass
class Track:
    """Universal track representation used across plugins and queue."""

    title: str
    artist: str
    duration: int
    stream_url: str
    thumbnail: Optional[str] = None
    source: str = "unknown"
    track_id: Optional[str] = None

    def get(self, key: str, default: Any = None) -> Any:
        mapping = {
            "url": "stream_url",
            "uploader": "artist",
            "id": "track_id",
            "thumb": "thumbnail",
        }
        attr = mapping.get(key, key)
        return getattr(self, attr, default)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["url"] = self.stream_url
        d["uploader"] = self.artist
        d["id"] = self.track_id
        d["thumb"] = self.thumbnail
        return d


class SourceRanker:
    """Compatibility ranking helper used by selection logic in play plugin."""

    _BASE_WEIGHTS = {
        "global_index": 1.0,
        "youtube": 0.95,
        "piped": 0.9,
        "telegram": 0.4,
        "unknown": 0.3,
    }
    _health: Dict[str, Dict[str, int]] = {}

    @classmethod
    def record_success(cls, source: str) -> None:
        stats = cls._health.setdefault(source, {"success": 0, "fail": 0})
        stats["success"] += 1

    @classmethod
    def record_failure(cls, source: str) -> None:
        stats = cls._health.setdefault(source, {"success": 0, "fail": 0})
        stats["fail"] += 1

    @classmethod
    def get_reliability(cls, source: str) -> float:
        stats = cls._health.get(source, {"success": 0, "fail": 0})
        total = stats["success"] + stats["fail"]
        if total == 0:
            return 0.8
        return stats["success"] / total

    @classmethod
    def get_source_priority(cls, source: str, query: str = "") -> int:
        _ = query
        src = (source or "unknown").lower()
        base = cls._BASE_WEIGHTS.get(src, cls._BASE_WEIGHTS["unknown"])
        reliability = cls.get_reliability(src)

        # Convert to priority score where lower is better.
        combined = (base * 0.75) + (reliability * 0.25)
        return int((1.0 - combined) * 100)


def calculate_track_quality(track: Track) -> float:
    """Compatibility quality scorer used by selection logic in play plugin."""

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
    """Simplified backend: Supabase index first, then Piped search/extract."""

    def __init__(self):
        self.piped = piped

    async def init(self):
        logger.info("MusicBackend initialized (Piped + Supabase cache)")

    async def close(self):
        logger.info("MusicBackend closed")

    @staticmethod
    def _normalize_query_key(query: str) -> str:
        return (query or "").strip().lower()

    @staticmethod
    def _extract_metadata(row: Dict[str, Any]) -> Dict[str, Any]:
        metadata = row.get("metadata")
        return metadata if isinstance(metadata, dict) else {}

    @staticmethod
    def _row_to_track(row: Dict[str, Any]) -> Optional[Track]:
        title = row.get("title") or "Unknown"
        artist = row.get("artist") or "Unknown"
        metadata = MusicBackend._extract_metadata(row)

        duration = metadata.get("duration", row.get("duration", 0)) or 0
        thumbnail = metadata.get("thumbnail", row.get("thumbnail"))

        sources = row.get("sources") if isinstance(row.get("sources"), list) else []
        track_id = row.get("track_id")
        stream_url = row.get("stream_url") or ""
        source = row.get("source") or "global_index"

        if sources:
            first = sources[0] if isinstance(sources[0], dict) else {}
            track_id = track_id or first.get("id")
            source = first.get("source") or source
            stream_url = stream_url or first.get("url", "")

        if not stream_url and track_id:
            stream_url = f"https://youtube.com/watch?v={track_id}"

        if not stream_url:
            return None

        return Track(
            title=title,
            artist=artist,
            duration=int(duration),
            stream_url=stream_url,
            thumbnail=thumbnail,
            source=str(source),
            track_id=track_id,
        )

    async def _load_from_index(self, query: str, limit: int) -> List[Track]:
        try:
            from bot.utils.database import db as app_db
        except Exception:
            return []

        if app_db is None or not hasattr(app_db, "search_global_music_index"):
            return []

        try:
            rows = await app_db.search_global_music_index(query, limit)
        except Exception as e:
            logger.warning(f"Global index lookup failed: {e}")
            return []

        tracks: List[Track] = []
        seen: set[str] = set()

        for row in rows or []:
            if not isinstance(row, dict):
                continue
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
            logger.info(f"Global index hit for '{query}' with {len(tracks)} track(s)")

        return tracks

    async def _save_to_index(self, query: str, track: Track) -> None:
        try:
            from bot.utils.database import db as app_db
        except Exception:
            return

        if app_db is None or not hasattr(app_db, "save_track_to_index"):
            return

        payload = track.to_dict()
        payload["metadata"] = {
            "duration": track.duration,
            "thumbnail": track.thumbnail,
        }
        payload["sources"] = [
            {
                "source": "youtube",
                "id": track.track_id,
                "url": track.stream_url,
            }
        ]

        try:
            await app_db.save_track_to_index(self._normalize_query_key(query), payload)
        except Exception as e:
            logger.warning(f"Failed to cache track in global index: {e}")

    async def search(self, query: str, limit: int = 5) -> List[Track]:
        query = (query or "").strip()
        if not query:
            return []

        # 1) Supabase global index first.
        indexed = await self._load_from_index(query, limit)
        if indexed:
            return indexed[:limit]

        # 2) Piped search fallback.
        results = await self.piped.search(query, limit=limit)
        tracks: List[Track] = []

        for item in results or []:
            if not isinstance(item, dict):
                continue

            video_id = item.get("id")
            title = item.get("title") or "Unknown"
            artist = item.get("uploader") or item.get("artist") or "Unknown"
            duration = int(item.get("duration") or 0)
            stream_url = item.get("url") or ""
            thumbnail = item.get("thumbnail")

            if not stream_url and video_id:
                stream_url = f"https://youtube.com/watch?v={video_id}"

            if not stream_url:
                continue

            track = Track(
                title=title,
                artist=artist,
                duration=duration,
                stream_url=stream_url,
                thumbnail=thumbnail,
                source="youtube",
                track_id=video_id,
            )
            tracks.append(track)

            # Write-through cache.
            await self._save_to_index(query, track)

            if len(tracks) >= limit:
                break

        logger.info(f"Search fallback via Piped for '{query}': {len(tracks)} track(s)")
        return tracks

    async def get_stream_payload(self, track: Track) -> Optional[Dict[str, Any]]:
        """Resolve final playable stream URL using Piped extractor."""
        if not self.piped:
            return None

        candidates = [track.track_id, track.stream_url, self._build_fallback_query(track)]
        tried: set[str] = set()

        for candidate in candidates:
            value = (candidate or "").strip()
            if not value or value in tried:
                continue
            tried.add(value)

            extracted = await self.piped.extract(value)
            if not extracted or not extracted.get("url"):
                continue

            resolved_url = extracted.get("url")
            return {
                "url": resolved_url,
                "stream_url": resolved_url,
                "title": extracted.get("title") or track.title,
                "artist": extracted.get("uploader") or track.artist,
                "duration": extracted.get("duration") or track.duration,
                "thumbnail": extracted.get("thumbnail") or track.thumbnail,
                "source": "youtube",
                "headers": None,
            }

        return None

    async def get_stream_url(self, track: Track) -> Optional[str]:
        payload = await self.get_stream_payload(track)
        if not payload:
            return None
        return payload.get("url") or payload.get("stream_url")

    @staticmethod
    def get_source_headers(source: str) -> Optional[Dict[str, str]]:
        _ = source
        return None

    @staticmethod
    def _build_fallback_query(track: Track) -> str:
        title = (track.title or "").strip()
        artist = (track.artist or "").strip()
        if title and artist and artist.lower() != "unknown":
            return f"{title} {artist}".strip()
        return title or artist or ""

    async def _resolve_fallback_payload(self, track: Track) -> Optional[Dict[str, Any]]:
        return await self.get_stream_payload(track)


music_backend = MusicBackend()
