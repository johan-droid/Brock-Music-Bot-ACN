"""Lightweight mood-query extraction for microservice-backed search."""

import logging
from typing import Any, Dict, List

from bot.core.music_backend import music_backend

logger = logging.getLogger(__name__)

# Maps natural-language vibe words to search hint tokens.
KEYWORD_TO_TAG = {
    "chill": "chill",
    "relax": "relaxing",
    "calm": "calm",
    "workout": "energetic",
    "gym": "energetic",
    "energy": "energetic",
    "sad": "sad",
    "happy": "happy",
    "focus": "focus",
    "study": "focus",
    "party": "party",
    "dance": "dance",
    "rock": "rock",
    "pop": "pop",
    "jazz": "jazz",
    "classical": "classical",
    "electronic": "electronic",
    "ambient": "ambient",
    "acoustic": "acoustic",
    "guitar": "guitar",
    "piano": "piano",
}


class VibeSearch:
    def __init__(self):
        self._cache: Dict[str, List[Dict[str, Any]]] = {}

    def extract_tags(self, query: str) -> List[str]:
        """Extract vibe tags from natural language query."""
        words = (query or "").lower().split()
        tags = []
        seen = set()
        for word in words:
            token = KEYWORD_TO_TAG.get(word)
            if not token or token in seen:
                continue
            seen.add(token)
            tags.append(token)
        return tags

    async def search_by_tags(self, tags: List[str], limit: int = 5) -> List[Dict[str, Any]]:
        if not tags:
            return []

        tags_str = "+".join(tags)
        if tags_str in self._cache:
            return self._cache[tags_str]

        query = " ".join(tags)
        try:
            tracks = await music_backend.search(query, limit=limit)
        except Exception as exc:
            logger.error("Vibe search failed for tags=%s: %s", tags, exc)
            return []

        results = [track.to_dict() for track in tracks]
        self._cache[tags_str] = results
        return results


vibe_search = VibeSearch()
