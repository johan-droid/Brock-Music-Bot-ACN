"""Deezer extractor hooks for the music backend."""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, List, Optional

import aiohttp

logger = logging.getLogger(__name__)

_URL_SCHEME_RX = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://")
_TRACK_ID_RX = re.compile(r"(?:track|song)/(\d+)", re.IGNORECASE)


def _normalize_url_text(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return text
    if _URL_SCHEME_RX.match(text):
        return text
    if text.startswith(("www.", "deezer.com", "deezer.page.link")):
        return f"https://{text}"
    return text


def _looks_like_page_url(value: str) -> bool:
    text = (value or "").strip().lower()
    if not text:
        return False
    return any(domain in text for domain in ("deezer.com", "deezer.page.link"))


def _extract_track_id(value: str) -> Optional[str]:
    text = (value or "").strip()
    if not text:
        return None
    if text.startswith("deezer://"):
        text = text[9:]
    if text.isdigit():
        return text
    match = _TRACK_ID_RX.search(text)
    if match:
        return match.group(1)
    return None


class DeezerExtractor:
    def __init__(self) -> None:
        self.base_url = os.getenv("DEEZER_API_BASE_URL", "https://api.deezer.com").strip().rstrip("/")
        raw_tokens = os.getenv("DEEZER_TOKENS", "")
        self.tokens = [token.strip() for token in re.split(r"[\s,]+", raw_tokens) if token.strip()]
        self.timeout = float(os.getenv("DEEZER_HTTP_TIMEOUT", "15"))
        self._token_index = 0

    def _next_token(self) -> Optional[str]:
        if not self.tokens:
            return None
        token = self.tokens[self._token_index % len(self.tokens)]
        self._token_index = (self._token_index + 1) % len(self.tokens)
        return token

    def _headers(self) -> Dict[str, str]:
        return {
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://www.deezer.com/",
        }

    async def search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        endpoint = f"{self.base_url}/search"
        attempts = max(1, len(self.tokens) or 1)
        timeout = aiohttp.ClientTimeout(total=self.timeout)
        payload: Dict[str, Any] = {}

        async with aiohttp.ClientSession(timeout=timeout) as session:
            for _ in range(attempts):
                token = self._next_token()
                params: Dict[str, Any] = {"q": query, "limit": max(1, limit)}
                if token:
                    params["access_token"] = token

                try:
                    async with session.get(endpoint, params=params, headers=self._headers()) as response:
                        if response.status in (401, 403, 429):
                            logger.debug("Deezer search token rejected with HTTP %s", response.status)
                            continue
                        if response.status >= 400:
                            logger.warning("Deezer search returned HTTP %s", response.status)
                            continue
                        payload = await response.json(content_type=None)
                        break
                except Exception as exc:
                    logger.warning("Deezer search failed: %s", exc)
            else:
                return []

        items = payload.get("data") if isinstance(payload, dict) else payload
        if not isinstance(items, list):
            return []

        results: List[Dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue

            track_id = item.get("id")
            preview = _normalize_url_text(item.get("preview") or item.get("stream_url") or item.get("url") or "")
            if not preview and track_id:
                preview = f"deezer://{track_id}"
            if not preview:
                continue

            artist = "Unknown Artist"
            if isinstance(item.get("artist"), dict):
                artist = item["artist"].get("name") or artist

            thumbnail = ""
            if isinstance(item.get("album"), dict):
                thumbnail = item["album"].get("cover_medium") or item["album"].get("cover") or ""

            results.append(
                {
                    "title": item.get("title") or "Unknown",
                    "artist": artist,
                    "duration": int(item.get("duration") or 0),
                    "url": preview,
                    "thumbnail": thumbnail,
                    "source": "deezer",
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

        if candidate.startswith("deezer://"):
            candidate = candidate[9:]

        if candidate.startswith("http") and not _looks_like_page_url(candidate):
            return {
                "url": candidate,
                "stream_url": candidate,
                "source": "deezer",
                "headers": self._headers(),
            }

        extracted_id = _extract_track_id(candidate)
        if extracted_id:
            candidate = extracted_id

        endpoint = f"{self.base_url}/track/{candidate}"
        params: Dict[str, Any] = {}
        if self.tokens:
            params["access_token"] = self._next_token() or ""

        timeout = aiohttp.ClientTimeout(total=self.timeout)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(endpoint, params=params, headers=self._headers()) as response:
                    if response.status >= 400:
                        logger.warning("Deezer track lookup returned HTTP %s", response.status)
                        return None
                    data = await response.json(content_type=None)
        except Exception as exc:
            logger.warning("Deezer resolve failed: %s", exc)
            return None

        if not isinstance(data, dict):
            return None

        url = _normalize_url_text(data.get("preview") or data.get("stream_url") or data.get("url") or "")
        if not url:
            return None

        artist = "Unknown Artist"
        if isinstance(data.get("artist"), dict):
            artist = data["artist"].get("name") or artist

        thumbnail = ""
        if isinstance(data.get("album"), dict):
            thumbnail = data["album"].get("cover_medium") or data["album"].get("cover") or ""

        return {
            "url": url,
            "stream_url": url,
            "title": data.get("title") or "Unknown",
            "artist": artist,
            "duration": int(data.get("duration") or 0),
            "thumbnail": thumbnail,
            "source": "deezer",
            "headers": self._headers(),
            "id": str(data.get("id") or candidate),
        }


deezer_extractor = DeezerExtractor()

__all__ = ["DeezerExtractor", "deezer_extractor"]
