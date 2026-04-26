"""
JioSaavn music extractor for Indian music
Uses the public JioSaavn API (unofficial)
"""

import logging
import aiohttp
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# JioSaavn API endpoints (unofficial)
JIOSAAVN_BASE = "https://www.jiosaavn.com/api.php"


class JioSaavnExtractor:
    """Extract music from JioSaavn - Best for Indian/Bollywood music"""

    def __init__(self):
        self.enabled = True
        logger.info("JioSaavn extractor initialized")

    async def _make_request(self, params: dict) -> Optional[dict]:
        """Make request to JioSaavn API"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(JIOSAAVN_BASE, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    logger.warning(f"JioSaavn API returned {resp.status}")
                    return None
        except Exception as e:
            logger.error(f"JioSaavn request failed: {e}")
            return None

    async def search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Search for songs on JioSaavn"""
        try:
            params = {
                "__call": "search.getResults",
                "q": query,
                "n": limit,
                "p": 1,
                "_format": "json",
                "_marker": 0,
                "api_version": 4,
                "ctx": "web6dot0",
                "cat": "songs"
            }

            result = await self._make_request(params)
            if not result or "results" not in result:
                return []

            tracks = []
            for item in result["results"]:
                if not isinstance(item, dict):
                    continue

                track_id = item.get("id")
                if not track_id:
                    continue

                tracks.append({
                    "id": str(track_id),
                    "title": item.get("title", "Unknown"),
                    "artist": item.get("primary_artists", "Unknown Artist"),
                    "duration": self._parse_duration(item.get("duration", "0:00")),
                    "thumbnail": item.get("image", "").replace("150x150", "500x500"),
                    "source": "jiosaavn",
                    "url": f"https://www.jiosaavn.com/song/{item.get('perma_url', '')}"
                })

            logger.info(f"JioSaavn search returned {len(tracks)} results for: {query}")
            return tracks

        except Exception as e:
            logger.error(f"JioSaavn search failed: {e}")
            return []

    async def extract(self, track_id: str) -> Optional[Dict[str, Any]]:
        """Get song details and streaming URL"""
        try:
            params = {
                "__call": "song.getDetails",
                "pids": track_id,
                "_format": "json",
                "_marker": 0,
                "api_version": 4,
                "ctx": "web6dot0"
            }

            result = await self._make_request(params)
            if not result or "songs" not in result:
                return None

            songs = result["songs"]
            if not songs:
                return None

            song = songs[0]

            # Get highest quality audio URL
            media_url = song.get("media_preview_url", "")
            if not media_url:
                # Try to generate from encrypted media URL
                media_url = self._decrypt_media_url(song.get("encrypted_media_url", ""))

            return {
                "id": str(track_id),
                "title": song.get("title", "Unknown"),
                "artist": song.get("primary_artists", "Unknown Artist"),
                "duration": self._parse_duration(song.get("duration", "0:00")),
                "stream_url": media_url,
                "thumbnail": song.get("image", "").replace("150x150", "500x500"),
                "source": "jiosaavn"
            }

        except Exception as e:
            logger.error(f"JioSaavn extract failed: {e}")
            return None

    def _parse_duration(self, duration_str: str) -> int:
        """Parse duration string to seconds"""
        try:
            parts = duration_str.split(":")
            if len(parts) == 2:
                return int(parts[0]) * 60 + int(parts[1])
            elif len(parts) == 3:
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
            return 0
        except:
            return 0

    def _decrypt_media_url(self, encrypted_url: str) -> str:
        """Decrypt JioSaavn media URL (simplified)"""
        # This is a placeholder - actual decryption requires more complex logic
        # For now, return preview URL if available
        return encrypted_url


# Global extractor instance
jiosaavn_extractor = JioSaavnExtractor()
