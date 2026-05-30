import aiohttp
import asyncio
import os
from typing import List, Dict, Any, Optional
from bot.utils.resilience import with_retries_and_cb, jamendo_cb
class Track:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)
import logging

logger = logging.getLogger(__name__)

JAMENDO_CLIENT_ID = os.getenv("JAMENDO_CLIENT_ID", "")
JAMENDO_API_BASE = "https://api.jamendo.com/v3.0"

_cache = {}

class JamendoClient:

    @staticmethod
    @with_retries_and_cb(jamendo_cb, max_retries=5, timeout=8)
    async def _make_request(endpoint: str, params: dict) -> dict:
        params['client_id'] = JAMENDO_CLIENT_ID
        params['format'] = 'jsonpretty'

        cache_key = f"{endpoint}:{str(params)}"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{JAMENDO_API_BASE}/{endpoint}", params=params) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        _cache[cache_key] = data # Cache success
                        return data
                    elif resp.status == 429:
                        # Rate limit
                        raise Exception(f"Jamendo Rate Limit 429")
                    elif resp.status >= 500:
                        raise Exception(f"Jamendo Server Error {resp.status}")
                    else:
                        resp.raise_for_status()
        except Exception as e:
            if cache_key in _cache:
                logger.warning(f"Using cached result for {endpoint} due to error: {e}")
                return _cache[cache_key]
            raise e

    @classmethod
    async def search(cls, query: str, limit: int = 5) -> List[Track]:
        if not JAMENDO_CLIENT_ID:
            logger.warning("JAMENDO_CLIENT_ID not set")
            return []

        try:
            data = await cls._make_request("tracks/", {"search": query, "limit": limit})
            results = data.get("results", [])
            tracks = []
            for item in results:
                tracks.append(Track(
                    track_id=item["id"],
                    title=item["name"],
                    artist=item.get("artist_name", "Unknown"),
                    duration=item.get("duration", 0),
                    stream_url=item.get("audio", ""),
                    thumbnail=item.get("image", ""),
                    source="jamendo"
                ))
            return tracks
        except Exception as e:
            logger.error(f"Jamendo search failed: {e}")
            return []

    @classmethod
    async def extract(cls, track_id: str) -> Optional[Dict[str, Any]]:
        if not JAMENDO_CLIENT_ID:
            return None

        try:
            data = await cls._make_request("tracks/", {"id": track_id})
            results = data.get("results", [])
            if not results:
                return None

            item = results[0]
            return {
                "id": item["id"],
                "title": item["name"],
                "artist": item.get("artist_name", "Unknown"),
                "duration": item.get("duration", 0),
                "url": item.get("audio", ""),
                "thumbnail": item.get("image", ""),
                "source": "jamendo",
                "headers": {}
            }
        except Exception as e:
            logger.error(f"Jamendo extract failed: {e}")
            return None
