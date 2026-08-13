"""Local multi-source web fallback search/resolve using yt-dlp.

This module is used only when remote microservice search/resolve cannot return
usable items. It gives the bot a resilient in-process fallback across common
web sources (YouTube, YouTube Music, SoundCloud).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    import yt_dlp  # type: ignore

    HAS_YTDLP = True
except Exception:
    yt_dlp = None
    HAS_YTDLP = False


_DEFAULT_PROVIDER_ORDER = ["youtube", "youtube_music", "soundcloud"]

_SEARCH_PREFIX = {
    "youtube": "ytsearch",
    "youtube_music": "ytmsearch",
    "ytmusic": "ytmsearch",
    "soundcloud": "scsearch",
    # Apple Music does not have a stable public search prefix in yt-dlp.
    # We map it to YouTube Music search for best-effort results.
    "apple_music": "ytmsearch",
    "apple": "ytmsearch",
}


def _normalize_provider(value: str) -> str:
    return (value or "").strip().lower()


def _provider_order(raw: Optional[str]) -> List[str]:
    if not raw:
        return list(_DEFAULT_PROVIDER_ORDER)
    providers = [_normalize_provider(p) for p in str(raw).split(",")]
    providers = [p for p in providers if p]
    if not providers:
        return list(_DEFAULT_PROVIDER_ORDER)
    deduped: List[str] = []
    for provider in providers:
        if provider not in deduped:
            deduped.append(provider)
    return deduped


def _yt_dlp_opts() -> Dict[str, Any]:
    return {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "skip_download": True,
        "extract_flat": False,
        "format": "bestaudio/best",
        "cachedir": False,
        "socket_timeout": 20,
    }


def _info_to_track(info: Dict[str, Any], source: str, prefer_webpage_url: bool = False) -> Optional[Dict[str, Any]]:
    if not isinstance(info, dict):
        return None

    webpage_url = info.get("webpage_url") or info.get("original_url") or ""
    stream_url = info.get("url") or ""
    if prefer_webpage_url and webpage_url:
        stream_url = webpage_url
    track_id = info.get("id") or webpage_url or stream_url

    if not stream_url and not webpage_url:
        return None

    artist = (
        info.get("artist")
        or info.get("uploader")
        or info.get("channel")
        or "Unknown Artist"
    )

    return {
        "title": info.get("title") or "Unknown",
        "artist": artist,
        "uploader": artist,
        "duration": int(info.get("duration") or 0),
        "stream_url": stream_url,
        "url": stream_url,
        "thumbnail": info.get("thumbnail"),
        "source": source,
        "track_id": str(track_id),
        "id": str(track_id),
        "webpage_url": webpage_url,
        "headers": info.get("http_headers") if isinstance(info.get("http_headers"), dict) else None,
    }


def _extract_sync(target: str, default_search: Optional[str] = None) -> Optional[Dict[str, Any]]:
    if not HAS_YTDLP:
        return None
    opts = _yt_dlp_opts()
    if default_search:
        opts["default_search"] = default_search
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(target, download=False)


async def resolve_url(target: str, source: str = "external") -> Optional[Dict[str, Any]]:
    """Resolve a URL to a direct playable stream URL."""
    text = (target or "").strip()
    if not text:
        return None
    if not HAS_YTDLP:
        logger.warning("yt-dlp is not installed; local fallback resolver disabled.")
        return None

    try:
        info = await asyncio.to_thread(_extract_sync, text, None)
        if not info:
            return None
        return _info_to_track(info, source=source, prefer_webpage_url=False)
    except Exception as exc:
        logger.debug("Local fallback URL resolve failed for %r: %s", text, exc)
        return None


async def search_tracks(query: str, limit: int = 5, provider_priority: Optional[str] = None) -> List[Dict[str, Any]]:
    """Search tracks across provider prefixes via yt-dlp."""
    text = (query or "").strip()
    if not text:
        return []
    if not HAS_YTDLP:
        logger.warning("yt-dlp is not installed; local fallback search disabled.")
        return []

    providers = _provider_order(provider_priority)
    out: List[Dict[str, Any]] = []
    seen: set[str] = set()

    for provider in providers:
        prefix = _SEARCH_PREFIX.get(provider)
        if not prefix:
            continue
        search_term = f"{prefix}{max(1, int(limit))}:{text}"

        try:
            info = await asyncio.to_thread(_extract_sync, search_term, None)
        except Exception as exc:
            logger.debug("Local fallback search failed for provider=%s query=%r: %s", provider, text, exc)
            continue

        entries = info.get("entries") if isinstance(info, dict) and isinstance(info.get("entries"), list) else []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            track = _info_to_track(entry, source=provider, prefer_webpage_url=True)
            if not track:
                continue
            dedupe_key = (track.get("track_id") or track.get("url") or track.get("title") or "").strip().lower()
            if not dedupe_key or dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            out.append(track)
            if len(out) >= limit:
                return out

    return out
