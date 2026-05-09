# Caching and Connection Pooling Optimization Guide

## 1. Redis Integration Guide with Async Client
The system is integrated with Redis using the `upstash-redis` async client or `redis.asyncio` as a fallback.
- Distributed caching ensures high availability across nodes.
- Initialization takes place in `bot/utils/cache.py` inside `init_redis()`.
- When Redis is unavailable, the cache gracefully degrades to `sqlite_cache`.

## 2. Two-Tier Cache Strategy
A two-tier cache strategy is implemented in `bot/utils/multi_tier_cache.py`:
- **L1 Cache (In-Memory LRU):** High-speed `OrderedDict` limited to 1000 items. Ideal for extremely hot searches and rapid UI updates.
- **L2 Cache (Redis/SQLite):** Distributed cache for longer-term storage.
- **TTL Configurations:**
  - Search queries (1 hour TTL)
  - Resolved stream URLs (45 min TTL)
- Operations are non-blocking; L2 sets and deletes are dispatched via `asyncio.create_task()` to prevent blocking the event loop.

## 3. Cache Invalidation Rules
Cache invalidation ensures optimistic UI updates remain accurate and do not present stale states:
- **Queue Changes:** Triggers invalidation of `queue_snapshot` (both L1 and L2 caches) when tracks are added, removed, skipped, cleared, or shuffled.
- **Playback Status:** Triggers invalidation of `playback_state` when playback is paused, resumed, stopped, or loop/volume settings change.
- **Source Health:** Adaptive timeouts in the wrapper logic circumvent relying on caches from degraded source endpoints.

## 4. `aiohttp` Connection Pool Tuning
To prevent connection exhaustion and latency spikes, a centralized `HTTPConnectionPool` has been implemented in `bot/utils/http_pool.py`:
- **TCPConnector Limits:** Capped at 100 total connections, with a maximum of 20 connections per host.
- **DNS Caching:** Enabled (`use_dns_cache=True`) with a 5-minute TTL to reduce DNS lookup latency.
- **Stratified Timeouts:**
  - Total request timeout: 30s
  - Connect timeout: 5s
  - Socket read timeout: 15s (shorter than global to allow failing fast on hung streams)

## 5. Memory Leak Prevention Checklist
To maintain memory health, particularly around long-running processes or large payloads:
- [x] Use `aiohttp.DummyCookieJar()` in the global session pool to prevent the accumulation of unneeded tracking cookies over time.
- [x] Utilize `OrderedDict` with a strict `capacity` limit for the L1 cache to cap memory usage.
- [x] Use `sys.getsizeof()` or object tracking if extremely large search responses are encountered.
- [x] Implement non-blocking, fire-and-forget mechanisms for L2 cache writes and deletes.
- [x] Clear Now Playing (NP) message cache when the tracks end or the queue is stopped.

## Metrics Export
Cache metrics (L1 hits, L2 hits, and misses) are continuously tracked and can be exported via `multi_cache.get_metrics()` for performance monitoring.
