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
from typing import Any, Dict, List, Optional

import aiohttp

logger = logging.getLogger(__name__)

# Get wrapper URL from env
JIOSAAVN_API_BASE_URL = os.getenv("JIOSAAVN_API_BASE_URL", "")


class JioSaavnWrapperExtractor:
    """Extract music from JioSaavn via wrapper service."""

    def __init__(self):
        self.enabled = bool(JIOSAAVN_API_BASE_URL)
        self.base_url = JIOSAAVN_API_BASE_URL.rstrip("/") if JIOSAAVN_API_BASE_URL else ""
        if self.enabled:
            logger.info(f"JioSaavn wrapper initialized: {self.base_url}")
        else:
            logger.warning("JioSaavn wrapper not configured - set JIOSAAVN_API_BASE_URL")

    async def _request(self, endpoint: str, params: dict = None) -> Optional[dict]:
        """Make request to wrapper service."""
        if not self.enabled or not self.base_url:
            return None

        url = f"{self.base_url}{endpoint}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    logger.warning(f"JioSaavn wrapper returned {resp.status}")
                    return None
        except Exception as e:
            logger.error(f"JioSaavn wrapper request failed: {e}")
            return None

    async def search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Search for songs on JioSaavn."""
        if not self.enabled:
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

        except Exception as e:
            logger.error(f"JioSaavn wrapper search failed: {e}")
            return []

    async def extract(self, track_id: str) -> Optional[Dict[str, Any]]:
        """Get song details and stream URL by ID."""
        if not self.enabled:
            return None

        try:
            result = await self._request(f"/track/{track_id}")
            if not result:
                return None

            return {
                "id": str(track_id),
                "title": result.get("title", "Unknown"),
                "artist": result.get("artist", {}).get("name", "Unknown Artist") if isinstance(result.get("artist"), dict) else result.get("artist", "Unknown Artist"),
                "duration": result.get("duration", 0),
                "stream_url": result.get("stream_url"),
                "thumbnail": result.get("thumbnail", ""),
                "url": result.get("url", ""),
                "source": "jiosaavn"
            }

        except Exception as e:
            logger.error(f"JioSaavn wrapper extract failed: {e}")
            return None


# Global extractor instance
jiosaavn_wrapper_extractor = JioSaavnWrapperExtractor()
