"""
YouTube Music audio extraction — optimized for official music tracks.
"""

import asyncio
import logging
import os
import re
from typing import Optional, Dict, Any

import yt_dlp

logger = logging.getLogger(__name__)

# ─── Concurrency guard ────────────────────────────────────────────────────────
_EXTRACT_SEMAPHORE = asyncio.Semaphore(2)

# ─── Format selection ─────────────────────────────────────────────────────────
# YT Music normally uses Opus/AAC
_FORMAT = "bestaudio/best"

_COOKIES_PATH = "./cookies.txt"

class YTMusicExtractor:
    """YouTube Music specific extractor."""

    def _extract_sync(self, query: str) -> Optional[Dict[str, Any]]:
        """Run yt-dlp synchronously in a thread pool."""
        opts = {
            "format": _FORMAT,
            "quiet": True,
            "no_warnings": True,
            "extract_flat": False,
            "noplaylist": True,
            "geo_bypass": True,
            "extractor_args": {
                "youtube": {
                    "player_client": ["android", "web"],
                    "player_skip": ["webpage", "configs"],
                }
            },
        }
        
        if os.path.exists(_COOKIES_PATH):
            opts["cookiefile"] = _COOKIES_PATH

        # Prepend music search if not a URL
        if not any(query.startswith(p) for p in ("http://", "https://", "music.youtube")):
            # Use specific music search
            query = f"https://music.youtube.com/search?q={query}"

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(query, download=False)
                
                if info and "entries" in info:
                    entries = [e for e in info["entries"] if e]
                    if not entries: return None
                    info = entries[0]
                
                if not info: return None

                # Find best audio URL
                stream_url = None
                formats = info.get("formats") or []
                for f in reversed(formats):
                    if f.get("acodec") != "none" and f.get("vcodec") == "none":
                        stream_url = f.get("url")
                        break
                
                if not stream_url:
                    stream_url = info.get("url")

                if not stream_url: return None

                return {
                    "url": stream_url,
                    "title": info.get("title", "Unknown"),
                    "duration": int(info.get("duration") or 0),
                    "thumbnail": info.get("thumbnail"),
                    "uploader": info.get("uploader") or info.get("channel", "Unknown Artist"),
                    "source": "ytmusic",
                    "id": info.get("id", ""),
                }
        except Exception as e:
            logger.debug(f"YTMusic extraction error: {e}")
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
                logger.error(f"YTMusic extraction failed: {e}")
                return None

    def _search_sync(self, query: str, limit: int) -> list:
        """Search YouTube Music directly."""
        opts = {
            "extract_flat": "in_playlist",
            "quiet": True,
        }
        # ytsearch doesn't target music.youtube specifically, 
        # but we can use the URL-based search + entries unwrapping
        search_url = f"https://music.youtube.com/search?q={query}"
        
        results = []
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                # We need to extract the search result page
                info = ydl.extract_info(search_url, download=False)
                # YT Music search often returns multiple sections, 
                # extract_flat helps get the track entries
                if info and "entries" in info:
                    count = 0
                    for entry in info["entries"]:
                        if not entry or count >= limit: continue
                        if entry.get("type", "") == "playlist": continue # Skip section headers
                        
                        results.append({
                            "title": entry.get("title", "Unknown"),
                            "duration": int(entry.get("duration") or 0),
                            "thumbnail": entry.get("thumbnail"),
                            "uploader": entry.get("uploader") or entry.get("channel", "Unknown Artist"),
                            "id": entry.get("id", ""),
                            "url": f"https://music.youtube.com/watch?v={entry.get('id', '')}",
                            "source": "ytmusic",
                        })
                        count += 1
        except Exception as e:
            logger.error(f"YTMusic search error: {e}")
        return results

    async def search(self, query: str, limit: int = 5) -> list:
        loop = asyncio.get_event_loop()
        try:
            return await asyncio.wait_for(
                loop.run_in_executor(None, self._search_sync, query, limit),
                timeout=20.0
            )
        except Exception:
            return []

ytmusic = YTMusicExtractor()
