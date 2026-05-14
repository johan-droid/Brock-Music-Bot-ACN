"""VK extractor hooks for the music backend."""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, List, Optional

import aiohttp

logger = logging.getLogger(__name__)

_URL_SCHEME_RX = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://")
_TRACK_ID_RX = re.compile(r"(?:track/|audio)(\d+)", re.IGNORECASE)


def _normalize_url_text(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return text
    if _URL_SCHEME_RX.match(text):
        return text
    if text.startswith(("www.", "vk.com", "m.vk.com", "vk.ru", "vkvideo.ru")):
        return f"https://{text}"
    return text


def _looks_like_page_url(value: str) -> bool:
    text = (value or "").strip().lower()
    if not text:
        return False
    return any(domain in text for domain in ("vk.com", "vk.ru", "vkvideo.ru"))


class VKExtractor:
    def __init__(self) -> None:
        self.base_url = os.getenv("VK_API_BASE_URL", "").strip().rstrip("/")
        self.token = os.getenv("VK_API_TOKEN", "").strip()
        self.search_path = os.getenv("VK_SEARCH_PATH", "/search")
        self.resolve_path = os.getenv("VK_RESOLVE_PATH", "/resolve")
        self.token_header = (os.getenv("VK_TOKEN_HEADER", "Authorization") or "Authorization").strip()
        self.timeout = float(os.getenv("VK_HTTP_TIMEOUT", "15"))

    def _headers(self) -> Dict[str, str]:
        if not self.token:
            return {}
        if self.token_header.lower() == "authorization":
            return {"Authorization": f"Bearer {self.token}"}
        return {self.token_header: self.token}

    async def search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        if not self.base_url:
            return []

        endpoint = f"{self.base_url}{self.search_path}"
        params = {"q": query, "limit": max(1, limit)}
        timeout = aiohttp.ClientTimeout(total=self.timeout)

        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(endpoint, params=params, headers=self._headers()) as response:
                    if response.status == 503:
                        logger.warning("VK search unavailable (503) - likely cold start or overload")
                        return []
                    if response.status >= 400:
                        logger.warning("VK search returned HTTP %s", response.status)
                        return []
                    payload = await response.json(content_type=None)
        except Exception as exc:
            logger.warning("VK search failed: %s", exc)
            return []

        items = payload.get("items") if isinstance(payload, dict) else payload
        if not isinstance(items, list):
            return []

        results: List[Dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue

            track_id = item.get("id") or item.get("track_id") or item.get("vk_id")
            stream_url = _normalize_url_text(item.get("stream_url") or item.get("url") or item.get("play_url") or "")
            if not stream_url and track_id:
                stream_url = f"vk://{track_id}"

            if not stream_url:
                continue

            results.append(
                {
                    "title": item.get("title") or item.get("name") or "Unknown",
                    "artist": item.get("artist") or item.get("uploader") or item.get("author") or "Unknown Artist",
                    "duration": int(item.get("duration") or item.get("length") or 0),
                    "url": stream_url,
                    "thumbnail": item.get("thumbnail") or item.get("cover") or "",
                    "source": "vk",
                    "id": str(track_id) if track_id is not None else None,
                }
            )
            if len(results) >= limit:
                break

        return results

    async def extract(self, track_id: str) -> Optional[Dict[str, Any]]:
        candidate = (track_id or "").strip()
        if not candidate:
            return None

        if candidate.startswith("vk://"):
            candidate = candidate[5:]

        if candidate.startswith("http") and not _looks_like_page_url(candidate):
            return {
                "url": candidate,
                "stream_url": candidate,
                "source": "vk",
                "headers": None,
            }

        if not self.base_url:
            return None

        endpoint = f"{self.base_url}{self.resolve_path}"
        payload: Dict[str, Any] = {"id": candidate}
        if candidate.startswith("http"):
            payload = {"url": candidate}

        timeout = aiohttp.ClientTimeout(total=self.timeout)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(endpoint, json=payload, headers=self._headers()) as response:
                    if response.status >= 400:
                        logger.warning("VK resolve returned HTTP %s", response.status)
                        return None
                    data = await response.json(content_type=None)
        except Exception as exc:
            logger.warning("VK resolve failed: %s", exc)
            return None

        if not isinstance(data, dict):
            return None

        url = _normalize_url_text(data.get("url") or data.get("stream_url") or data.get("play_url") or "")
        if not url:
            return None

        return {
            "url": url,
            "stream_url": url,
            "title": data.get("title") or "Unknown",
            "artist": data.get("artist") or data.get("uploader") or "Unknown Artist",
            "duration": int(data.get("duration") or 0),
            "thumbnail": data.get("thumbnail") or data.get("cover") or "",
            "source": "vk",
            "headers": None,
            "id": data.get("id") or data.get("track_id") or candidate,
        }


vk_extractor = VKExtractor()

__all__ = ["VKExtractor", "vk_extractor"]
