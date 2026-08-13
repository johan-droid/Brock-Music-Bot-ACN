import aiohttp
import asyncio
from typing import Optional

class HTTPConnectionPool:
    """Centralized aiohttp connection pool for efficient requests."""

    _session: Optional[aiohttp.ClientSession] = None
    _lock = asyncio.Lock()

    @classmethod
    async def get_session(cls) -> aiohttp.ClientSession:
        """Get or create the global aiohttp session."""
        if cls._session is None or cls._session.closed:
            async with cls._lock:
                if cls._session is None or cls._session.closed:
                    # Connection pool tuning:
                    # - Limit max connections to prevent overwhelming the event loop
                    # - Limit max connections per host
                    # - Use DNS caching with a reasonable TTL
                    connector = aiohttp.TCPConnector(
                        limit=100,           # Total connection limit
                        limit_per_host=20,   # Limit per host (e.g., youtube.com)
                        ttl_dns_cache=300,   # Cache DNS lookups for 5 minutes
                        use_dns_cache=True,
                    )

                    # Stratified timeouts:
                    # - Connect timeout: 5s
                    # - Read/Write timeout: 15s (shorter than global to fail fast)
                    timeout = aiohttp.ClientTimeout(
                        total=30,      # Absolute max time for the whole request
                        connect=5,     # Max time to establish connection
                        sock_read=15,  # Max time between bytes read
                        sock_connect=5 # Max time to connect to socket
                    )

                    cls._session = aiohttp.ClientSession(
                        connector=connector,
                        timeout=timeout,
                        # Prevent memory leaks from large headers/cookies
                        cookie_jar=aiohttp.DummyCookieJar()
                    )
        return cls._session

    @classmethod
    async def close(cls):
        """Close the global session."""
        if cls._session and not cls._session.closed:
            await cls._session.close()
            cls._session = None
