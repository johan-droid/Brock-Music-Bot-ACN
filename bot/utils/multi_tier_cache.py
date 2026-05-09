import asyncio
import json
import logging
from typing import Any, Dict, Optional, Tuple
from collections import OrderedDict

# Assuming _cache_module.redis_client is initialized in bot/utils/cache.py
import bot.utils.cache as _cache_module

logger = logging.getLogger(__name__)

class L1Cache:
    """In-memory LRU cache for high-frequency access (L1)."""
    def __init__(self, capacity: int = 1000):
        self.capacity = capacity
        self.cache: OrderedDict[str, Any] = OrderedDict()
        self.lock = asyncio.Lock()

    async def get(self, key: str) -> Optional[Any]:
        async with self.lock:
            if key in self.cache:
                self.cache.move_to_end(key)
                # Mark as L1 hit for metrics
                return self.cache[key]
            return None

    async def set(self, key: str, value: Any):
        async with self.lock:
            self.cache[key] = value
            self.cache.move_to_end(key)
            if len(self.cache) > self.capacity:
                self.cache.popitem(last=False)

    async def delete(self, key: str):
        async with self.lock:
            if key in self.cache:
                del self.cache[key]

    async def clear(self):
        async with self.lock:
            self.cache.clear()


class MultiTierCache:
    """Two-tier cache system: L1 (in-memory) + L2 (Redis/SQLite)."""

    def __init__(self, l1_capacity: int = 1000):
        self.l1 = L1Cache(capacity=l1_capacity)
        # Metrics counters
        self.hits_l1 = 0
        self.hits_l2 = 0
        self.misses = 0

    async def _get_l2(self, key: str) -> Optional[str]:
        """Non-blocking L2 cache fetch with fallback."""
        try:
            if _cache_module.CACHE_MODE == "redis" and _cache_module.redis_client:
                return await _cache_module.redis_client.get(key)
            elif _cache_module.sqlite_cache:
                return await _cache_module.sqlite_cache.get(key)
        except Exception as e:
            logger.warning(f"L2 cache fetch failed: {e}")
            return None
        return None

    async def _set_l2(self, key: str, value: str, ttl: int):
        """Non-blocking L2 cache set (fire and forget)."""
        async def _set():
            try:
                if _cache_module.CACHE_MODE == "redis" and _cache_module.redis_client:
                    await _cache_module.redis_client.set(key, value, ex=ttl)
                elif _cache_module.sqlite_cache:
                    await _cache_module.sqlite_cache.set(key, value, ex=ttl)
            except Exception as e:
                logger.warning(f"L2 cache set failed: {e}")

        asyncio.create_task(_set())

    async def get(self, key: str, is_json: bool = True) -> Tuple[Optional[Any], str]:
        """Get value from L1 -> L2 -> Miss. Returns (value, hit_type)."""
        # Try L1 (Memory)
        val = await self.l1.get(key)
        if val is not None:
            self.hits_l1 += 1
            return val, "L1_HIT"

        # Try L2 (Redis/SQLite)
        l2_val = await self._get_l2(key)
        if l2_val is not None:
            self.hits_l2 += 1
            parsed_val = l2_val
            if is_json:
                try:
                    parsed_val = json.loads(l2_val)
                except json.JSONDecodeError:
                    pass

            # Promote to L1
            await self.l1.set(key, parsed_val)
            return parsed_val, "L2_HIT"

        self.misses += 1
        return None, "MISS"

    async def set(self, key: str, value: Any, ttl: int):
        """Set value in both L1 and L2 caches."""
        # Set L1
        await self.l1.set(key, value)

        # Set L2
        str_val = json.dumps(value) if not isinstance(value, str) else value
        await self._set_l2(key, str_val, ttl)

    async def delete(self, key: str):
        """Invalidate key in both caches."""
        # Delete L1
        await self.l1.delete(key)

        # Delete L2
        async def _del_l2():
            try:
                if _cache_module.CACHE_MODE == "redis" and _cache_module.redis_client:
                    await _cache_module.redis_client.delete(key)
                elif _cache_module.sqlite_cache:
                    await _cache_module.sqlite_cache.delete(key)
            except Exception as e:
                logger.warning(f"L2 cache delete failed: {e}")

        asyncio.create_task(_del_l2())

    def get_metrics(self) -> Dict[str, int]:
        """Export cache metrics."""
        return {
            "l1_hits": self.hits_l1,
            "l2_hits": self.hits_l2,
            "misses": self.misses,
            "total_requests": self.hits_l1 + self.hits_l2 + self.misses
        }

# Global instance
multi_cache = MultiTierCache(l1_capacity=1000)
