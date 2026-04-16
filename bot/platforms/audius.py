import aiohttp
import random
import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)


class AudiusExtractor:
    """
    Open-source decentralized music database integration.
    Bypasses traditional CDN restrictions by utilizing distributed nodes.
    """

    def __init__(self):
        self.app_name = "JohanDroid_MusicBot"
        self.host_url = None

    async def _get_api_host(self) -> str:
        """Audius uses decentralized nodes. We query the main API to find an active node."""
        if self.host_url:
            return self.host_url

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get("https://api.audius.co") as response:
                    data = await response.json()
                    self.host_url = random.choice(data.get("data", []))
                    return self.host_url
        except Exception as e:
            logger.error(f"Failed to fetch Audius nodes: {e}")
            return "https://discoveryprovider.audius.co"

    async def search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Sends the search request to the open database and receives structured data."""
        host = await self._get_api_host()
        url = f"{host}/v1/tracks/search"

        params = {
            "query": query,
            "app_name": self.app_name,
            "limit": limit,
        }

        results = []
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        tracks_data = data.get("data", [])

                        for item in tracks_data:
                            stream_url = f"{host}/v1/tracks/{item['id']}/stream?app_name={self.app_name}"
                            results.append({
                                "id": item.get("id"),
                                "title": item.get("title", "Unknown"),
                                "artist": item.get("user", {}).get("name", "Unknown Artist"),
                                "duration": item.get("duration", 0),
                                "url": stream_url,
                                "thumbnail": item.get("artwork", {}).get("480x480"),
                            })
        except Exception as e:
            logger.error(f"Audius search failed: {e}")

        return results

    async def extract(self, track_id: str) -> Dict[str, Any]:
        """Direct extraction method for fallback chains."""
        host = await self._get_api_host()
        return {
            "url": f"{host}/v1/tracks/{track_id}/stream?app_name={self.app_name}",
            "source": "audius",
        }


audius = AudiusExtractor()
