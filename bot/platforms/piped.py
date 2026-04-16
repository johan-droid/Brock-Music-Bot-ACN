"""Universal Piped & Invidious extractor with multi-instance failover."""

import logging
import random
import asyncio
from urllib.parse import parse_qs, urlparse

import aiohttp
from yarl import URL

from config import config

logger = logging.getLogger(__name__)


class PipedUniversalExtractor:
    """Single extractor for all public content with automatic node failover & Invidious backup."""

    _PIPED_INSTANCES = [
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

    _INVIDIOUS_INSTANCES = [
        "https://invidious.snopyta.org",
        "https://yewtu.be",
        "https://invidious.kavin.rocks",
        "https://inv.vern.cc",
        "https://invidious.flokinet.to",
        "https://invidious.privacydev.net",
    ]

    def __init__(self):
        self.piped_instances = self._parse_instances(getattr(config, "PIPED_INSTANCES", None)) or self._PIPED_INSTANCES[:]
        self.invidious_instances = self._INVIDIOUS_INSTANCES[:]
        
        logger.info("Piped nodes: %s", len(self.piped_instances))
        logger.info("Invidious nodes: %s", len(self.invidious_instances))

    def _parse_instances(self, raw_instances: any) -> list[str]:
        cleaned: list[str] = []
        if not raw_instances:
            return []

        if isinstance(raw_instances, str):
            parts = [raw_instances]
            for sep in [",", "\n", " "]:
                next_parts = []
                for p in parts:
                    next_parts.extend(p.split(sep))
                parts = next_parts
            for item in parts:
                val = item.strip().rstrip("/")
                if val.startswith("http"):
                    cleaned.append(val)
        elif isinstance(raw_instances, list):
            for item in raw_instances:
                if isinstance(item, str) and item.startswith("http"):
                    cleaned.append(item.strip().rstrip("/"))
        
        # Dedup
        res = []
        for x in cleaned:
            if x not in res:
                res.append(x)
        return res

    def _extract_video_id(self, value: str | None) -> str | None:
        if not value: return None
        raw = value.strip()
        if not raw: return None
        if "youtube.com/watch" in raw:
            return parse_qs(urlparse(raw).query).get("v", [None])[0]
        if raw.startswith("/watch"):
            return parse_qs(urlparse(raw).query).get("v", [None])[0]
        if "youtu.be/" in raw:
            return (urlparse(raw).path or "").strip("/")
        return raw

    async def search(self, query: str, limit: int = 10):
        """Search against Piped, fallback to Invidious if exhausted."""
        instances = self.piped_instances[:]
        random.shuffle(instances)

        # 1. Try Piped Nodes
        tracks = await self._search_piped(query, instances, limit)
        if tracks:
            return tracks

        # 2. Fallback to Invidious
        logger.warning(f"Piped exhausted. Trying Invidious for: {query}")
        inv_instances = self.invidious_instances[:]
        random.shuffle(inv_instances)
        return await self._search_invidious(query, inv_instances, limit)

    async def _search_piped(self, query: str, instances: list, limit: int):
        timeout = aiohttp.ClientTimeout(total=8)
        # Using TCPConnector(ssl=False) to bypass expired certificates on community nodes
        async with aiohttp.ClientSession(timeout=timeout, connector=aiohttp.TCPConnector(ssl=False)) as session:
            for instance in instances:
                try:
                    # Use yarl.URL for bulletproof endpoint construction
                    base_url = URL(instance)
                    endpoint = base_url / "search"
                    params = {"q": query, "filter": "videos"}
                    
                    async with session.get(endpoint, params=params) as response:
                        if response.status != 200:
                            continue
                        if "application/json" not in (response.content_type or "").lower():
                            continue
                        
                        payload = await response.json()
                        items = payload.get("items") if isinstance(payload, dict) else payload
                        if not isinstance(items, list): continue

                        tracks = []
                        for item in items[:limit]:
                            v_id = self._extract_video_id(item.get("url")) or item.get("videoId")
                            if not v_id: continue
                            tracks.append({
                                "id": v_id,
                                "title": item.get("title") or "Unknown",
                                "uploader": item.get("uploaderName") or "Unknown",
                                "duration": item.get("duration") or 0,
                                "url": f"https://youtube.com/watch?v={v_id}",
                                "thumbnail": item.get("thumbnail") or None,
                                "source": "youtube",
                            })
                        if tracks:
                            logger.info(f"Piped search ok via {instance}")
                            return tracks
                except Exception as e:
                    logger.debug(f"Piped node {instance} failed: {e}")
        return []

    async def _search_invidious(self, query: str, instances: list, limit: int):
        timeout = aiohttp.ClientTimeout(total=8)
        async with aiohttp.ClientSession(timeout=timeout, connector=aiohttp.TCPConnector(ssl=False)) as session:
            for instance in instances:
                try:
                    base_url = URL(instance)
                    endpoint = base_url / "api" / "v1" / "search"
                    params = {"q": query, "type": "video"}
                    
                    async with session.get(endpoint, params=params) as response:
                        if response.status != 200: continue
                        payload = await response.json()
                        if not isinstance(payload, list): continue

                        tracks = []
                        for item in payload[:limit]:
                            v_id = item.get("videoId")
                            if not v_id: continue
                            tracks.append({
                                "id": v_id,
                                "title": item.get("title") or "Unknown",
                                "uploader": item.get("author") or "Unknown",
                                "duration": item.get("lengthSeconds") or 0,
                                "url": f"https://youtube.com/watch?v={v_id}",
                                "thumbnail": (item.get("videoThumbnails") or [{}])[0].get("url"),
                                "source": "youtube",
                            })
                        if tracks:
                            logger.info(f"Invidious search ok via {instance}")
                            return tracks
                except Exception as e:
                    logger.debug(f"Invidious node {instance} failed: {e}")
        return []

    async def extract(self, target: str):
        """Resolve a playable audio stream URL."""
        video_id = self._extract_video_id(target)
        if not video_id: return None

        import re
        if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
            results = await self.search(target, limit=1)
            if not results: return None
            video_id = results[0]["id"]

        instances = self.piped_instances[:]
        random.shuffle(instances)

        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout, connector=aiohttp.TCPConnector(ssl=False)) as session:
            for instance in instances:
                try:
                    base_url = URL(instance)
                    endpoint = base_url / "streams" / video_id
                    async with session.get(endpoint) as response:
                        if response.status != 200: continue
                        if "application/json" not in (response.content_type or "").lower(): continue
                        
                        stream_info = await response.json()
                        audio_streams = stream_info.get("audioStreams") or []
                        valid = [s for s in audio_streams if isinstance(s, dict) and s.get("url")]
                        if not valid: continue

                        best = max(valid, key=lambda x: x.get("bitrate") or 0)
                        stream_url = best.get("url")
                        if not stream_url: continue

                        return {
                            "id": video_id,
                            "title": stream_info.get("title") or "Unknown",
                            "uploader": stream_info.get("uploader") or stream_info.get("uploaderName") or "Unknown",
                            "duration": stream_info.get("duration") or 0,
                            "url": stream_url,
                            "thumbnail": stream_info.get("thumbnailUrl") or None,
                            "source": "youtube",
                        }
                except Exception as e:
                    logger.debug(f"Piped extract failed on {instance}: {e}")

        # Invidious extract fallback if needed, but piped streams are generally matched 1:1 with IDs.
        logger.error(f"Extraction failed across all nodes for {video_id}")
        return None

    async def get_related(self, video_id: str, limit: int = 5) -> list:
        """Fetch related videos for autoplay."""
        video_id = self._extract_video_id(video_id) or video_id
        instances = self.piped_instances[:]
        random.shuffle(instances)

        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout, connector=aiohttp.TCPConnector(ssl=False)) as session:
            for instance in instances:
                try:
                    base_url = URL(instance)
                    endpoint = base_url / "streams" / video_id
                    async with session.get(endpoint) as response:
                        if response.status != 200: continue
                        if "application/json" not in (response.content_type or "").lower(): continue
                        
                        info = await response.json()
                        related = info.get("relatedStreams") or []
                        
                        tracks = []
                        for item in related:
                            if item.get("type") != "stream": continue
                            rel_id = self._extract_video_id(item.get("url")) or item.get("videoId")
                            if not rel_id: continue
                            tracks.append({
                                "id": rel_id,
                                "title": item.get("title") or "Unknown",
                                "uploader": item.get("uploaderName") or "Unknown",
                                "duration": item.get("duration") or 0,
                                "url": f"https://youtube.com/watch?v={rel_id}",
                                "thumbnail": item.get("thumbnail") or None,
                                "source": "youtube",
                            })
                            if len(tracks) >= limit: break
                        if tracks: return tracks
                except Exception:
                    continue
        return []

piped = PipedUniversalExtractor()

