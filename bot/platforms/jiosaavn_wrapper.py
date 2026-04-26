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

from bot.utils.circuit_breaker import CircuitBreakerRegistry, CircuitBreakerOpen

logger = logging.getLogger(__name__)

# Get wrapper URL from env
JIOSAAVN_API_BASE_URL = os.getenv("JIOSAAVN_API_BASE_URL", "")


class JioSaavnWrapperExtractor:
    """Extract music from JioSaavn via wrapper service with circuit breaker protection."""

    def __init__(self):
        self.enabled = bool(JIOSAAVN_API_BASE_URL)
        self.base_url = JIOSAAVN_API_BASE_URL.rstrip("/") if JIOSAAVN_API_BASE_URL else ""
        
        # Adaptive timeout configuration
        self._timeout_config = {
            'initial': 35,      # 35s for cold start
            'healthy': 12,      # 12s when warm
            'circuit_open': 5   # Fast fail when circuit open
        }
        self._consecutive_successes = 0
        self._last_response_time = None
        
        # Get circuit breaker
        self._circuit_breaker = CircuitBreakerRegistry.get("jiosaavn_wrapper")
        
        if self.enabled:
            logger.info(f"JioSaavn wrapper initialized: {self.base_url}")
        else:
            logger.warning("JioSaavn wrapper not configured - set JIOSAAVN_API_BASE_URL")
    
    def _get_timeout(self) -> int:
        """Get adaptive timeout based on service health."""
        if self._circuit_breaker and self._circuit_breaker.is_open:
            return self._timeout_config['circuit_open']
        
        # If we have fast recent responses, use shorter timeout
        if self._last_response_time and self._last_response_time < 5:
            return self._timeout_config['healthy']
        
        # Default to initial timeout for cold start protection
        return self._timeout_config['initial']

    async def _request(self, endpoint: str, params: dict = None) -> Optional[dict]:
        """Make request to wrapper service with circuit breaker protection."""
        if not self.enabled or not self.base_url:
            return None
        
        # Check circuit breaker
        if self._circuit_breaker and self._circuit_breaker.is_open:
            logger.warning("JioSaavn wrapper circuit breaker is OPEN, skipping request")
            return None

        url = f"{self.base_url}{endpoint}"
        timeout = self._get_timeout()
        start_time = time.time()
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, 
                    params=params, 
                    timeout=aiohttp.ClientTimeout(total=timeout)
                ) as resp:
                    response_time = time.time() - start_time
                    self._last_response_time = response_time
                    
                    if resp.status == 200:
                        data = await resp.json()
                        # Record success for circuit breaker
                        if self._circuit_breaker:
                            await self._circuit_breaker._record_success()
                        self._consecutive_successes += 1
                        return data
                    
                    logger.warning(f"JioSaavn wrapper returned HTTP {resp.status} for {url}")
                    # Record failure for circuit breaker
                    if self._circuit_breaker:
                        await self._circuit_breaker._record_failure()
                    return None
                    
        except asyncio.TimeoutError:
            response_time = time.time() - start_time
            logger.error(f"JioSaavn wrapper timeout ({timeout}s, response took {response_time:.1f}s): {url}")
            if self._circuit_breaker:
                await self._circuit_breaker._record_failure()
            return None
        except Exception as e:
            logger.error(f"JioSaavn wrapper request failed: {type(e).__name__}: {e}")
            if self._circuit_breaker:
                await self._circuit_breaker._record_failure()
            return None

    async def search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Search for songs on JioSaavn with circuit breaker protection."""
        if not self.enabled:
            return []
        
        if self._circuit_breaker and self._circuit_breaker.is_open:
            logger.debug("JioSaavn wrapper circuit open, skipping search")
            return []

        try:
            result = await self._request("/search", {"q": query, "limit": limit})
            if not result or not result.get("data"):
                return []

            tracks = []
            for item in result["data"]:
                tracks.append({
                    "id": str(item.get("id", "")),
                    "title": item.get("title", "Unknown"),
                    "artist": item.get("artist", "Unknown Artist"),
                    "duration": item.get("duration", 0),
                    "thumbnail": item.get("thumbnail", ""),
                    "url": item.get("url", ""),
                    "stream_url": item.get("stream_url"),
                    "source": "jiosaavn"
                })

            logger.info(f"JioSaavn wrapper search returned {len(tracks)} results for: {query}")
            return tracks

        except CircuitBreakerOpen:
            logger.warning("JioSaavn wrapper circuit breaker OPEN")
            return []
        except Exception as e:
            logger.error(f"JioSaavn wrapper search failed: {e}")
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
                "stream_url": result.get("stream_url"),
                "thumbnail": result.get("thumbnail", ""),
                "url": result.get("url", ""),
                "source": "jiosaavn"
            }

        except CircuitBreakerOpen:
            logger.warning("JioSaavn wrapper circuit breaker OPEN")
            return None
        except Exception as e:
            logger.error(f"JioSaavn wrapper extract failed: {e}")
            return None


# Global extractor instance
jiosaavn_wrapper_extractor = JioSaavnWrapperExtractor()
