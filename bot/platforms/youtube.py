"""YouTube Music extractor via yt-dlp.

This extractor searches and extracts streams directly from YouTube Music.
It implements circuit breaker protection and handles IP blocks gracefully.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import Any, Dict, List, Optional

import yt_dlp

from bot.utils.circuit_breaker import CircuitBreakerRegistry, CircuitBreakerOpen, retry_with_backoff, source_health_tracker
from bot.utils.errors import BotDetectionError, format_error_message

logger = logging.getLogger(__name__)

# Compile regexes once
_URL_SCHEME_RX = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://")
_YOUTUBE_ID_RX = re.compile(r"[?&]v=([a-zA-Z0-9_-]{11})")


def _normalize_url_text(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return text
    if _URL_SCHEME_RX.match(text):
        return text
    if text.startswith(("www.", "youtube.com", "youtu.be", "music.youtube.com")):
        return f"https://{text}"
    return text


def _extract_video_id(value: str) -> Optional[str]:
    """Extract YouTube video ID from URL or string."""
    if not value:
        return None

    # Direct ID (11 characters)
    if re.match(r"^[a-zA-Z0-9_-]{11}$", value):
        return value

    # From URL
    url = _normalize_url_text(value)
    match = _YOUTUBE_ID_RX.search(url)
    if match:
        return match.group(1)

    # From youtu.be/ID
    if "youtu.be/" in url:
        parts = url.split("youtu.be/")
        if len(parts) > 1:
            vid = parts[1].split("?")[0].split("&")[0]
            if len(vid) == 11:
                return vid

    return None


class YouTubeExtractor:
    """YouTube extractor with circuit breaker protection."""

    def __init__(self) -> None:
        self.cookies_file = os.getenv("YOUTUBE_COOKIES_FILE", "")
        self.cookie_string = os.getenv("YOUTUBE_COOKIES", "")

        # Base options for all requests
        self._base_ydl_opts = {
            "format": "bestaudio/best",
            "quiet": True,
            "no_warnings": True,
            "extract_flat": True,
            "source_address": "0.0.0.0",
            # Ignore errors like Geo-blocks to keep searching
            "ignoreerrors": True,
        }

        # Apply cookies if configured
        if self.cookies_file and os.path.exists(self.cookies_file):
            self._base_ydl_opts["cookiefile"] = self.cookies_file
            logger.info("YouTube Extractor: Using cookies file")
        elif self.cookie_string:
            # We would need to write it to a temp file, but for now just log
            logger.info(
                "YouTube Extractor: Has YOUTUBE_COOKIES env var but writing to file is not implemented here")

        # Get circuit breaker
        self._circuit_breaker = CircuitBreakerRegistry.get("youtube")

    async def _trigger_cookie_refresh(self):
        """Placeholder for out-of-band workflow to refresh cookies."""
        logger.warning(
            "Triggering direct YouTube cookie auto-refresh due to 403 Bot Detection")

    @retry_with_backoff(retries=2, base_delay=1.0, max_delay=5.0, exceptions=(BotDetectionError,))
    async def _extract_info(self, ydl: yt_dlp.YoutubeDL, query: str, download: bool = False) -> Any:
        try:
            return await asyncio.to_thread(ydl.extract_info, query, download=download)
        except yt_dlp.utils.DownloadError as e:
            error_msg = str(e).lower()
            if "sign in" in error_msg or "confirm you" in error_msg or "403" in error_msg:
                await self._trigger_cookie_refresh()
                await source_health_tracker.record_failure("youtube", is_critical=True)
                raise BotDetectionError("YouTube Bot Detection triggered")
            raise

    async def search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Search YouTube with circuit breaker protection."""
        if self._circuit_breaker and self._circuit_breaker.is_open:
            logger.debug("YouTube circuit open, skipping search")
            return []

        if not query or not query.strip():
            return []

        # ytsearch{limit}: avoids massive playlists
        search_query = f"ytsearch{min(limit, 20)}:{query.strip()}"

        # Fast search options
        opts = self._base_ydl_opts.copy()
        opts["extract_flat"] = "in_playlist"

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = await self._extract_info(ydl, search_query, download=False)

            if not info or "entries" not in info:
                return []

            results = []
            entries = list(info["entries"])

            for entry in entries:
                if not entry:
                    continue

                video_id = entry.get("id")
                if not video_id:
                    continue

                results.append({
                    "id": video_id,
                    "title": entry.get("title", "Unknown"),
                    "artist": entry.get("uploader", "Unknown Artist"),
                    "duration": entry.get("duration", 0),
                    "thumbnail": f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg",
                    "url": entry.get("url", f"https://www.youtube.com/watch?v={video_id}"),
                    "source": "youtube",
                })

            if results:
                logger.info(
                    f"YouTube search returned {len(results)} results for: {query}")
                await source_health_tracker.record_success("youtube")
                if self._circuit_breaker:
                    await self._circuit_breaker._record_success()
            return results

        except CircuitBreakerOpen:
            logger.debug("YouTube circuit breaker OPEN")
            return []
        except BotDetectionError as e:
            logger.warning(f"YouTube hit bot detection during search: {e}")
            return []
        except Exception as e:
            logger.warning(f"YouTube direct search failed: {e}")
            await source_health_tracker.record_failure("youtube")
            if self._circuit_breaker:
                await self._circuit_breaker._record_failure()
            return []

    async def extract(self, track_id: str) -> Optional[Dict[str, Any]]:
        """Extract stream URL with circuit breaker protection."""
        if self._circuit_breaker and self._circuit_breaker.is_open:
            logger.debug("YouTube circuit open, skipping extract")
            return None

        candidate = (track_id or "").strip()
        if not candidate:
            return None

        video_id = _extract_video_id(candidate)
        if not video_id:
            return None

        url = f"https://www.youtube.com/watch?v={video_id}"

        # Stream extraction requires getting formats
        opts = self._base_ydl_opts.copy()
        opts["extract_flat"] = False

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = await self._extract_info(ydl, url, download=False)

            if not info:
                return None

            stream_url = info.get("url")
            if not stream_url:
                logger.warning(f"No stream URL found directly for: {video_id}")
                return None

            await source_health_tracker.record_success("youtube")
            if self._circuit_breaker:
                await self._circuit_breaker._record_success()

            return {
                "id": video_id,
                "title": info.get("title", "Unknown"),
                "artist": info.get("uploader", "Unknown Artist"),
                "duration": info.get("duration", 0),
                "stream_url": stream_url,
                "url": url,
                "thumbnail": info.get("thumbnail", f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg"),
                "source": "youtube",
                "headers": {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Accept": "*/*",
                    "Accept-Language": "en-US,en;q=0.9",
                },
            }

        except BotDetectionError as e:
            logger.warning(f"YouTube hit bot detection during extract: {e}")
            return None
        except Exception as e:
            logger.warning(f"YouTube direct extract failed: {e}")
            await source_health_tracker.record_failure("youtube")
            if self._circuit_breaker:
                await self._circuit_breaker._record_failure()
            return None


youtube_extractor = YouTubeExtractor()

__all__ = ["YouTubeExtractor", "youtube_extractor"]
