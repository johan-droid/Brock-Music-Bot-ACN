"""YouTube Music extractor via wrapper microservice.

This extractor calls a YouTube wrapper service (running on Render)
to bypass Heroku IP blocks from YouTube.

Environment variables:
    YOUTUBE_API_BASE_URL: URL of the YouTube wrapper service
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional

import aiohttp

from bot.utils.circuit_breaker import CircuitBreakerRegistry, CircuitBreakerOpen, retry_with_backoff, source_health_tracker
from bot.utils.errors import BotDetectionError, format_error_message

logger = logging.getLogger(__name__)

# Export for health check access
YOUTUBE_WRAPPER_BASE_URL = os.getenv(
    "YOUTUBE_API_BASE_URL", "").strip().rstrip("/")

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


class YouTubeWrapperExtractor:
    """YouTube extractor that calls a wrapper microservice.

    The wrapper runs on Render (or elsewhere) to bypass Heroku IP blocks.
    Includes circuit breaker protection and adaptive timeouts.
    """

    def __init__(self) -> None:
        self.base_url = os.getenv(
            "YOUTUBE_API_BASE_URL", "").strip().rstrip("/")
        YOUTUBE_WRAPPER_BASE_URL = self.base_url  # Export for health checks
        if not self.base_url:
            logger.warning(
                "YOUTUBE_API_BASE_URL not set - YouTube wrapper extractor disabled")

        # Adaptive timeout configuration
        self._timeout_config = {
            'initial': 25,      # 25s for cold start
            'healthy': 10,      # 10s when warm
            'circuit_open': 5   # Fast fail when circuit open
        }
        self._last_response_time = None

        # Get circuit breaker
        self._circuit_breaker = CircuitBreakerRegistry.get("youtube_wrapper")

    def _get_timeout(self) -> int:
        """Get adaptive timeout based on service health."""
        if self._circuit_breaker and self._circuit_breaker.is_open:
            return self._timeout_config['circuit_open']

        # If we have fast recent responses, use shorter timeout
        if self._last_response_time and self._last_response_time < 5:
            return self._timeout_config['healthy']

        return self._timeout_config['initial']

    def _headers(self) -> Dict[str, str]:
        return {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
        }

    async def _trigger_cookie_refresh(self):
        """Trigger an out-of-band workflow to refresh cookies via wrapper."""
        logger.warning(
            "Triggering YouTube cookie auto-refresh due to 403 Bot Detection")
        if not self.base_url:
            return

        endpoint = f"{self.base_url}/refresh-cookies"
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
                async with session.post(endpoint) as response:
                    if response.status == 200:
                        logger.info(
                            "Successfully triggered wrapper cookie refresh")
        except Exception as e:
            logger.debug(f"Cookie refresh trigger failed: {e}")

    @retry_with_backoff(retries=2, base_delay=1.0, max_delay=5.0, exceptions=(BotDetectionError,))
    async def _request(self, endpoint: str, params: dict = None) -> Any:
        timeout = aiohttp.ClientTimeout(total=self._get_timeout())
        start_time = time.time()

        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(endpoint, params=params, headers=self._headers()) as response:
                self._last_response_time = time.time() - start_time

                if response.status == 403:
                    await self._trigger_cookie_refresh()
                    await source_health_tracker.record_failure("youtube_wrapper", is_critical=True)
                    raise BotDetectionError(
                        "YouTube returned 403 Bot Detection")

                if response.status >= 400:
                    await source_health_tracker.record_failure("youtube_wrapper")
                    if self._circuit_breaker:
                        await self._circuit_breaker._record_failure()
                    return None

                try:
                    data = await response.json()
                    await source_health_tracker.record_success("youtube_wrapper")
                    if self._circuit_breaker:
                        await self._circuit_breaker._record_success()
                    return data
                except Exception:
                    return None

    async def search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Search YouTube via wrapper service with circuit breaker protection."""
        if not self.base_url:
            logger.warning("YouTube wrapper not configured - skipping search")
            return []

        if self._circuit_breaker and self._circuit_breaker.is_open:
            logger.debug("YouTube wrapper circuit open, skipping search")
            return []

        if not query or not query.strip():
            return []

        endpoint = f"{self.base_url}/search"
        params = {"q": query.strip(), "limit": max(1, min(limit, 20))}

        try:
            data = await self._request(endpoint, params)
            if not isinstance(data, dict):
                return []

            tracks = data.get("data", [])
            results = []

            for track in tracks:
                if not isinstance(track, dict):
                    continue

                video_id = track.get("id")
                if not video_id:
                    continue

                results.append({
                    "id": video_id,
                    "title": track.get("title", "Unknown"),
                    "artist": track.get("artist", "Unknown Artist"),
                    "duration": track.get("duration", 0),
                    "thumbnail": track.get("thumbnail", f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg"),
                    "url": track.get("url", f"https://www.youtube.com/watch?v={video_id}"),
                    "source": "youtube",
                })

            logger.info(
                f"YouTube wrapper search returned {len(results)} results for: {query}")
            return results

        except CircuitBreakerOpen:
            logger.debug("YouTube wrapper circuit breaker OPEN")
            return []
        except BotDetectionError as e:
            logger.warning(f"YouTube wrapper hit bot detection: {e}")
            return []
        except asyncio.TimeoutError:
            logger.warning(f"YouTube wrapper search timed out for: {query}")
            if self._circuit_breaker:
                await self._circuit_breaker._record_failure()
            return []
        except Exception as e:
            logger.warning(f"YouTube wrapper search failed: {e}")
            if self._circuit_breaker:
                await self._circuit_breaker._record_failure()
            return []

    async def extract(self, track_id: str) -> Optional[Dict[str, Any]]:
        """Extract stream URL via wrapper service."""
        if not self.base_url:
            logger.warning("YouTube wrapper not configured - cannot extract")
            return None

        candidate = (track_id or "").strip()
        if not candidate:
            return None

        # Handle full URLs
        video_id = _extract_video_id(candidate)
        if not video_id:
            logger.warning(
                f"Could not extract video ID from: {candidate[:50]}")
            return None

        endpoint = f"{self.base_url}/track/{video_id}"

        try:
            data = await self._request(endpoint)
            if not isinstance(data, dict):
                return None

            stream_url = data.get("stream_url") or data.get("url")
            if not stream_url:
                logger.warning(
                    f"No stream URL in wrapper response for: {video_id}")
                return None

            artist_name = "Unknown Artist"
            artist_data = data.get("artist")
            if isinstance(artist_data, dict):
                artist_name = artist_data.get("name") or artist_name
            elif isinstance(artist_data, str):
                artist_name = artist_data

            return {
                "id": video_id,
                "title": data.get("title", "Unknown"),
                "artist": artist_name,
                "duration": data.get("duration", 0),
                "stream_url": stream_url,
                "url": data.get("url", f"https://www.youtube.com/watch?v={video_id}"),
                "thumbnail": data.get("thumbnail", f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg"),
                "source": "youtube",
                "headers": {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Accept": "*/*",
                    "Accept-Language": "en-US,en;q=0.9",
                },
            }

        except BotDetectionError as e:
            logger.warning(
                f"YouTube wrapper hit bot detection on extract: {e}")
            return None
        except asyncio.TimeoutError:
            logger.warning(
                f"YouTube wrapper extract timed out for: {video_id}")
            return None
        except Exception as e:
            logger.warning(f"YouTube wrapper extract failed: {e}")
            return None


youtube_wrapper_extractor = YouTubeWrapperExtractor()

__all__ = ["YouTubeWrapperExtractor", "youtube_wrapper_extractor"]
