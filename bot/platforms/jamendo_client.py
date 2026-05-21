import os
import time
import logging
import asyncio
import aiohttp
from typing import List, Dict, Optional, Any

from bot.platforms.jamendo_embedded import DEFAULT_JAMENDO_CLIENT_ID, JamendoEmbedded

logger = logging.getLogger(__name__)

class JamendoClient:
    """Jamendo API Client for searching and fetching tracks."""

    BASE_URL = "https://api.jamendo.com/v3.0/"

    def __init__(self):
        self.client_id = os.environ.get("JAMENDO_CLIENT_ID") or DEFAULT_JAMENDO_CLIENT_ID
        self.test_mode = os.environ.get("TEST_MODE", "").lower() in ("1", "true", "yes")
        self.embedded = JamendoEmbedded(client_id=self.client_id)

        # TTL Cache structure: { cache_key: {"data": value, "expiry": timestamp} }
        self._cache: Dict[str, Dict[str, Any]] = {}
        self.cache_ttl = 300  # 5 minutes

    async def _request(self, endpoint: str, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Make an async HTTP request to the Jamendo API."""
        params["client_id"] = self.client_id
        params["format"] = "jsonpretty"

        url = f"{self.BASE_URL.rstrip('/')}/{endpoint.lstrip('/')}"

        timeout = aiohttp.ClientTimeout(total=10)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, params=params) as response:
                    if response.status != 200:
                        logger.error(f"Jamendo API returned status {response.status} for URL {url}")
                        return None
                    return await response.json()
        except asyncio.TimeoutError:
            logger.error(f"Jamendo API request to {url} timed out after 10 seconds.")
            return None
        except Exception as e:
            logger.error(f"Error fetching from Jamendo API: {e}")
            return None

    def _get_mock_track(self, track_id: str) -> Dict[str, Any]:
        """Return a mock track dict for testing."""
        return {
            "id": int(track_id) if str(track_id).isdigit() else 12345,
            "title": f"Mock Track {track_id}",
            "artist": "Mock Artist",
            "audio_url": "https://example.com/mock_audio.mp3",
            "thumbnail_url": "https://example.com/mock_thumbnail.jpg",
            "duration": 180
        }

    async def search_tracks(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Search for tracks on Jamendo."""
        if self.test_mode:
            logger.info(f"TEST_MODE is enabled. Returning mock data for query: {query}")
            return [self._get_mock_track(str(i)) for i in range(1, min(limit, 5) + 1)]

        # Check cache
        cache_key = f"search_{query}_{limit}"
        now = time.time()
        if cache_key in self._cache:
            cache_entry = self._cache[cache_key]
            if now < cache_entry["expiry"]:
                return cache_entry["data"]
            else:
                del self._cache[cache_key]

        params = {
            "search": query,
            "limit": limit
        }

        response_data = await self._request("tracks/", params)
        if not response_data or "results" not in response_data:
            return await self.embedded.search_tracks(query, limit)

        results = []
        for track in response_data.get("results", []):
            try:
                results.append({
                    "id": track.get("id"),
                    "title": track.get("name", ""),
                    "artist": track.get("artist_name", ""),
                    "audio_url": track.get("audio", ""),
                    "thumbnail_url": track.get("album_image", ""),
                    "duration": int(track.get("duration", 0))
                })
            except Exception as e:
                logger.warning(f"Failed to parse track data: {e}")

        # Save to cache
        self._cache[cache_key] = {
            "data": results,
            "expiry": now + self.cache_ttl
        }

        return results

    async def get_track_by_id(self, track_id: int) -> Optional[Dict[str, Any]]:
        """Get a specific track by its ID from Jamendo."""
        if self.test_mode:
            logger.info(f"TEST_MODE is enabled. Returning mock data for track_id: {track_id}")
            return self._get_mock_track(str(track_id))

        # Check cache
        cache_key = f"track_{track_id}"
        now = time.time()
        if cache_key in self._cache:
            cache_entry = self._cache[cache_key]
            if now < cache_entry["expiry"]:
                return cache_entry["data"]
            else:
                del self._cache[cache_key]

        params = {
            "id": track_id
        }

        response_data = await self._request("tracks/", params)
        if not response_data or "results" not in response_data or not response_data["results"]:
            return await self.embedded.get_track_by_id(track_id)

        track = response_data["results"][0]
        try:
            result = {
                "id": track.get("id"),
                "title": track.get("name", ""),
                "artist": track.get("artist_name", ""),
                "audio_url": track.get("audio", ""),
                "thumbnail_url": track.get("album_image", ""),
                "duration": int(track.get("duration", 0))
            }

            # Save to cache
            self._cache[cache_key] = {
                "data": result,
                "expiry": now + self.cache_ttl
            }

            return result
        except Exception as e:
            logger.warning(f"Failed to parse track data: {e}")
            return None
