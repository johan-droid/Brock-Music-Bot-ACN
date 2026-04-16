"""Universal Piped extractor with multi-instance failover."""

import logging
import random
from urllib.parse import parse_qs, urlparse

import aiohttp

from config import config

logger = logging.getLogger(__name__)


class PipedUniversalExtractor:
    """Single extractor for all public content with automatic node failover."""

    _DEFAULT_INSTANCES = [
        "https://pipedapi.adminforge.de",
        "https://api.piped.yt",
        "https://pipedapi.kavin.rocks",
        "https://pipedapi.lunar.icu",
        "https://piapi.ggtyler.dev",
        "https://api.piped.private.coffee",
        "https://pipedapi.drgns.space",
        "https://api.piped.privacydev.net",
        "https://api.piped.minionflo.net",
        "https://pipedapi-libre.kavin.rocks",
    ]

    def __init__(self):
        raw_instances = getattr(config, "PIPED_INSTANCES", None)
        cleaned: list[str] = []

        if raw_instances:
            if isinstance(raw_instances, str):
                separators = [",", "\n", " "]
                parts = [raw_instances]
                for sep in separators:
                    next_parts: list[str] = []
                    for part in parts:
                        next_parts.extend(part.split(sep))
                    parts = next_parts

                for item in parts:
                    value = item.strip().rstrip("/")
                    if value.startswith("http"):
                        cleaned.append(value)
            else:
                for item in raw_instances:
                    if not isinstance(item, str):
                        continue
                    instance = item.strip().rstrip("/")
                    if instance.startswith("http"):
                        cleaned.append(instance)

        if not cleaned:
            fallback = (getattr(config, "PIPED_API", "") or "").strip().rstrip("/")
            if fallback:
                cleaned = [fallback]

        if not cleaned:
            cleaned = self._DEFAULT_INSTANCES[:]

        # Keep order stable while removing duplicates.
        deduped: list[str] = []
        for instance in cleaned:
            if instance not in deduped:
                deduped.append(instance)

        cleaned = deduped

        self.instances = cleaned
        logger.info("Piped instances configured: %s", ", ".join(self.instances))

    def _extract_video_id(self, value: str | None) -> str | None:
        if not value:
            return None

        raw = value.strip()
        if not raw:
            return None

        if "youtube.com/watch" in raw:
            parsed = urlparse(raw)
            video_id = parse_qs(parsed.query).get("v", [None])[0]
            return video_id

        if raw.startswith("/watch"):
            parsed = urlparse(raw)
            video_id = parse_qs(parsed.query).get("v", [None])[0]
            return video_id

        if "youtu.be/" in raw:
            parsed = urlparse(raw)
            last = (parsed.path or "").strip("/")
            return last or None

        return raw

    async def search(self, query: str, limit: int = 10):
        """Search against Piped instances, returning first successful result set."""
        if not self.instances:
            return []

        instances = self.instances[:]
        random.shuffle(instances)

        timeout = aiohttp.ClientTimeout(total=8)

        for instance in instances:
            try:
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    endpoint = f"{instance}/search"
                    params = {"q": query, "filter": "videos"}
                    async with session.get(endpoint, params=params) as response:
                        if response.status != 200:
                            continue

                        # Verify content-type before attempting to decode JSON
                        if "application/json" not in (response.content_type or "").lower():
                            logger.warning(f"Piped search node {instance} returned non-JSON content: {response.content_type}")
                            continue

                        try:
                            payload = await response.json()
                        except Exception as json_err:
                            logger.warning(f"Failed to decode Piped search JSON from {instance}: {json_err}")
                            continue

                        if isinstance(payload, dict):
                            items = payload.get("items") or []
                        elif isinstance(payload, list):
                            items = payload
                        else:
                            items = []

                        tracks = []
                        for item in items[:limit]:
                            title = item.get("title") or "Unknown"
                            uploader = item.get("uploaderName") or "Unknown"
                            duration = item.get("duration") or 0
                            url = item.get("url") or ""
                            thumb = item.get("thumbnail") or None

                            video_id = self._extract_video_id(url)
                            if not video_id:
                                continue

                            tracks.append(
                                {
                                    "id": video_id,
                                    "title": title,
                                    "uploader": uploader,
                                    "duration": duration,
                                    "url": f"https://youtube.com/watch?v={video_id}",
                                    "thumbnail": thumb,
                                    "source": "youtube",
                                }
                            )

                        if tracks:
                            logger.info(f"Piped search ok via {instance} ({len(tracks)} result(s))")
                            return tracks
            except Exception as e:
                logger.warning(f"Piped search failed on {instance}: {e}")

        logger.warning("Piped search exhausted all nodes")
        return []

    async def extract(self, target: str):
        """Resolve a playable audio stream URL using Piped failover."""
        if not self.instances:
            return None

        video_id = self._extract_video_id(target)
        if not video_id:
            return None

        import re
        if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
            logger.info(f"Target does not look like a video ID. Searching instead: {target}")
            results = await self.search(target, limit=1)
            if not results:
                return None
            video_id = results[0]["id"]

        instances = self.instances[:]
        random.shuffle(instances)

        timeout = aiohttp.ClientTimeout(total=8)

        for instance in instances:
            try:
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    endpoint = f"{instance}/streams/{video_id}"
                    async with session.get(endpoint) as response:
                        if response.status != 200:
                            continue

                        if "application/json" not in (response.content_type or "").lower():
                            logger.warning(f"Piped extract node {instance} returned non-JSON content: {response.content_type}")
                            continue

                        try:
                            stream_info = await response.json()
                        except Exception as json_err:
                            logger.warning(f"Failed to decode Piped extract JSON from {instance}: {json_err}")
                            continue

                        if not isinstance(stream_info, dict):
                            continue

                        audio_streams = stream_info.get("audioStreams") or []
                        if not audio_streams:
                            continue

                        valid_streams = [s for s in audio_streams if isinstance(s, dict) and s.get("url")]
                        if not valid_streams:
                            continue

                        best_stream = max(valid_streams, key=lambda item: item.get("bitrate") or 0)
                        stream_url = best_stream.get("url")
                        if not stream_url:
                            continue

                        title = stream_info.get("title") or "Unknown"
                        uploader = stream_info.get("uploader") or stream_info.get("uploaderName") or "Unknown"
                        duration = stream_info.get("duration") or 0
                        thumb = stream_info.get("thumbnailUrl") or None

                        logger.info(f"Piped extract ok via {instance} ({video_id})")
                        return {
                            "id": video_id,
                            "title": title,
                            "uploader": uploader,
                            "duration": duration,
                            "url": stream_url,
                            "thumbnail": thumb,
                            "source": "youtube",
                        }
            except Exception as e:
                logger.warning(f"Piped extract failed on {instance}: {e}")

        logger.error(f"Piped extract failed across all nodes for {video_id}")
        return None

    async def get_related(self, video_id: str, limit: int = 5) -> list:
        """Fetch related videos for autoplay."""
        if not self.instances:
            return []

        # It might be a full URL instead of a raw ID
        video_id = self._extract_video_id(video_id) or video_id

        instances = self.instances[:]
        random.shuffle(instances)

        timeout = aiohttp.ClientTimeout(total=8)

        for instance in instances:
            try:
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    endpoint = f"{instance}/streams/{video_id}"
                    async with session.get(endpoint) as response:
                        if response.status != 200:
                            continue

                        if "application/json" not in (response.content_type or "").lower():
                            continue

                        try:
                            stream_info = await response.json()
                        except Exception:
                            continue

                        related = stream_info.get("relatedStreams") or []
                        
                        tracks = []
                        for item in related:
                            if item.get("type") != "stream":
                                continue
                                
                            url = item.get("url", "")
                            rel_id = self._extract_video_id(url)
                            if not rel_id:
                                continue
                                
                            tracks.append({
                                "id": rel_id,
                                "title": item.get("title") or "Unknown",
                                "uploader": item.get("uploaderName") or "Unknown",
                                "duration": item.get("duration") or 0,
                                "url": f"https://youtube.com/watch?v={rel_id}",
                                "thumbnail": item.get("thumbnail") or None,
                                "source": "youtube",
                            })
                            if len(tracks) >= limit:
                                break

                        if tracks:
                            return tracks
            except Exception as e:
                logger.debug(f"Piped get_related failed on {instance}: {e}")

        logger.warning(f"Piped get_related failed across all nodes for {video_id}")
        return []

piped = PipedUniversalExtractor()

