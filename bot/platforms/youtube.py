"""
YouTube audio extraction — stream URL only (no download).

Design principles:
- NEVER download: get the direct CDN URL and pass it straight to py-tgcalls
- Multi-client fallback: android → web → mweb (avoids bot detection)
- Semaphore: max 3 concurrent yt-dlp calls to prevent CPU spikes
- Redis caching: cache resolved CDN URLs for 5.5h (YouTube URLs expire at ~6h)
- 30s timeout: prevents bot hanging on slow extractions
"""

import asyncio
import logging
import os
from typing import Optional, Dict, Any

import yt_dlp

logger = logging.getLogger(__name__)

# ─── Concurrency guard ────────────────────────────────────────────────────────
_EXTRACT_SEMAPHORE = asyncio.Semaphore(3)

# ─── Client fallback chain ───────────────────────────────────────────────────
# Each entry is tried in order until one succeeds
_PLAYER_CLIENTS = [
    ["android"],          # Best bypass, highest success rate
    ["web"],              # Standard fallback
    ["mweb"],             # Mobile web, last resort
]

# ─── Format selection ─────────────────────────────────────────────────────────
# Prefer Opus/WebM (native Telegram codec) → M4A → MP3 → best
# Do NOT use postprocessors — we want the RAW stream URL, not a downloaded file
_FORMAT = (
    "bestaudio[ext=webm][acodec=opus]/"
    "bestaudio[ext=m4a]/"
    "bestaudio[ext=mp3]/"
    "bestaudio"
)


def _build_opts(player_clients: list, cookies: Optional[str] = None) -> dict:
    opts = {
        "format": _FORMAT,
        "quiet": True,
        "no_warnings": True,
        "extract_flat": False,
        "noplaylist": True,
        "geo_bypass": True,
        "source_address": "0.0.0.0",
        "legacy_server_connect": True,
        "retries": 3,
        "extractor_args": {
            "youtube": {
                "player_client": player_clients,
                "player_skip": ["webpage", "configs"],
            }
        },
        # CRITICAL: NO postprocessors — we want the stream URL, not a download
    }

    # PO token / visitor data (advanced bypass — optional)
    po_token = os.environ.get("YT_PO_TOKEN")
    visitor_data = os.environ.get("YT_VISITOR_DATA")
    if po_token and visitor_data:
        opts["extractor_args"]["youtube"]["po_token"] = [f"web+{po_token}"]
        opts["extractor_args"]["youtube"]["visitor_data"] = [visitor_data]

    # Cookies from logged-in browser session (optional, improves success rate)
    if cookies and os.path.exists(cookies):
        opts["cookiefile"] = cookies

    return opts


_COOKIES_PATH = "./cookies.txt"


