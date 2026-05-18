import aiohttp
import os
import logging

logger = logging.getLogger(__name__)

class JamendoClient:
    def __init__(self, client_id=None):
        self.client_id = client_id or os.environ.get("JAMENDO_CLIENT_ID", "56d30c95")
        self.base_url = "https://api.jamendo.com/v3.0"

    async def search_tracks(self, query, limit=5):
        url = f"{self.base_url}/tracks/"
        params = {
            "client_id": self.client_id,
            "format": "json",
            "limit": limit,
            "search": query,
            "include": "musicinfo"
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        results = data.get("results", [])
                        tracks = []
                        for item in results:
                            # Standard Jamendo v3 API track schema
                            # The API returns: id, name, duration, artist_name, album_image, audio, audiodownload
                            tracks.append({
                                "id": str(item.get("id", "")),
                                "track_id": str(item.get("id", "")),
                                "title": item.get("name", "Unknown Title"),
                                "artist": item.get("artist_name", "Unknown Artist"),
                                "duration": item.get("duration", 0),
                                "thumbnail": item.get("album_image", ""),
                                "stream_url": item.get("audio") or item.get("audiodownload", ""),
                                "source": "jamendo"
                            })
                        return tracks
                    else:
                        logger.error(f"Jamendo API error: HTTP {response.status}")
                        return []
        except Exception as e:
            logger.error(f"Jamendo request failed: {e}")
            return []

jamendo_client = JamendoClient()
