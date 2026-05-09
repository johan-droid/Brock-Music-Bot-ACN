```sql
-- 1. Optimized SQLite Schema and High-Concurrency Pragmas
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA cache_size = -64000;
PRAGMA temp_store = MEMORY;
PRAGMA mmap_size = 268435456;
PRAGMA busy_timeout = 5000;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS lobby_snapshots (
    chat_id INTEGER PRIMARY KEY,
    now_playing TEXT,
    status TEXT DEFAULT 'idle',
    position_seconds INTEGER DEFAULT 0,
    participants TEXT DEFAULT '[]',
    version INTEGER DEFAULT 1,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_lobby_snapshots_updated_at ON lobby_snapshots(updated_at);

CREATE TABLE IF NOT EXISTS queue_tracks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    position INTEGER NOT NULL,
    track_id TEXT,
    title TEXT,
    artist TEXT,
    duration INTEGER,
    stream_url TEXT,
    thumbnail TEXT,
    source TEXT,
    added_by INTEGER,
    metadata TEXT,
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(chat_id) REFERENCES lobby_snapshots(chat_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_queue_chat_position ON queue_tracks(chat_id, position);

CREATE TABLE IF NOT EXISTS track_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    user_id INTEGER,
    track_id TEXT,
    title TEXT,
    played_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_history_chat_time ON track_history(chat_id, played_at DESC);

CREATE TABLE IF NOT EXISTS analytics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    chat_id INTEGER,
    user_id INTEGER,
    event_data TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_analytics_type_time ON analytics(event_type, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_analytics_chat ON analytics(chat_id);

CREATE TABLE IF NOT EXISTS user_roles (
    user_id INTEGER NOT NULL,
    chat_id INTEGER NOT NULL,
    role TEXT NOT NULL,
    assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, chat_id)
);
CREATE INDEX IF NOT EXISTS idx_user_roles_chat ON user_roles(chat_id);
```

```python
# 2. Connection pooling, pragmas, and explicit transactions
import asyncio
import json
from typing import Dict, Any, List
import aiosqlite

class DatabasePool:
    def __init__(self, db_path: str = "./data/bot.db", pool_size: int = 5):
        self.db_path = db_path
        self.pool_size = pool_size
        self._pool: asyncio.Queue = asyncio.Queue(maxsize=pool_size)
        self._initialized = False

    async def init_pool(self):
        if self._initialized:
            return

        for _ in range(self.pool_size):
            conn = await aiosqlite.connect(self.db_path, isolation_level=None)
            conn.row_factory = aiosqlite.Row
            await conn.execute("PRAGMA journal_mode = WAL;")
            await conn.execute("PRAGMA synchronous = NORMAL;")
            await conn.execute("PRAGMA cache_size = -64000;")
            await conn.execute("PRAGMA temp_store = MEMORY;")
            await conn.execute("PRAGMA mmap_size = 268435456;")
            await conn.execute("PRAGMA busy_timeout = 5000;")
            await conn.execute("PRAGMA foreign_keys = ON;")
            await self._pool.put(conn)

        self._initialized = True

    class _ConnectionContextManager:
        def __init__(self, pool: 'DatabasePool'):
            self.pool = pool
            self.conn = None

        async def __aenter__(self) -> aiosqlite.Connection:
            self.conn = await self.pool._pool.get()
            return self.conn

        async def __aexit__(self, exc_type, exc, tb):
            await self.pool._pool.put(self.conn)

    def acquire(self):
        return self._ConnectionContextManager(self)

    async def close(self):
        while not self._pool.empty():
            conn = await self._pool.get()
            await conn.close()

class QueueManager:
    def __init__(self, pool: DatabasePool):
        self.pool = pool

    async def add_to_queue(self, chat_id: int, tracks: List[Dict[str, Any]]):
        async with self.pool.acquire() as conn:
            await conn.execute("BEGIN IMMEDIATE")
            try:
                cursor = await conn.execute(
                    "SELECT COALESCE(MAX(position), 0) as max_pos FROM queue_tracks WHERE chat_id = ?"
                , (chat_id,))
                row = await cursor.fetchone()
                current_max = row['max_pos'] if row else 0

                track_tuples = []
                for idx, track in enumerate(tracks, start=1):
                    track_tuples.append((
                        chat_id,
                        current_max + idx,
                        track.get("track_id") or track.get("id"),
                        track.get("title"),
                        track.get("artist"),
                        track.get("duration", 0),
                        track.get("stream_url") or track.get("url"),
                        track.get("thumbnail"),
                        track.get("source"),
                        track.get("added_by"),
                        json.dumps(track.get("metadata", {}))
                    ))

                await conn.executemany("""
                    INSERT INTO queue_tracks
                    (chat_id, position, track_id, title, artist, duration, stream_url, thumbnail, source, added_by, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, track_tuples)

                await conn.execute("COMMIT")
            except Exception:
                await conn.execute("ROLLBACK")
                raise

    async def get_queue(self, chat_id: int) -> List[Dict[str, Any]]:
        async with self.pool.acquire() as conn:
            cursor = await conn.execute(
                "SELECT * FROM queue_tracks WHERE chat_id = ? ORDER BY position ASC",
                (chat_id,)
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
```