class YouTubeExtractor:
    """Thread-pool-safe YouTube audio URL extractor."""

    def _extract_sync(self, query: str, player_clients: list) -> Optional[Dict[str, Any]]:
        """Run yt-dlp synchronously in a thread pool executor."""
        opts = _build_opts(player_clients, _COOKIES_PATH if os.path.exists(_COOKIES_PATH) else None)

        # Prepend ytsearch: for non-URL queries
        if not any(query.startswith(p) for p in ("http://", "https://", "youtu")):
            query = f"ytsearch:{query}"

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(query, download=False)

                # Unwrap search results
                if info and "entries" in info:
                    entries = [e for e in info["entries"] if e]
                    if not entries:
                        return None
                    info = entries[0]

                if not info:
                    return None

                # Pick the best audio-only stream URL
                formats = info.get("formats") or []
                stream_url = None

                # Priority: audio-only streams first
                for fmt in reversed(formats):
                    if fmt.get("acodec") not in (None, "none") and fmt.get("vcodec") in (None, "none", ""):
                        url = fmt.get("url")
                        if url:
                            stream_url = url
                            break

                # Fallback: any format with audio
                if not stream_url:
                    for fmt in reversed(formats):
                        if fmt.get("acodec") not in (None, "none"):
                            url = fmt.get("url")
                            if url:
                                stream_url = url
                                break

                # Last resort: top-level url
                if not stream_url:
                    stream_url = info.get("url")

                if not stream_url:
                    return None

                return {
                    "url": stream_url,
                    "title": info.get("title", "Unknown"),
                    "duration": int(info.get("duration") or 0),
                    "thumbnail": info.get("thumbnail"),
                    "uploader": info.get("uploader") or info.get("channel", ""),
                    "source": "youtube",
                    "video_id": info.get("id", ""),
                }

        except Exception as exc:
            logger.debug(f"yt-dlp extract_sync error [{player_clients}]: {exc}")
            return None

    async def extract(self, query: str) -> Optional[Dict[str, Any]]:
        """
        Extract audio stream URL with:
        - concurrency semaphore (max 3 simultaneous)
        - multi-client fallback chain
        - 30s hard timeout
        - Redis CDN URL caching (5.5h TTL)
        """
        async with _EXTRACT_SEMAPHORE:
            # Check Redis cache first (video_id based, skip for raw search queries)
            video_id = _parse_video_id(query)
            if video_id:
                cached = await _get_cached_url(video_id)
                if cached:
                    logger.info(f"Cache HIT for YouTube video {video_id}")
                    return cached

            loop = asyncio.get_event_loop()

            for clients in _PLAYER_CLIENTS:
                try:
                    result = await asyncio.wait_for(
                        loop.run_in_executor(None, self._extract_sync, query, clients),
                        timeout=30.0,
                    )
                    if result:
                        # Cache the CDN URL if we have a video ID
                        vid = result.get("video_id") or video_id
                        if vid:
                            await _cache_url(vid, result)
                        logger.info(
                            f"YouTube extracted [{clients}]: {result['title'][:50]}"
                        )
                        return result
                except asyncio.TimeoutError:
                    logger.warning(f"yt-dlp timeout with client {clients}")
                except Exception as exc:
                    logger.warning(f"yt-dlp error [{clients}]: {exc}")

            logger.error(f"All YouTube clients failed for: {query}")
            return None

    def _search_sync(self, query: str, limit: int) -> list:
        """Search YouTube for multiple results."""
        opts = _build_opts(_PLAYER_CLIENTS[0], _COOKIES_PATH if os.path.exists(_COOKIES_PATH) else None)
        opts["extract_flat"] = True  # Metadata only, much faster
        opts["playlist_items"] = f"1-{limit}"

        search_query = f"ytsearch{limit}:{query}"
        results = []

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(search_query, download=False)
                for entry in (info or {}).get("entries") or []:
                    if entry:
                        results.append({
                            "title": entry.get("title", "Unknown"),
                            "duration": int(entry.get("duration") or 0),
                            "thumbnail": entry.get("thumbnail"),
                            "uploader": entry.get("uploader") or entry.get("channel", ""),
                            "id": entry.get("id", ""),
                            "url": f"https://youtube.com/watch?v={entry.get('id', '')}",
                            "source": "youtube",
                        })
        except Exception as exc:
            logger.error(f"YouTube search error: {exc}")

        return results

    async def search(self, query: str, limit: int = 5, max_results: int = None) -> list:
        """Search YouTube and return metadata-only results (no stream URL resolution)."""
        limit = max_results or limit
        loop = asyncio.get_event_loop()
        try:
            return await asyncio.wait_for(
                loop.run_in_executor(None, self._search_sync, query, limit),
                timeout=20.0,
            )
        except asyncio.TimeoutError:
            logger.warning("YouTube search timed out")
        except Exception as exc:
            logger.error(f"YouTube search failed: {exc}")
        return []


# ─── Redis / cache helpers ────────────────────────────────────────────────────

import re

def _parse_video_id(query: str) -> Optional[str]:
    """Extract YouTube video ID from URL, or None for plain search queries."""
    patterns = [
        r"(?:v=|youtu\.be/|/embed/|/shorts/)([A-Za-z0-9_-]{11})",
    ]
    for p in patterns:
        m = re.search(p, query)
        if m:
            return m.group(1)
    return None


async def _get_cached_url(video_id: str) -> Optional[Dict[str, Any]]:
    """Try to get a cached stream URL from Redis."""
    try:
        import json
        from bot.utils.cache import cache
        key = f"yt_stream:{video_id}"
        data = await cache.get(key)
        if data:
            return json.loads(data)
    except Exception:
        pass
    return None


async def _cache_url(video_id: str, result: Dict[str, Any], ttl: int = 19800):
    """Cache a resolved stream URL in Redis (default TTL: 5.5h)."""
    try:
        import json
        from bot.utils.cache import cache
        key = f"yt_stream:{video_id}"
        await cache.set(key, json.dumps(result), ex=ttl)
    except Exception:
        pass


# ─── Global instance + convenience wrappers ──────────────────────────────────

youtube = YouTubeExtractor()


async def extract_youtube(query: str) -> Optional[Dict[str, Any]]:
    return await youtube.extract(query)


async def search_youtube(query: str, limit: int = 5) -> list:
    return await youtube.search(query, limit)
