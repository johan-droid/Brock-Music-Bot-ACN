"""HTTP client for remote music microservices."""

from __future__ import annotations

import asyncio
import aiohttp
import logging
import time
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
        cold_start_timeout_seconds: int = 50,
        token: Optional[str] = None,
        token_header: str = "Authorization",
    ) -> None:
        self.base_urls = _normalize_urls(base_urls)
        self.search_path = self._normalize_path(search_path, default="/search")
        self.resolve_path = self._normalize_path(resolve_path, default="/resolve")
        self.health_path = self._normalize_path(health_path, default="/health")
        self.timeout_seconds = max(4, int(timeout_seconds or 12))
        self.cold_start_timeout_seconds = max(self.timeout_seconds, int(cold_start_timeout_seconds or 50))
        self.token = (token or "").strip() or None
        self.token_header = (token_header or "Authorization").strip() or "Authorization"
        self._endpoint_state: Dict[str, Dict[str, Any]] = {
            base_url: {
                "failures": 0,
                "successes": 0,
                "cooldown_until": 0.0,
                "last_error": None,
                "last_latency_ms": None,
            }
            for base_url in self.base_urls
        }

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

    def _ordered_base_urls(self) -> List[str]:
        now = time.time()

        def sort_key(base_url: str) -> tuple[int, float, int]:
            state = self._endpoint_state.setdefault(
                base_url,
                {"failures": 0, "successes": 0, "cooldown_until": 0.0, "last_error": None, "last_latency_ms": None},
            )
            cooling = 1 if state.get("cooldown_until", 0.0) > now else 0
            latency = float(state.get("last_latency_ms") or 0.0)
            failures = int(state.get("failures") or 0)
            return (cooling, latency, failures)

        return sorted(self.base_urls, key=sort_key)

    def _record_endpoint_success(self, base_url: str, latency_ms: Optional[float] = None) -> None:
        state = self._endpoint_state.setdefault(
            base_url,
            {"failures": 0, "successes": 0, "cooldown_until": 0.0, "last_error": None, "last_latency_ms": None},
        )
        state["successes"] = int(state.get("successes") or 0) + 1
        state["failures"] = 0
        state["cooldown_until"] = 0.0
        state["last_error"] = None
        if latency_ms is not None:
            state["last_latency_ms"] = round(float(latency_ms), 2)

    def _record_endpoint_failure(self, base_url: str, error: str) -> None:
        state = self._endpoint_state.setdefault(
            base_url,
            {"failures": 0, "successes": 0, "cooldown_until": 0.0, "last_error": None, "last_latency_ms": None},
        )
        failures = int(state.get("failures") or 0) + 1
        state["failures"] = failures
        state["last_error"] = error
        # No cooldown - always use the configured URL regardless of failures
        state["cooldown_until"] = 0.0

    @staticmethod
    def _is_render_endpoint(base_url: str) -> bool:
        return "onrender.com" in (base_url or "").lower()

    def _allow_cold_start_retry(self, base_url: str) -> bool:
        # Cold start retry is disabled - use only the configured URL without special retry logic
        return False

    def is_initial_render_cold_start(self) -> bool:
        # Cold start detection is disabled - always return False
        return False

    @staticmethod
    def _extract_items(payload: Any) -> List[Dict[str, Any]]:
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]

        if not isinstance(payload, dict):
            return []

        for key in ("items", "results", "tracks", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]

        return []

    @staticmethod
    def _extract_track(payload: Any) -> Optional[Dict[str, Any]]:
        if isinstance(payload, dict):
            for key in ("item", "track", "result", "data"):
                value = payload.get(key)
                if isinstance(value, dict):
                    return value
            return payload
        return None

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json_payload: Optional[Dict[str, Any]] = None,
        expected: tuple[int, ...] = (200,),
        non_fatal_statuses: tuple[int, ...] = (),
    ) -> Optional[Dict[str, Any]]:
        if not self.base_urls:
            return None

        headers = self._headers()
        last_error: Optional[str] = None

        # Use only the first configured URL - no fallback to other endpoints
        base_url = self.base_urls[0]
        url = f"{base_url}{path}"
        
        timeout = aiohttp.ClientTimeout(total=self.timeout_seconds)
        started = time.time()
        try:
            session = await HTTPConnectionPool.get_session()
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
                    if response.status not in non_fatal_statuses:
                        self._record_endpoint_failure(base_url, last_error)
                    logger.warning("Microservice request failed %s %s (%s)", method, url, last_error)
                    return None
                try:
                    payload = await response.json(content_type=None)
                    self._record_endpoint_success(base_url, (time.time() - started) * 1000.0)
                    return payload
                except Exception as exc:
                    last_error = f"invalid-json: {exc}"
                    self._record_endpoint_failure(base_url, last_error)
                    logger.warning("Microservice returned invalid JSON for %s %s: %s", method, url, exc)
                    return None
        except asyncio.TimeoutError:
            last_error = "timeout"
            self._record_endpoint_failure(base_url, last_error)
            logger.warning("Microservice request timed out for %s %s", method, url)
            return None
        except Exception as exc:
            last_error = str(exc)
            self._record_endpoint_failure(base_url, last_error)
            logger.warning("Microservice request error for %s %s: %s", method, url, exc)
            return None

        if last_error:
            logger.debug("Microservice endpoint failed for %s %s: %s", method, path, last_error)
        return None

    async def search(self, query: str, limit: int = 10, routing: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        q = (query or "").strip()
        if not q:
            return []

        # First try with routing hints if provided
        if routing:
            routed_payload = await self._request(
                "POST",
                self.search_path,
                json_payload={
                    "query": q,
                    "limit": max(1, int(limit or 1)),
                    "routing": routing,
                },
                expected=(200,),
                non_fatal_statuses=(404, 405, 501),
            )
            items = self._extract_items(routed_payload)
            if items:
                return items

        # Primary search with 'q' parameter
        payload = await self._request(
            "GET",
            self.search_path,
            params={"q": q, "limit": max(1, int(limit or 1))},
            expected=(200,),
        )
        items = self._extract_items(payload)
        if items:
            return items

        # No fallback - return empty if the configured microservice returns nothing
        return []

    async def resolve(self, track: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        payload = await self._request(
            "POST",
            self.resolve_path,
            json_payload=track or {},
            expected=(200,),
        )
        return self._extract_track(payload)

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
            endpoint_state["client_state"] = self._endpoint_state.get(base_url, {})
            details["endpoints"].append(endpoint_state)

        return details
