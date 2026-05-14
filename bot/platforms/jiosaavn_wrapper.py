"""JioSaavn Music extractor via wrapper microservice.

This extractor calls a JioSaavn wrapper service (running on Render)
to get Indian/Bollywood music without bot detection issues.

Environment variables:
    JIOSAAVN_API_BASE_URL: URL of the JioSaavn wrapper service
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Dict, List, Optional

import aiohttp

from bot.utils.circuit_breaker import CircuitBreakerRegistry, CircuitBreakerOpen, retry_with_backoff, source_health_tracker
from bot.utils.errors import PreviewOnlyError

logger = logging.getLogger(__name__)

# Get wrapper URL from env
JIOSAAVN_API_BASE_URL = os.getenv("JIOSAAVN_API_BASE_URL", "")


class JioSaavnWrapperExtractor:
    """Extract music from JioSaavn via wrapper service with circuit breaker protection."""

    def __init__(self):
        self.enabled = bool(JIOSAAVN_API_BASE_URL)
        self.base_url = JIOSAAVN_API_BASE_URL.rstrip(
            "/") if JIOSAAVN_API_BASE_URL else ""

        # Adaptive timeout configuration
        self._timeout_config = {
            'initial': 60,      # 60s for Render free-tier cold start
            'healthy': 15,      # 15s when warm
            'circuit_open': 5   # Fast fail when circuit open
        }
        self._last_success_time = 0.0
        self._last_response_time = None

        # Get circuit breaker
        self._circuit_breaker = CircuitBreakerRegistry.get("jiosaavn_wrapper")

        if self.enabled:
            logger.info(f"JioSaavn wrapper initialized: {self.base_url}")
        else:
            logger.warning(
                "JioSaavn wrapper not configured - set JIOSAAVN_API_BASE_URL")

    def _get_timeout(self) -> int:
        """Get adaptive timeout based on service health and activity gaps."""
        if self._circuit_breaker and self._circuit_breaker.is_open:
            return self._timeout_config['circuit_open']

        # Render free tier spins down after 15 mins. Use long timeout if gap is large.
        gap = time.time() - self._last_success_time
        if gap > 840:  # 14 minutes
            logger.info(f"JioSaavn wrapper potentially cold (last activity: {int(gap)}s ago). Using {self._timeout_config['initial']}s timeout.")
            return self._timeout_config['initial']

        # If we have fast recent responses, use healthy timeout
        if self._last_response_time and self._last_response_time < 5:
            return self._timeout_config['healthy']

        return self._timeout_config['initial']

    @retry_with_backoff(retries=2, base_delay=1.0, max_delay=5.0)
    async def _request(self, endpoint: str) -> Optional[Dict[str, Any]]:
        if not self.enabled:
            return None

        url = f"{self.base_url}{endpoint}"
        timeout = aiohttp.ClientTimeout(total=self._get_timeout())
        start_time = time.time()

        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as response:
                self._last_response_time = time.time() - start_time

                if response.status >= 400:
                    logger.warning(
                        f"JioSaavn wrapper returned HTTP {response.status}")
                    await source_health_tracker.record_failure("jiosaavn_wrapper")
                    if self._circuit_breaker:
                        await self._circuit_breaker._record_failure()
                    return None

                data = await response.json()
                self._last_success_time = time.time()

                # Check for errors in the payload
                if data.get("error"):
                    logger.warning(
                        f"JioSaavn wrapper error: {data.get('error')}")
                    await source_health_tracker.record_failure("jiosaavn_wrapper")
                    if self._circuit_breaker:
                        await self._circuit_breaker._record_failure()
                    return None

                await source_health_tracker.record_success("jiosaavn_wrapper")
                if self._circuit_breaker:
                    await self._circuit_breaker._record_success()

                return data

    async def search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Search JioSaavn via wrapper with circuit breaker protection."""
        if not self.enabled:
            return []

        if self._circuit_breaker and self._circuit_breaker.is_open:
            logger.debug("JioSaavn wrapper circuit open, skipping search")
            return []

        try:
            result = await self._request(f"/search?q={query}")
            if not result or not isinstance(result, dict):
                return []

            tracks = result.get("data", [])
            if not tracks:
                return []

            logger.info(
                f"JioSaavn wrapper search returned {len(tracks)} results for: {query}")
            return tracks

        except CircuitBreakerOpen:
            logger.warning("JioSaavn wrapper circuit breaker OPEN")
            return []
        except Exception as e:
            logger.error(f"JioSaavn wrapper search failed: {e}")
            await source_health_tracker.record_failure("jiosaavn_wrapper")
            return []

    async def extract(self, track_id: str) -> Optional[Dict[str, Any]]:
        """Get song details and stream URL by ID with circuit breaker protection."""
        if not self.enabled:
            return None

        if self._circuit_breaker and self._circuit_breaker.is_open:
            logger.debug("JioSaavn wrapper circuit open, skipping extract")
            return None

        try:
            result = await self._request(f"/track/{track_id}")
            if not result:
                return None

            stream_url = result.get("stream_url")

            if stream_url and "jiotunepreview" in stream_url.lower():
                logger.warning(
                    f"JioSaavn wrapper returned a preview URL for track {track_id}")
                raise PreviewOnlyError("JioSaavn stream is only a preview.")

            # Handle both artist object and string formats
            artist = result.get("artist")
            if isinstance(artist, dict):
                artist_name = artist.get("name", "Unknown Artist")
            elif isinstance(artist, str):
                artist_name = artist
            else:
                artist_name = "Unknown Artist"

            return {
                "id": str(track_id),
                "title": result.get("title", "Unknown"),
                "artist": artist_name,
                "duration": result.get("duration", 0),
                "stream_url": stream_url,
                "thumbnail": result.get("thumbnail", ""),
                "url": result.get("url", ""),
                "source": "jiosaavn"
            }

        except PreviewOnlyError:
            raise
        except CircuitBreakerOpen:
            logger.warning("JioSaavn wrapper circuit breaker OPEN")
            return None
        except Exception as e:
            logger.error(f"JioSaavn wrapper extract failed: {e}")
            await source_health_tracker.record_failure("jiosaavn_wrapper")
            return None


# Global extractor instance
jiosaavn_wrapper_extractor = JioSaavnWrapperExtractor()
