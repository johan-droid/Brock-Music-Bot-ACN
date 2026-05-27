"""HTTP client for remote music microservices."""

from __future__ import annotations

import asyncio
import aiohttp
import logging
from typing import Any, Dict, Iterable, List, Optional

from bot.utils.http_pool import HTTPConnectionPool

logger = logging.getLogger(__name__)


def _normalize_urls(values: Iterable[str]) -> List[str]:
    normalized: List[str] = []
    seen = set()

    for raw in values:
        value = (raw or "").strip()
        if not value:
            continue
        if not value.startswith(("http://", "https://")):
            value = f"https://{value}"
        value = value.rstrip("/")
        if value in seen:
            continue
        seen.add(value)
        normalized.append(value)

    return normalized


class MusicMicroserviceClient:
    """Resilient client for search/resolve calls to remote music services."""

    def __init__(
        self,
        base_urls: List[str],
        search_path: str = "/search",
        resolve_path: str = "/resolve",
        health_path: str = "/health",
        timeout_seconds: int = 12,
        token: Optional[str] = None,
        token_header: str = "Authorization",
    ) -> None:
        self.base_urls = _normalize_urls(base_urls)
        self.search_path = self._normalize_path(search_path, default="/search")
        self.resolve_path = self._normalize_path(resolve_path, default="/resolve")
        self.health_path = self._normalize_path(health_path, default="/health")
        self.timeout_seconds = max(4, int(timeout_seconds or 12))
        self.token = (token or "").strip() or None
        self.token_header = (token_header or "Authorization").strip() or "Authorization"

    @property
    def is_configured(self) -> bool:
        return bool(self.base_urls)

    @staticmethod
    def _normalize_path(path: str, default: str) -> str:
        value = (path or "").strip()
        if not value:
            return default
        if not value.startswith("/"):
            value = f"/{value}"
        return value

    def _headers(self) -> Dict[str, str]:
        headers = {"Accept": "application/json"}
        if not self.token:
            return headers

        if self.token_header.lower() == "authorization":
            headers[self.token_header] = f"Bearer {self.token}"
        else:
            headers[self.token_header] = self.token
        return headers

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json_payload: Optional[Dict[str, Any]] = None,
        expected: tuple[int, ...] = (200,),
    ) -> Optional[Dict[str, Any]]:
        if not self.base_urls:
            return None

        headers = self._headers()
        last_error: Optional[str] = None

        for idx, base_url in enumerate(self.base_urls):
            url = f"{base_url}{path}"
            try:
                session = await HTTPConnectionPool.get_session()
                timeout = aiohttp.ClientTimeout(total=self.timeout_seconds)
                async with session.request(
                    method.upper(),
                    url,
                    params=params,
                    json=json_payload,
                    headers=headers,
                    timeout=timeout,
                ) as response:
                    if response.status not in expected:
                        body = await response.text()
                        last_error = f"HTTP {response.status}: {body[:200]}"
                        logger.warning("Microservice request failed %s %s (%s)", method, url, last_error)
                        continue
                    try:
                        return await response.json(content_type=None)
                    except Exception as exc:
                        last_error = f"invalid-json: {exc}"
                        logger.warning("Microservice returned invalid JSON for %s %s: %s", method, url, exc)
                        continue
            except asyncio.TimeoutError:
                last_error = "timeout"
                logger.warning("Microservice request timed out for %s %s", method, url)
                continue
            except Exception as exc:
                last_error = str(exc)
                logger.warning("Microservice request error for %s %s: %s", method, url, exc)
                continue
            finally:
                # Keep loop deterministic and avoid hammering all failed endpoints at once.
                if idx < len(self.base_urls) - 1:
                    await asyncio.sleep(0.05)

        if last_error:
            logger.debug("All microservice endpoints failed for %s %s: %s", method, path, last_error)
        return None

    async def search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        q = (query or "").strip()
        if not q:
            return []

        payload = await self._request(
            "GET",
            self.search_path,
            params={"q": q, "limit": max(1, int(limit or 1))},
            expected=(200,),
        )
        if not payload:
            return []

        items = payload.get("items") if isinstance(payload, dict) else payload
        if not isinstance(items, list):
            return []
        return [item for item in items if isinstance(item, dict)]

    async def resolve(self, track: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        payload = await self._request(
            "POST",
            self.resolve_path,
            json_payload=track or {},
            expected=(200,),
        )
        if isinstance(payload, dict):
            return payload
        return None

    async def health(self) -> Dict[str, Any]:
        if not self.base_urls:
            return {"configured": False, "healthy": False, "endpoints": []}

        details = {
            "configured": True,
            "healthy": False,
            "endpoints": [],
        }

        headers = self._headers()

        for base_url in self.base_urls:
            url = f"{base_url}{self.health_path}"
            endpoint_state: Dict[str, Any] = {"url": url, "ok": False}
            try:
                session = await HTTPConnectionPool.get_session()
                timeout = aiohttp.ClientTimeout(total=self.timeout_seconds)
                async with session.get(url, headers=headers, timeout=timeout) as response:
                    endpoint_state["status"] = response.status
                    if response.status == 200:
                        endpoint_state["ok"] = True
                        endpoint_state["payload"] = await response.json(content_type=None)
                        details["healthy"] = True
                    else:
                        endpoint_state["error"] = await response.text()
            except Exception as exc:
                endpoint_state["error"] = str(exc)
            details["endpoints"].append(endpoint_state)

        return details
