"""Redis cache utilities with SQLite fallback for zero-cost deployment."""

import logging
import os
import time
import json
from typing import Any, Dict, Optional
from config import config
from bot.utils.multi_tier_cache import multi_cache

logger = logging.getLogger(__name__)

# Global Redis client
redis_client = None
sqlite_cache = None

# Cache mode: "redis" or "sqlite"
CACHE_MODE = "sqlite"


async def init_redis():
    """Initialize Redis connection if configured, otherwise use SQLite."""
    global redis_client, sqlite_cache, CACHE_MODE
    from bot.utils.sqlite_cache import init_sqlite_cache, sqlite_cache as _sqlite
    init_sqlite_cache()
    sqlite_cache = _sqlite
    
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
    
    async def ltrim(self, key: str, start: int, end: int) -> None:
        """Trim list to specified range (remove elements outside range)."""
        if CACHE_MODE == "redis" and redis_client:
            await redis_client.ltrim(key, start, end)
        else:
            await sqlite_cache.ltrim(key, start, end)

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

    async def incr(self, key: str, amount: int = 1) -> int:
        """Atomically increment a key and return the new integer value.

        Uses Redis INCR semantics when available. Falls back to a best-effort
        increment using the SQLite cache when Redis is not available.
        """
        if CACHE_MODE == "redis" and redis_client:
            try:
                # redis-py/aioredis supports incr(name, amount)
                return int(await redis_client.incr(key, amount))
            except TypeError:
                # Some clients (Upstash) expose incr(key) without amount
                return int(await redis_client.incr(key))
        else:
            # Best-effort (non-atomic) fallback for SQLite cache
            val = await sqlite_cache.get(key)
            try:
                current = int(val) if val is not None else 0
            except Exception:
                current = 0
            current += amount
            # Persist new value (no TTL set here; caller should set TTL on first increment)
            await sqlite_cache.set(key, str(current))
            return current

    async def expire(self, key: str, seconds: int) -> bool:
        """Set TTL/expiry on a key. Returns True if the expiry was set (best-effort).

        Uses Redis EXPIRE when available, otherwise updates the SQLite TTL.
        """
        if CACHE_MODE == "redis" and redis_client:
            try:
                return bool(await redis_client.expire(key, seconds))
            except Exception:
                return False
        else:
            try:
                await sqlite_cache.expire(key, seconds)
                return True
            except Exception:
                return False

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

    # ── Resolved stream URL cache ─────────────────────────────────────────────

    async def cache_stream_url(self, video_id: str, data: str, ttl: int = 2700) -> None:
        """Cache a resolved stream URL (default TTL: 45m)."""
        await multi_cache.set(f"yt_stream:{video_id}", data, ttl=ttl)

    async def get_cached_stream_url(self, video_id: str) -> Optional[str]:
        """Retrieve a cached stream URL."""
        val, _ = await multi_cache.get(f"yt_stream:{video_id}", is_json=False)
        return val

    # ── Playback state cache (for ultra-responsive buttons) ──────────────────

    async def cache_playback_state(self, chat_id: int, status: str = None, loop_mode: str = None, 
                                   volume: int = None, shuffle: bool = None, ttl: int = 60) -> None:
        """Cache playback state for optimistic UI updates (TTL: 60s default)."""
        import json
        key = f"playback_state:{chat_id}"

        if CACHE_MODE == "redis" and redis_client:
            script = """
local current = redis.call('GET', KEYS[1])
local state = {}
if current and current ~= false and current ~= '' then
    local ok, decoded = pcall(cjson.decode, current)
    if ok and type(decoded) == 'table' then
        state = decoded
    end
end
if ARGV[1] ~= '' then state['status'] = ARGV[1] end
if ARGV[2] ~= '' then state['loop_mode'] = ARGV[2] end
if ARGV[3] ~= '' then state['volume'] = tonumber(ARGV[3]) end
if ARGV[4] ~= '' then state['shuffle'] = (ARGV[4] == 'true') end
local out = cjson.encode(state)
if ARGV[5] ~= '' then
    redis.call('SET', KEYS[1], out, 'EX', tonumber(ARGV[5]))
else
    redis.call('SET', KEYS[1], out)
end
return out
"""
            shuffle_arg = 'true' if shuffle else 'false' if shuffle is not None else ''
            eval_args = [
                status or "",
                loop_mode or "",
                str(volume) if volume is not None else "",
                shuffle_arg,
                str(ttl),
            ]

            # Upstash uses eval(script, keys=[...], args=[...]) while redis-py uses
            # eval(script, numkeys, key1, arg1, ...). Support both call styles.
            try:
                await redis_client.eval(script, keys=[key], args=eval_args)
            except TypeError:
                await redis_client.eval(script, 1, key, *eval_args)
            return

        # Fallback for SQLite or non-Redis caches
        existing = await self.get(key)
        state_dict = json.loads(existing) if existing else {}
        
        # Update only provided fields
        if status is not None:
            state_dict["status"] = status
        if loop_mode is not None:
            state_dict["loop_mode"] = loop_mode
        if volume is not None:
            state_dict["volume"] = volume
        if shuffle is not None:
            state_dict["shuffle"] = shuffle
        
        await self.set(key, json.dumps(state_dict), ex=ttl)
    
    async def get_playback_state(self, chat_id: int) -> dict:
        """Get cached playback state (or empty dict if not found)."""
        import json
        key = f"playback_state:{chat_id}"
        data = await self.get(key)
        
        if data:
            try:
                return json.loads(data)
            except json.JSONDecodeError:
                return {}
        return {}
    
    async def invalidate_playback_state(self, chat_id: int) -> None:
        """Invalidate playback state cache when stopping."""
        key = f"playback_state:{chat_id}"
        await self.delete(key)
        await multi_cache.delete(key)

    # ── Queue data cache (for batch queue button optimization) ───────────────

    async def cache_queue_snapshot(self, chat_id: int, current: Optional[dict], queue: list, ttl: int = 30) -> None:
        """Cache current track + queue list snapshot (TTL: 30s default, refreshes frequently for accuracy)."""
        import json
        key = f"queue_snapshot:{chat_id}"
        
        snapshot = {
            "current": current,
            "queue": queue,
            "timestamp": time.time()
        }
        
        await self.set(key, json.dumps(snapshot, default=str), ex=ttl)
    
    async def get_queue_snapshot(self, chat_id: int) -> Optional[dict]:
        """Get cached queue snapshot (current + queue list) or None if expired."""
        import json
        key = f"queue_snapshot:{chat_id}"
        data = await self.get(key)
        
        if data:
            try:
                return json.loads(data)
            except json.JSONDecodeError:
                return None
        return None
    
    async def invalidate_queue_snapshot(self, chat_id: int) -> None:
        """Invalidate queue snapshot when queue changes."""
        key = f"queue_snapshot:{chat_id}"
        await self.delete(key)
        await multi_cache.delete(key)

    # ── Mini App cache helpers ───────────────────────────────────────────────

    async def set_lobby_state(self, chat_id: int, state: Dict[str, Any], ttl: int = 300) -> None:
        """Cache mini app lobby snapshot for fast cold-start recovery."""
        key = f"mini:lobby:{chat_id}"
        await self.set(key, json.dumps(state, default=str), ex=ttl)

    async def get_lobby_state(self, chat_id: int) -> Optional[Dict[str, Any]]:
        """Fetch mini app lobby snapshot, if available."""
        key = f"mini:lobby:{chat_id}"
        raw = await self.get(key)
        if not raw:
            return None
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            return None

    async def get_user_preferences(self, user_id: int) -> Dict[str, Any]:
        """Fetch mini app user preferences from cached session document."""
        key = f"mini:session:{user_id}"
        raw = await self.get(key)
        if not raw:
            return {}
        try:
            data = json.loads(raw)
            if isinstance(data, dict) and isinstance(data.get("preferences"), dict):
                return data["preferences"]
            return {}
        except json.JSONDecodeError:
            return {}


# Global cache instance
cache = Cache()

async def init_cache():
    """Initialize cache (alias kept for backward compat)."""
    await init_redis()