```python
# 3. Data Migration Script (JSON queue -> Relational table)
async def migrate_json_queue_to_relational(pool: DatabasePool):
    async with pool.acquire() as conn:
        try:
            cursor = await conn.execute("SELECT chat_id, queue FROM lobby_snapshots WHERE queue IS NOT NULL AND queue != '[]'")
            rows = await cursor.fetchall()
        except aiosqlite.OperationalError:
            return

        if not rows:
            return

        await conn.execute("BEGIN IMMEDIATE")
        try:
            track_tuples = []
            for row in rows:
                chat_id = row['chat_id']
                try:
                    queue_data = json.loads(row['queue'])
                    for pos, track in enumerate(queue_data, start=1):
                        track_tuples.append((
                            chat_id,
                            pos,
                            track.get("track_id") or track.get("id"),
                            track.get("title"),
                            track.get("artist"),
                            track.get("duration", 0),
                            track.get("stream_url") or track.get("url"),
                            track.get("thumbnail"),
                            track.get("source"),
                            track.get("added_by"),
                            json.dumps(track.get("metadata", {}))
                        ))
                except json.JSONDecodeError:
                    continue

            if track_tuples:
                await conn.executemany("""
                    INSERT INTO queue_tracks
                    (chat_id, position, track_id, title, artist, duration, stream_url, thumbnail, source, added_by, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, track_tuples)

            await conn.executescript("""
                CREATE TABLE lobby_snapshots_new (
                    chat_id INTEGER PRIMARY KEY,
                    now_playing TEXT,
                    status TEXT DEFAULT 'idle',
                    position_seconds INTEGER DEFAULT 0,
                    participants TEXT DEFAULT '[]',
                    version INTEGER DEFAULT 1,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                INSERT INTO lobby_snapshots_new (chat_id, now_playing, status, position_seconds, participants, version, updated_at, created_at)
                SELECT chat_id, now_playing, status, position_seconds, participants, version, updated_at, created_at
                FROM lobby_snapshots;

                DROP TABLE lobby_snapshots;
                ALTER TABLE lobby_snapshots_new RENAME TO lobby_snapshots;
                CREATE INDEX IF NOT EXISTS idx_lobby_snapshots_updated_at ON lobby_snapshots(updated_at);
            """)

            await conn.execute("COMMIT")
        except Exception:
            await conn.execute("ROLLBACK")
            raise
```

```sql
-- 4. Query Optimization Checklist

-- 4a. Fetching recent tracks for a chat (Pagination / Cursor-based)
-- Uses: CREATE INDEX idx_history_chat_time ON track_history(chat_id, played_at DESC);
SELECT track_id, title, played_at
FROM track_history
WHERE chat_id = ?
ORDER BY played_at DESC
LIMIT 50 OFFSET 0;

-- 4b. Grouping analytics events by type within a time range
-- Uses: CREATE INDEX idx_analytics_type_time ON analytics(event_type, created_at DESC);
SELECT event_type, COUNT(*) as count
FROM analytics
WHERE event_type = ? AND created_at > datetime('now', '-7 days')
GROUP BY event_type;

-- 4c. Fetching top active users per chat
-- Uses: CREATE INDEX idx_analytics_chat ON analytics(chat_id);
SELECT user_id, COUNT(*) as total_events
FROM analytics
WHERE chat_id = ? AND event_type = 'play'
GROUP BY user_id
ORDER BY total_events DESC
LIMIT 10;

-- 4d. Checking if a user has a specific role (Fast point queries)
-- Uses: PRIMARY KEY (user_id, chat_id)
SELECT role
FROM user_roles
WHERE user_id = ? AND chat_id = ?;

-- 4e. Listing all admins for a specific chat
-- Uses: CREATE INDEX idx_user_roles_chat ON user_roles(chat_id);
SELECT user_id, role
FROM user_roles
WHERE chat_id = ? AND role = 'admin';
```
