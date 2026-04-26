"""YouTube Music extractor using yt-dlp - works globally."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Try to import yt_dlp
try:
    import yt_dlp
    YTDLP_AVAILABLE = True
except ImportError:
    YTDLP_AVAILABLE = False
    logger.warning("yt-dlp not available, YouTube Music extractor disabled")


class YouTubeMusicExtractor:
    """YouTube Music search and extraction using yt-dlp."""

    def __init__(self) -> None:
        self.timeout = 30  # seconds for yt-dlp operations

    def _get_ydl_opts(self, extract_audio: bool = True) -> Dict[str, Any]:
        """Get yt-dlp options for audio extraction."""
        return {
            "format": "bestaudio/best",
            "quiet": True,
            "no_warnings": True,
            "extract_audio": extract_audio,
            "audio_format": "mp3",
            "audio_quality": "0",  # best
            "outtmpl": "%(title)s.%(ext)s",
            "cookiefile": None,
            "cookiesfrombrowser": None,
            "headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            },
        }

    async def search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Search YouTube Music for tracks matching query."""
        if not YTDLP_AVAILABLE:
            logger.warning("yt-dlp not available, skipping YouTube search")
            return []

        search_query = f"ytsearch{limit}:{query}"

        try:
            loop = asyncio.get_event_loop()

            def _do_search():
                with yt_dlp.YoutubeDL(self._get_ydl_opts(extract_audio=False)) as ydl:
                    # Search without downloading
                    result = ydl.extract_info(search_query, download=False)
                    if not result:
                        return []

                    entries = result.get("entries", [])
                    tracks = []

                    for entry in entries:
                        if not entry:
                            continue

                        # Extract track info
                        track_id = entry.get("id")
                        title = entry.get("title", "Unknown")
                        duration = entry.get("duration", 0)
                        thumbnail = entry.get("thumbnail", "")
                        channel = entry.get("channel", entry.get("uploader", "Unknown Artist"))

                        # Check if it's music-related
                        url = f"https://www.youtube.com/watch?v={track_id}"

                        tracks.append({
                            "id": track_id,
                            "title": title,
                            "artist": channel,
                            "duration": duration,
                            "thumbnail": thumbnail,
                            "url": url,
                            "source": "youtube",
                        })

                    return tracks

            # Run in thread pool to avoid blocking
            tracks = await asyncio.wait_for(
                loop.run_in_executor(None, _do_search),
                timeout=self.timeout
            )

            logger.info(f"YouTube search returned {len(tracks)} results for: {query}")
            return tracks

        except asyncio.TimeoutError:
            logger.warning(f"YouTube search timed out for query: {query}")
            return []
        except Exception as e:
            logger.warning(f"YouTube search failed: {e}")
            return []

    async def extract(self, track_id: str) -> Optional[Dict[str, Any]]:
        """Extract direct audio URL for a YouTube video ID."""
        if not YTDLP_AVAILABLE:
            return None

        # Handle full URLs
        if track_id.startswith("http"):
            url = track_id
            # Extract ID from URL
            match = re.search(r"[?&]v=([a-zA-Z0-9_-]{11})", url)
            if match:
                track_id = match.group(1)
            else:
                track_id = url.split("/")[-1].split("?")[0]
        else:
            url = f"https://www.youtube.com/watch?v={track_id}"

        try:
            loop = asyncio.get_event_loop()

            def _do_extract():
                opts = self._get_ydl_opts(extract_audio=True)
                opts["format"] = "bestaudio[ext=m4a]/bestaudio/best"
                opts["skip_download"] = True

                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    if not info:
                        return None

                    # Get best audio format
                    formats = info.get("formats", [])
                    audio_formats = [f for f in formats if f.get("acodec") != "none" and f.get("vcodec") == "none"]

                    if audio_formats:
                        # Sort by quality (highest bitrate first)
                        audio_formats.sort(key=lambda x: x.get("tbr", 0) or 0, reverse=True)
                        best_audio = audio_formats[0]
                        stream_url = best_audio.get("url")
                    else:
                        # Fallback to any format with audio
                        stream_url = info.get("url") or (formats[0].get("url") if formats else None)

                    if not stream_url:
                        return None

                    return {
                        "id": track_id,
                        "title": info.get("title", "Unknown"),
                        "artist": info.get("channel", info.get("uploader", "Unknown Artist")),
                        "duration": info.get("duration", 0),
                        "thumbnail": info.get("thumbnail", ""),
                        "url": stream_url,
                        "stream_url": stream_url,
                        "source": "youtube",
                        "headers": {
                            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                            "Accept": "*/*",
                            "Accept-Language": "en-US,en;q=0.9",
                        },
                    }

            result = await asyncio.wait_for(
                loop.run_in_executor(None, _do_extract),
                timeout=self.timeout
            )

            return result

        except asyncio.TimeoutError:
            logger.warning(f"YouTube extract timed out for: {track_id}")
            return None
        except Exception as e:
            logger.warning(f"YouTube extract failed: {e}")
            return None


youtube_extractor = YouTubeMusicExtractor()

__all__ = ["YouTubeMusicExtractor", "youtube_extractor"]
