"""Local multi-source web fallback search/resolve using yt-dlp.

This module is used only when remote microservice search/resolve cannot return
usable items. It gives the bot a resilient in-process fallback across common
web sources (YouTube, YouTube Music, SoundCloud).
"""

from __future__ import annotations

import asyncio
import logging
import os
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


def _yt_dlp_opts(fast: bool = False) -> Dict[str, Any]:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "skip_download": True,
        "extract_flat": False,
        "format": "bestaudio/best",
        "cachedir": False,
        "socket_timeout": 20,
    }
    if fast:
        # Fast search mode: fetch only the playlist/search metadata without
        # resolving each result. Typically 3-4x faster than full extraction and
        # still includes title/duration/channel/url, which is all the selection
        # menu needs. The full stream URL is resolved later when a track plays.
        opts.update(
            {
                "extract_flat": True,
                "lazy_playlist": True,
            }
        )

    # Use the Android player client for YouTube by default: its stream URLs are
    # not gated by the same bot-detection as the web clients, which return HTTP
    # 403 on videoplayback without a logged-in session. Override with
    # YTDLP_YOUTUBE_CLIENT or YTDLP_EXTRACTOR_ARGS if needed.
    custom_args = os.getenv("YTDLP_EXTRACTOR_ARGS", "").strip()
    if custom_args:
        opts["extractor_args"] = {"youtube": [a.strip() for a in custom_args.split(";") if a.strip()]}
    else:
        client = os.getenv("YTDLP_YOUTUBE_CLIENT", "android").strip() or "android"
        opts["extractor_args"] = {"youtube": [f"player_client={client}"]}

    # Optional cookie file for logged-in playback (see README / bot docs).
    cookiefile = os.getenv("YTDLP_COOKIES_FILE", "cookies.txt").strip()
    if cookiefile and os.path.isfile(cookiefile):
        opts["cookiefile"] = cookiefile

    return opts


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

    thumb = info.get("thumbnail")
    if not thumb:
        thumbs = info.get("thumbnails")
        if isinstance(thumbs, list) and thumbs:
            thumb = thumbs[-1].get("url") if isinstance(thumbs[-1], dict) else None

    artist = (
        info.get("artist")
        or info.get("uploader")
        or info.get("channel")
        or info.get("creator")
        or "Unknown Artist"
    )

    return {
        "title": info.get("title") or "Unknown",
        "artist": artist,
        "uploader": artist,
        "duration": int(info.get("duration") or 0),
        "stream_url": stream_url,
        "url": stream_url,
        "thumbnail": thumb,
        "source": source,
        "track_id": str(track_id),
        "id": str(track_id),
        "webpage_url": webpage_url,
        "headers": info.get("http_headers") if isinstance(info.get("http_headers"), dict) else None,
    }


def _extract_sync(target: str, default_search: Optional[str] = None, fast: bool = False) -> Optional[Dict[str, Any]]:
    if not HAS_YTDLP:
        return None
    opts = _yt_dlp_opts(fast=fast)
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


async def _search_provider(provider: str, query: str, limit: int) -> List[Dict[str, Any]]:
    """Search a single provider via yt-dlp (fast flat extraction)."""
    prefix = _SEARCH_PREFIX.get(provider)
    if not prefix:
        return []

    search_term = f"{prefix}{max(1, int(limit))}:{query}"
    try:
        info = await asyncio.to_thread(_extract_sync, search_term, None, True)
    except Exception as exc:
        logger.debug("Local fallback search failed for provider=%s query=%r: %s", provider, query, exc)
        return []

    out: List[Dict[str, Any]] = []
    entries = info.get("entries") if isinstance(info, dict) and isinstance(info.get("entries"), list) else []
    for entry in entries:
        track = _info_to_track(entry, source=provider, prefer_webpage_url=True)
        if track:
            out.append(track)
    return out


async def search_tracks(query: str, limit: int = 5, provider_priority: Optional[str] = None) -> List[Dict[str, Any]]:
    """Search tracks across provider prefixes via yt-dlp, concurrently."""
    text = (query or "").strip()
    if not text:
        return []
    if not HAS_YTDLP:
        logger.warning("yt-dlp is not installed; local fallback search disabled.")
        return []

    providers = _provider_order(provider_priority)
    results = await asyncio.gather(
        *(_search_provider(provider, text, limit) for provider in providers),
        return_exceptions=True,
    )

    out: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for tracks in results:
        if isinstance(tracks, Exception) or not tracks:
            continue
        for track in tracks:
            dedupe_key = (track.get("track_id") or track.get("url") or track.get("title") or "").strip().lower()
            if not dedupe_key or dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            out.append(track)
            if len(out) >= limit:
                return out

    return out
