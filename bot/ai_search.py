import aiohttp
import asyncio
import logging
from typing import List, Dict, Any, Tuple

logger = logging.getLogger(__name__)

# Very basic dictionary mapping words to Jamendo tags
KEYWORD_TO_TAG = {
    "chill": "mood:chill",
    "relax": "mood:relaxing",
    "calm": "mood:calm",
    "workout": "mood:energetic",
    "gym": "mood:energetic",
    "energy": "mood:energetic",
    "sad": "mood:sad",
    "happy": "mood:happy",
    "focus": "mood:focus",
    "study": "mood:focus",
    "party": "mood:party",
    "dance": "genre:dance",
    "rock": "genre:rock",
    "pop": "genre:pop",
    "jazz": "genre:jazz",
    "classical": "genre:classical",
    "electronic": "genre:electronic",
    "ambient": "genre:ambient",
    "acoustic": "instrument:acoustic",
    "guitar": "instrument:guitar",
    "piano": "instrument:piano",
}

JAMENDO_CLIENT_ID = "b6747d04"  # Jamendo default test client ID
JAMENDO_API_URL = "https://api.jamendo.com/v3.0/tracks/"

class JamendoVibeSearch:
    def __init__(self):
        self._cache: Dict[str, List[Dict[str, Any]]] = {}

    def extract_tags(self, query: str) -> List[str]:
        """Extract tags from a natural language query using simple keyword matching."""
        words = query.lower().split()
        tags = set()
        for word in words:
            if word in KEYWORD_TO_TAG:
                tags.add(KEYWORD_TO_TAG[word])

        # Strip prefixes for jamendo tags parameter (e.g. "mood:chill" -> "chill")
        # Jamendo allows searching just by the tag name
        return [t.split(":")[-1] if ":" in t else t for t in tags]

    async def search_by_tags(self, tags: List[str], limit: int = 5) -> List[Dict[str, Any]]:
        if not tags:
            return []

        tags_str = "+".join(tags)

        if tags_str in self._cache:
            return self._cache[tags_str]

        params = {
            "client_id": JAMENDO_CLIENT_ID,
            "format": "json",
            "limit": limit,
            "tags": tags_str,
            "include": "musicinfo",
            "audioformat": "mp32"
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(JAMENDO_API_URL, params=params, timeout=10) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        results = data.get("results", [])

                        # Format to internal Track-like dict
                        tracks = []
                        for item in results:
                            tracks.append({
                                "title": item.get("name", "Unknown Title"),
                                "artist": item.get("artist_name", "Unknown Artist"),
                                "duration": int(item.get("duration", 0)),
                                "stream_url": item.get("audio", ""),
                                "thumbnail": item.get("image", ""),
                                "source": "jamendo",
                                "track_id": str(item.get("id", ""))
                            })

                        self._cache[tags_str] = tracks
                        return tracks
                    else:
                        logger.error(f"Jamendo API returned status {resp.status}")
                        return []
        except Exception as e:
            logger.error(f"Error fetching from Jamendo: {e}")
            return []

vibe_search = JamendoVibeSearch()
