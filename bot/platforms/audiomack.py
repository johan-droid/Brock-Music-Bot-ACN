"""
Audiomack audio extraction — very bot-friendly, minimal CDN blocking.
"""

import asyncio
import logging
import os
from typing import Optional, Dict, Any

import yt_dlp

logger = logging.getLogger(__name__)

# ─── Concurrency guard ────────────────────────────────────────────────────────
_EXTRACT_SEMAPHORE = asyncio.Semaphore(2)

# ─── Format selection ─────────────────────────────────────────────────────────
# Audiomack uses MP3 mostly.
_FORMAT = "bestaudio/best"

class AudiomackExtractor:
    """Audiomack specific extractor using yt-dlp."""

    def _extract_sync(self, query: str) -> Optional[Dict[str, Any]]:
        """Run yt-dlp synchronously in a thread pool."""
        opts = {
            "format": _FORMAT,
            "quiet": True,
            "no_warnings": True,
            "extract_flat": False,
            "noplaylist": True,
            "geo_bypass": True,
        }
        
        # Prepend search if not a URL
        if not any(query.startswith(p) for p in ("http://", "https://", "audiomack")):
            query = f"https://audiomack.com/search?q={query}"

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(query, download=False)
                
                if info and "entries" in info:
                    entries = [e for e in info["entries"] if e]
                    if not entries: return None
                    info = entries[0]
                
                if not info: return None

                return {
                    "url": info.get("url"),
                    "title": info.get("title", "Unknown"),
                    "duration": int(info.get("duration") or 0),
                    "thumbnail": info.get("thumbnail"),
                    "uploader": info.get("uploader") or info.get("artist", "Unknown Artist"),
                    "source": "audiomack",
                    "id": info.get("id", ""),
                }
        except Exception as e:
            logger.debug(f"Audiomack extraction error: {e}")
            return None

    async def extract(self, query: str) -> Optional[Dict[str, Any]]:
        async with _EXTRACT_SEMAPHORE:
            loop = asyncio.get_event_loop()
            try:
                return await asyncio.wait_for(
                    loop.run_in_executor(None, self._extract_sync, query),
                    timeout=30.0
                )
            except Exception as e:
                logger.error(f"Audiomack extraction failed: {e}")
                return None

    def _search_sync(self, query: str, limit: int) -> list:
        """Search Audiomack for results."""
        opts = {
            "extract_flat": True,
            "quiet": True,
            "playlist_items": f"1-{limit}",
        }
        search_query = f"ytsearch{limit}:audiomack {query}"
        
        results = []
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(search_url, download=False)
                for entry in (info or {}).get("entries", []):
                    if not entry: continue
                    results.append({
                        "title": entry.get("title", "Unknown"),
                        "duration": int(entry.get("duration") or 0),
                        "thumbnail": entry.get("thumbnail"),
                        "uploader": entry.get("uploader") or entry.get("artist", "Unknown Artist"),
                        "id": entry.get("id", ""),
                        "url": entry.get("webpage_url") or f"https://audiomack.com/song/{entry.get('id', '')}",
                        "source": "audiomack",
                    })
        except Exception as e:
            logger.error(f"Audiomack search error: {e}")
        return results[:limit]

    async def search(self, query: str, limit: int = 5) -> list:
        loop = asyncio.get_event_loop()
        try:
            return await asyncio.wait_for(
                loop.run_in_executor(None, self._search_sync, query, limit),
                timeout=20.0
            )
        except Exception:
            return []

audiomack = AudiomackExtractor()
