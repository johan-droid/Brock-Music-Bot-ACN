"""SoundCloud integration via yt-dlp."""

import logging
import asyncio
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class SoundCloudExtractor:
    """Extract audio from SoundCloud URLs using yt-dlp."""

    _YDL_OPTS_BASE = {
        "format": "bestaudio/best",
        "quiet": True,
        "no_warnings": True,
    }

    def __init__(self):
        pass

    async def extract(self, url: str) -> Optional[Dict[str, Any]]:
        """Extract audio from a SoundCloud URL."""
        try:
            loop = asyncio.get_event_loop()
            return await asyncio.wait_for(
                loop.run_in_executor(None, self._extract_sync, url),
                timeout=30.0,
            )
        except asyncio.TimeoutError:
            logger.warning(f"SoundCloud extract timeout for: {url}")
            return None
        except Exception as e:
            logger.error(f"SoundCloud extraction failed: {e}")
            return None

    def _extract_sync(self, query: str) -> Optional[Dict[str, Any]]:
        """Synchronous extraction via yt-dlp."""
        import yt_dlp

        # Support both direct SoundCloud URLs and generic search queries.
        if not any(query.startswith(p) for p in ("http://", "https://", "soundcloud", "snd.sc")):
            query = f"scsearch1:{query}"

        try:
            with yt_dlp.YoutubeDL(self._YDL_OPTS_BASE) as ydl:
                info = ydl.extract_info(query, download=False)

                audio_url = None
                if "url" in info:
                    audio_url = info["url"]
                elif "formats" in info:
                    for fmt in sorted(
                        info["formats"],
                        key=lambda f: f.get("abr") or 0,
                        reverse=True,
                    ):
                        if fmt.get("acodec") != "none" and fmt.get("url"):
                            audio_url = fmt["url"]
                            break

                if not audio_url:
                    return None

                return {
                    "url": audio_url,
                    "title": info.get("title", "Unknown"),
                    "duration": int(info.get("duration") or 0),
                    "thumbnail": info.get("thumbnail"),
                    "uploader": info.get("uploader") or info.get("creator") or "Unknown",
                    "id": str(info.get("id", "")),
                    "source": "soundcloud",
                }

        except Exception as e:
            logger.error(f"SoundCloud extraction error: {e}")
            return None

    def _search_sync(self, query: str, limit: int) -> list:
        """Search SoundCloud for multiple results (flat extract)."""
        import yt_dlp

        opts = {
            **self._YDL_OPTS_BASE,
            "extract_flat": True,
            "playlist_items": f"1-{limit}",
        }

        results = []
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(f"scsearch{limit}:{query}", download=False)
                for entry in (info or {}).get("entries") or []:
                    if not entry:
                        continue
                    uploader = (
                        entry.get("uploader")
                        or entry.get("channel")
                        or (entry.get("user") or {}).get("username")
                        or "Unknown"
                    )
                    results.append({
                        "title": entry.get("title", "Unknown"),
                        "duration": int(entry.get("duration") or 0),
                        "thumbnail": entry.get("thumbnail"),
                        "uploader": uploader,
                        "id": str(entry.get("id", "")),
                        "url": entry.get("url") or entry.get("webpage_url", ""),
                        "source": "soundcloud",
                    })
        except Exception as e:
            logger.error(f"SoundCloud search error: {e}")

        return results

    async def search(self, query: str, limit: int = 5) -> list:
        """Async search for SoundCloud tracks."""
        loop = asyncio.get_event_loop()
        try:
            return await asyncio.wait_for(
                loop.run_in_executor(None, self._search_sync, query, limit),
                timeout=20.0,
            )
        except asyncio.TimeoutError:
            logger.warning(f"SoundCloud search timeout for: {query}")
            return []
        except Exception as e:
            logger.error(f"SoundCloud search failed: {e}")
            return []


# Global extractor
soundcloud = SoundCloudExtractor()


async def extract_soundcloud(url: str) -> Optional[Dict[str, Any]]:
    """Extract from SoundCloud URL."""
    return await soundcloud.extract(url)
