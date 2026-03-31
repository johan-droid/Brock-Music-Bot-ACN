"""Redis cache utilities with SQLite fallback for zero-cost deployment."""

import logging
import os
from typing import Optional
from config import config

logger = logging.getLogger(__name__)

# Global Redis client
redis_client = None
sqlite_cache = None

# Cache mode: "redis" or "sqlite"
CACHE_MODE = "sqlite"


async def init_redis():
    """Initialize Redis connection if configured, otherwise use SQLite."""
    global redis_client, sqlite_cache, CACHE_MODE
    
    # Try Upstash Redis first
    if config.UPSTASH_REDIS_REST_URL and config.UPSTASH_REDIS_REST_TOKEN:
        try:
            from upstash_redis.asyncio import Redis as UpstashRedis
            redis_client = UpstashRedis(
                url=config.UPSTASH_REDIS_REST_URL,
                token=config.UPSTASH_REDIS_REST_TOKEN
            )
            # Test connection
            await redis_client.ping()
            CACHE_MODE = "redis"
            logger.info("Upstash Redis cache connected")
            return
        except Exception as e:
            logger.warning(f"Upstash Redis connection failed, falling back to local Redis/SQLite: {e}")

    # Try local Redis next if configured
    if config.REDIS_HOST and config.REDIS_HOST != "redis":
        try:
            import redis.asyncio as aioredis
            redis_client = aioredis.Redis(
                host=config.REDIS_HOST,
                port=config.REDIS_PORT,
                password=config.REDIS_PASSWORD if config.REDIS_PASSWORD else None,
                decode_responses=True,
            )
            
            # Test connection
            await redis_client.ping()
            CACHE_MODE = "redis"
            logger.info("Local Redis cache connected")
            return
        except Exception as e:
            logger.warning(f"Local Redis connection failed, falling back to SQLite: {e}")
    
    # Use SQLite fallback
    from bot.utils.sqlite_cache import init_sqlite_cache, sqlite_cache as _sqlite
    sqlite_path = config.SQLITE_CACHE_PATH
    init_sqlite_cache(sqlite_path)
    sqlite_cache = _sqlite
    CACHE_MODE = "sqlite"
    logger.info("Using SQLite cache (zero-cost mode)")


