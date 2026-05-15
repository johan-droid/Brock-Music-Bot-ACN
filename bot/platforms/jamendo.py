import aiohttp
import asyncio
import logging
import os
from typing import List, Dict, Any, Optional

from config import config
from bot.utils.circuit_breaker import retry_with_backoff

logger = logging.getLogger(__name__)

class JamendoClient:
    """Resilient Jamendo API Client with Circuit Breaker & Rate Limiting."""

    BASE_URL = "https://api.jamendo.com/v3.0"

    def __init__(self, client_id: str = None):
        self.client_id = client_id or "56d30c95" # Public default/test ID if none provided
        self._session: Optional[aiohttp.ClientSession] = None
        self._cache: Dict[str, Any] = {}
        self.circuit_open = False
        self.failures = 0

    def is_configured(self) -> bool:
        """Check if Jamendo API is configured."""
        return bool(self.client_id)

    def generate_oauth_url(self, state: Any) -> str:
        """Generate OAuth URL for Jamendo."""
        if not self.is_configured():
            return ""
        redirect_uri = getattr(config, "JAMENDO_REDIRECT_URI", "http://localhost:8000/callback")
        return f"https://api.jamendo.com/v3.0/oauth/authorize?client_id={self.client_id}&redirect_uri={redirect_uri}&state={state}"

    async def get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            # Enforce 8-second timeout on all requests per requirements
            timeout = aiohttp.ClientTimeout(total=8.0)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    @retry_with_backoff(retries=5, base_delay=1.0, max_delay=10.0)
    async def _request(self, endpoint: str, params: Dict[str, Any]) -> Any:
        if self.circuit_open:
            logger.warning("Jamendo circuit open. Using degraded mode (cache).")
            cache_key = f"{endpoint}_{hash(frozenset(params.items()))}"
            if cache_key in self._cache:
                return self._cache[cache_key]
            raise Exception("Circuit open and no cache available")

        params["client_id"] = self.client_id
        params["format"] = "json"

        session = await self.get_session()

        try:
            async with session.get(f"{self.BASE_URL}/{endpoint}", params=params) as response:
                if response.status == 429:
                    retry_after = int(response.headers.get("Retry-After", 5))
                    logger.warning(f"Jamendo Rate Limited (429). Waiting {retry_after}s.")
                    await asyncio.sleep(retry_after)
                    raise aiohttp.ClientResponseError(
                        request_info=response.request_info,
                        history=response.history,
                        status=response.status,
                        message="Rate Limited"
                    )

                if response.status >= 500:
                    self.failures += 1
                    if self.failures >= 3:
                        logger.error("Jamendo 5xx errors threshold reached. Opening circuit.")
                        self.circuit_open = True
                        asyncio.create_task(self._reset_circuit())
                    raise aiohttp.ClientResponseError(
                        request_info=response.request_info,
                        history=response.history,
                        status=response.status,
                        message="Server Error"
                    )

                response.raise_for_status()
                data = await response.json()

                # Success - Reset circuit breaker state
                self.failures = 0
                self.circuit_open = False

                # Cache successful response for degraded mode
                cache_key = f"{endpoint}_{hash(frozenset(params.items()))}"
                self._cache[cache_key] = data
                return data

        except asyncio.TimeoutError as e:
            logger.error("Jamendo request timed out")
            raise Exception("Timeout") from e

    async def _reset_circuit(self):
        """Reset circuit breaker after 30 seconds."""
        await asyncio.sleep(30)
        logger.info("Jamendo circuit half-open. Attempting recovery.")
        self.circuit_open = False

    async def search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Search tracks on Jamendo."""
        params = {
            "search": query,
            "limit": limit,
            "imagesize": "600",
            "audioformat": "mp32"
        }
        try:
            data = await self._request("tracks", params)
            return data.get("results", [])
        except Exception as e:
            logger.error(f"Jamendo search failed: {e}")
            return []

    async def extract(self, track_id: str) -> Optional[Dict[str, Any]]:
        """Extract track details from Jamendo."""
        params = {
            "id": track_id,
            "imagesize": "600",
            "audioformat": "mp32"
        }
        try:
            data = await self._request("tracks", params)
            results = data.get("results", [])
            if results:
                track = results[0]
                return {
                    "id": track["id"],
                    "title": track["name"],
                    "artist": track["artist_name"],
                    "duration": int(track.get("duration", 0)),
                    "url": track.get("audio"),
                    "stream_url": track.get("audio"),
                    "thumbnail": track.get("image"),
                    "source": "jamendo"
                }
            return None
        except Exception as e:
            logger.error(f"Jamendo extract failed: {e}")
            return None

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

jamendo_client = JamendoClient(os.getenv("JAMENDO_CLIENT_ID"))
