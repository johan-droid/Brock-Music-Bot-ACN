import aiohttp
import asyncio
import logging
import random
from typing import Optional, Dict, Any
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger(__name__)


class PipedExtractor:
    """Bypasses Commercial CDN blocks by utilizing decentralized proxy databases."""
    def __init__(self):
        self.instances = [
            "https://pipedapi.kavin.rocks",
            "https://pipedapi.tokhmi.xyz",
            "https://pipedapi.syncpundit.io"
        ]

    def _get_node(self) -> str:
        return random.choice(self.instances)

    async def extract(self, query: str) -> Optional[Dict[str, Any]]:
        """Searches Piped and returns a direct proxy audio stream, bypassing Heroku blocks."""
        node = self._get_node()
        search_url = f"{node}/search"
        params = {"q": query, "filter": "music_songs"}

        try:
            async with aiohttp.ClientSession() as session:
                # Perform search with a short timeout to fail fast
                try:
                    async with session.get(search_url, params=params, timeout=aiohttp.ClientTimeout(total=6)) as resp:
                        if resp.status != 200:
                            logger.debug("Piped search returned non-200 status: %s", resp.status)
                            return None
                        data = await resp.json()
                except (asyncio.TimeoutError, aiohttp.ClientError) as exc:
                    logger.debug(f"Piped search request failed: {exc}")
                    return None
                except Exception as exc:
                    logger.error(f"Piped search parse failed: {exc}")
                    return None

                items = data.get("items", []) if isinstance(data, dict) else []
                if not items:
                    return None

                # Find the first item with a usable URL and extract a video id.
                video_id = None
                for it in items:
                    # Safely read url and skip falsy values
                    video_url = it.get("url") if isinstance(it, dict) else None
                    if not video_url or not isinstance(video_url, str) or not video_url.strip():
                        continue
                    # Prefer parsed query parameter 'v', fall back to last path segment.
                    parsed = urlparse(video_url)
                    query_v = parse_qs(parsed.query).get("v", [""])[0]
                    if query_v:
                        vid = query_v
                    else:
                        parts = parsed.path.rstrip("/").split("/")
                        vid = parts[-1] if parts else ""
                    if vid:
                        video_id = vid
                        break

                if not video_id:
                    logger.debug("Piped search returned items with no usable URL")
                    return None

                stream_url = f"{node}/streams/{video_id}"

                # Fetch stream info with a slightly longer timeout
                try:
                    async with session.get(stream_url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                        if resp.status != 200:
                            logger.debug("Piped stream fetch returned non-200 status: %s", resp.status)
                            return None
                        stream_data = await resp.json()
                except (asyncio.TimeoutError, aiohttp.ClientError) as exc:
                    logger.debug(f"Piped stream request failed: {exc}")
                    return None
                except Exception as exc:
                    logger.error(f"Piped stream parse failed: {exc}")
                    return None

                audio_streams = stream_data.get("audioStreams", []) if isinstance(stream_data, dict) else []

                # Pick the highest-bitrate stream that actually has a URL
                valid_streams = [s for s in audio_streams if s and s.get("url")]
                if not valid_streams:
                    logger.debug("No valid audio streams found in piped response")
                    return None
                best_audio = max(valid_streams, key=lambda x: x.get("bitrate", 0))
                url = best_audio.get("url")
                if not url:
                    logger.debug("Best audio stream has no URL")
                    return None
                return {"url": url, "source": "piped", "headers": None}
        except Exception as e:
            logger.error(f"Piped extraction failed: {e}")
        return None


piped = PipedExtractor()