class Cache:
    """Unified cache interface - uses Redis if available, else SQLite."""
    
    def _get_backend(self):
        """Get current backend client."""
        if CACHE_MODE == "redis" and redis_client:
            return redis_client
        return sqlite_cache
    
    # Admin cache
    async def cache_admins(self, chat_id: int, admin_ids: list, ttl: int = 60):
        """Cache admin list for a chat."""
        key = f"admins:{chat_id}"
        
        if CACHE_MODE == "redis" and redis_client:
            await redis_client.delete(key)
            if admin_ids:
                await redis_client.sadd(key, *admin_ids)
            await redis_client.expire(key, ttl)
        else:
            import json
            await sqlite_cache.set(key, json.dumps(admin_ids), ex=ttl)
    
    async def is_admin(self, chat_id: int, user_id: int) -> bool:
        """Check if user is admin (from cache)."""
        key = f"admins:{chat_id}"
        
        if CACHE_MODE == "redis" and redis_client:
            is_member = await redis_client.sismember(key, user_id)
            return bool(is_member)
        else:
            import json
            data = await sqlite_cache.get(key)
            if data:
                admin_ids = json.loads(data)
                return user_id in admin_ids
            return False
    
    async def get_cached_admins(self, chat_id: int) -> list:
        """Get cached admin list."""
        key = f"admins:{chat_id}"
        
        if CACHE_MODE == "redis" and redis_client:
            members = await redis_client.smembers(key)
            return [int(m) for m in members]
        else:
            import json
            data = await sqlite_cache.get(key)
            if data:
                return json.loads(data)
            return []
    
    async def invalidate_admins(self, chat_id: int):
        """Invalidate admin cache for a chat."""
        key = f"admins:{chat_id}"
        
        if CACHE_MODE == "redis" and redis_client:
            await redis_client.delete(key)
        else:
            await sqlite_cache.delete(key)
    
    # Bot admin status
    async def set_bot_admin(self, chat_id: int, is_admin: bool, ttl: int = 120):
        """Cache bot admin status."""
        key = f"bot_admin:{chat_id}"
        
        if CACHE_MODE == "redis" and redis_client:
            await redis_client.set(key, "1" if is_admin else "0", ex=ttl)
        else:
            await sqlite_cache.set(key, "1" if is_admin else "0", ex=ttl)
    
    async def is_bot_admin_cached(self, chat_id: int) -> bool:
        """Check cached bot admin status."""
        key = f"bot_admin:{chat_id}"
        
        if CACHE_MODE == "redis" and redis_client:
            val = await redis_client.get(key)
            return val == "1"
        else:
            val = await sqlite_cache.get(key)
            return val == "1"
    
    # Cooldown
    async def check_cooldown(self, user_id: int, command: str, cooldown: int = 3) -> bool:
        """Check if user is on cooldown for a command."""
        key = f"cooldown:{user_id}:{command}"
        
        if CACHE_MODE == "redis" and redis_client:
            exists = await redis_client.exists(key)
            if exists:
                return False
            await redis_client.set(key, "1", ex=cooldown)
            return True
        else:
            val = await sqlite_cache.get(key)
            if val:
                return False
            await sqlite_cache.set(key, "1", ex=cooldown)
            return True
    
    # Maintenance mode
    async def is_maintenance(self) -> bool:
        """Check if bot is in maintenance mode (persistent)."""
        key = "maintenance_mode_persistent"
        
        if CACHE_MODE == "redis" and redis_client:
            val = await redis_client.get(key)
            return val == "1"
        else:
            val = await sqlite_cache.get(key)
            return val == "1"
    
    async def set_maintenance(self, enabled: bool):
        """Set maintenance mode (persistent)."""
        key = "maintenance_mode_persistent"
        
        if CACHE_MODE == "redis" and redis_client:
            if enabled:
                await redis_client.set(key, "1")  # No TTL = Persistent
            else:
                await redis_client.delete(key)
        else:
            if enabled:
                await sqlite_cache.set(key, "1")  # No TTL = Persistent
            else:
                await sqlite_cache.delete(key)
    
    # Gban cache
    async def cache_gban(self, user_id: int, is_banned: bool, ttl: int = 300):
        """Cache gban status."""
        key = f"gban_cache:{user_id}"
        
        if CACHE_MODE == "redis" and redis_client:
            await redis_client.set(key, "1" if is_banned else "0", ex=ttl)
        else:
            await sqlite_cache.set(key, "1" if is_banned else "0", ex=ttl)
    
    async def is_gbanned_cached(self, user_id: int) -> bool:
        """Check cached gban status."""
        key = f"gban_cache:{user_id}"
        
        if CACHE_MODE == "redis" and redis_client:
            val = await redis_client.get(key)
            return val == "1"
        else:
            val = await sqlite_cache.get(key)
            return val == "1"
    
    # Queue operations (delegate to appropriate backend)
    async def lpush(self, key: str, *values: str):
        """List push left."""
        if CACHE_MODE == "redis" and redis_client:
            await redis_client.lpush(key, *values)
        else:
            await sqlite_cache.lpush(key, *values)
    
    async def rpush(self, key: str, *values: str):
        """List push right."""
        if CACHE_MODE == "redis" and redis_client:
            await redis_client.rpush(key, *values)
        else:
            await sqlite_cache.rpush(key, *values)
    
    async def lpop(self, key: str):
        """List pop left."""
        if CACHE_MODE == "redis" and redis_client:
            return await redis_client.lpop(key)
        else:
            return await sqlite_cache.lpop(key)
    
    async def lindex(self, key: str, index: int):
        """List get index."""
        if CACHE_MODE == "redis" and redis_client:
            return await redis_client.lindex(key, index)
        else:
            return await sqlite_cache.lindex(key, index)
    
    async def llen(self, key: str) -> int:
        """List length."""
        if CACHE_MODE == "redis" and redis_client:
            return await redis_client.llen(key)
        else:
            return await sqlite_cache.llen(key)
    
    async def lrange(self, key: str, start: int, end: int) -> list:
        """List range."""
        if CACHE_MODE == "redis" and redis_client:
            return await redis_client.lrange(key, start, end)
        else:
            return await sqlite_cache.lrange(key, start, end)
    
    async def delete(self, key: str) -> None:
        """Delete key."""
        if CACHE_MODE == "redis" and redis_client:
            await redis_client.delete(key)
        else:
            await sqlite_cache.delete(key)

    async def get(self, key: str) -> Optional[str]:
        """Generic get."""
        if CACHE_MODE == "redis" and redis_client:
            return await redis_client.get(key)
        else:
            return await sqlite_cache.get(key)

    async def set(self, key: str, value: str, ex: int = None) -> None:
        """Generic set with optional TTL in seconds."""
        if CACHE_MODE == "redis" and redis_client:
            if ex:
                await redis_client.set(key, value, ex=ex)
            else:
                await redis_client.set(key, value)
        else:
            await sqlite_cache.set(key, value, ex=ex)

    # ── Now Playing message tracking ─────────────────────────────────────────

    async def set_np_message(self, chat_id: int, msg_id: int) -> None:
        """Store the message ID of the current Now Playing card."""
        await self.set(f"np_msg:{chat_id}", str(msg_id), ex=86400)  # 24h max

    async def get_np_message(self, chat_id: int) -> Optional[int]:
        """Retrieve the stored NP message ID."""
        val = await self.get(f"np_msg:{chat_id}")
        return int(val) if val else None

    async def clear_np_message(self, chat_id: int) -> None:
        """Remove the NP message ID from cache."""
        await self.delete(f"np_msg:{chat_id}")

    # ── YouTube CDN URL cache ─────────────────────────────────────────────────

    async def cache_stream_url(self, video_id: str, data: str, ttl: int = 19800) -> None:
        """Cache a resolved YouTube CDN stream URL (default TTL: 5.5 hours)."""
        await self.set(f"yt_stream:{video_id}", data, ex=ttl)

    async def get_cached_stream_url(self, video_id: str) -> Optional[str]:
        """Retrieve a cached YouTube CDN stream URL."""
        return await self.get(f"yt_stream:{video_id}")


# Global cache instance
cache = Cache()

async def init_cache():
    """Initialize cache (alias kept for backward compat)."""
    await init_redis()
