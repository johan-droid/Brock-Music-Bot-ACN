"""
Spotify integration — metadata extraction with YouTube audio resolution.
The Soul King's Spotify scout! 💀🟢
"""

import logging
import asyncio
from typing import Optional, Dict, Any
from bot.platforms.youtube import youtube
from config import config

logger = logging.getLogger(__name__)

# ─── spotipy dependency ───────────────────────────────────────────────────────
try:
    import spotipy
    from spotipy.oauth2 import SpotifyClientCredentials
    SPOTIPY_AVAILABLE = True
except ImportError:
    SPOTIPY_AVAILABLE = False
    logger.warning("💀 spotipy not installed! Spotify features will be limited, Yohoho!")


class SpotifyExtractor:
    """Extracts Spotify metadata and resolves to YouTube stream URLs."""

    def __init__(self):
        self.sp = None
        if SPOTIPY_AVAILABLE and config.SPOTIFY_CLIENT_ID and config.SPOTIFY_CLIENT_SECRET:
            try:
                auth = SpotifyClientCredentials(
                    client_id=config.SPOTIFY_CLIENT_ID,
                    client_secret=config.SPOTIFY_CLIENT_SECRET,
                )
                self.sp = spotipy.Spotify(auth_manager=auth)
                logger.info("💀 Spotify client initialized!")
            except Exception as e:
                logger.error(f"💀 Failed to initialize Spotify: {e}")

    async def extract(self, url: str) -> Optional[Dict[str, Any]]:
        """
        Extract track info from Spotify URL and resolve to YouTube audio.
        """
        if not self.sp:
            logger.warning("💀 Spotify client not available!")
            return None

        try:
            track_id = self._extract_track_id(url)
            if not track_id:
                logger.warning(f"💀 Invalid Spotify URL: {url}")
                return None

            loop = asyncio.get_event_loop()
            track = await loop.run_in_executor(None, self.sp.track, track_id)

            artists = ", ".join([a["name"] for a in track["artists"]])
            title = track["name"]
            search_query = f"{artists} - {title}"

            thumbnail = None
            if track["album"].get("images"):
                thumbnail = track["album"]["images"][0]["url"]

            logger.info(f"💀 Spotify resolving: {search_query}")

            yt_result = await youtube.extract(search_query)

            if yt_result:
                yt_result.update({
                    "title": title,
                    "uploader": artists,
                    "thumbnail": thumbnail or yt_result.get("thumbnail"),
                    "source": "spotify",
                    "spotify_url": url,
                })
                return yt_result

            return None

        except Exception as e:
            logger.error(f"💀 Spotify extraction failed: {e}")
            return None

    def _extract_track_id(self, url: str) -> Optional[str]:
        """Extract track ID from Spotify URL or URI."""
        import re
        patterns = [
            r"spotify:track:([a-zA-Z0-9]+)",
            r"open\.spotify\.com/track/([a-zA-Z0-9]+)",
            r"spotify\.com/track/([a-zA-Z0-9]+)",
        ]
        for p in patterns:
            match = re.search(p, url)
            if match:
                return match.group(1)
        return None

    async def search(self, query: str, limit: int = 5) -> list:
        """Search Spotify tracks. Falls back to YouTube if Spotify unavailable."""
        if not self.sp:
            return await youtube.search(query, limit)

        try:
            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(
                None,
                lambda: self.sp.search(q=query, type="track", limit=limit)
            )
            items = (results or {}).get("tracks", {}).get("items", [])

            formatted = []
            for track in items:
                artists = ", ".join([a["name"] for a in track["artists"]])
                thumbnail = None
                if track["album"].get("images"):
                    thumbnail = track["album"]["images"][0]["url"]

                formatted.append({
                    "title": track["name"],
                    "uploader": artists,
                    "duration": int((track.get("duration_ms") or 0) // 1000),
                    "thumbnail": thumbnail,
                    "url": track["external_urls"]["spotify"],
                    "id": track["id"],
                    "source": "spotify",
                })
            return formatted

        except Exception as e:
            logger.error(f"💀 Spotify search failed: {e}")
            return await youtube.search(query, limit)


# Global instance
spotify = SpotifyExtractor()


async def extract_spotify(url: str) -> Optional[Dict[str, Any]]:
    return await spotify.extract(url)


async def search_spotify(query: str, limit: int = 5) -> list:
    return await spotify.search(query, limit)
