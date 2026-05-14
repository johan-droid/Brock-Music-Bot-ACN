import aiohttp
import logging
import random
from typing import List, Dict, Any, Optional
from config import config

logger = logging.getLogger(__name__)

class JamendoClient:
    """Client for fetching tracks from Jamendo API for Song Hunter."""

    BASE_URL = "https://api.jamendo.com/v3.0/tracks"

    def __init__(self, client_id: Optional[str] = None):
        self.client_id = client_id or getattr(config, 'JAMENDO_CLIENT_ID', 'b6747d04')

    async def get_random_tracks(self, limit: int = 5, genre: Optional[str] = None) -> List[Dict[str, Any]]:
        params = {
            "client_id": self.client_id,
            "format": "json",
            "limit": limit,
            "boost": "random",
            "hasimage": "true",
            "audioformat": "mp32"
        }

        if genre:
            params["tags"] = genre

        offset = random.randint(0, 100)
        params["offset"] = offset

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.BASE_URL, params=params, timeout=10) as response:
                    if response.status == 200:
                        data = await response.json()
                        if "results" in data:
                            return data["results"]
                    else:
                        text = await response.text()
                        logger.error(f"Jamendo API error: {response.status} - {text}")
        except Exception as e:
            logger.error(f"Failed to fetch from Jamendo: {e}")

        return []

jamendo_client = JamendoClient()
