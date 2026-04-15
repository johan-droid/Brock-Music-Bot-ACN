"""SQLite-based cache fallback when Redis is not available."""

import os
import json
import time
import logging
import sqlite3
import threading
from typing import Optional, Any, List, Set
from datetime import datetime

logger = logging.getLogger(__name__)

# Thread-local storage for SQLite connections
_local = threading.local()

# Global in-memory cache for hot data
_memory_cache: dict = {}
_memory_ttl: dict = {}


class SQLiteCache:
    """SQLite-based cache with TTL support - zero-cost alternative to Redis."""
    
    def __init__(self, db_path: str = "./data/cache.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()
    
    def _get_conn(self) -> sqlite3.Connection:
        """Get thread-local connection."""
        if not hasattr(_local, 'conn') or _local.conn is None:
            _local.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            _local.conn.row_factory = sqlite3.Row
        return _local.conn
    
    def _init_db(self):
        """Initialize database tables."""
        conn = self._get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cache (
                key TEXT PRIMARY KEY,
                value TEXT,
                ttl INTEGER,
                created_at INTEGER
            )
        """)
        
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sets (
                key TEXT,
                member TEXT,
                ttl INTEGER,
                created_at INTEGER,
                PRIMARY KEY (key, member)
            )
        """)
        
        conn.execute("""
            CREATE TABLE IF NOT EXISTS lists (
                key TEXT,
                idx INTEGER,
                value TEXT,
                ttl INTEGER,
                created_at INTEGER,
                PRIMARY KEY (key, idx)
            )
        """)
        
        conn.commit()
    
    def _is_expired(self, row: sqlite3.Row) -> bool:
        """Check if row is expired."""
        ttl = row['ttl']
        if ttl is None or ttl == 0:
            return False
        created = row['created_at']
        return (time.time() - created) > ttl
    
    def _cleanup_expired(self):
        """Remove expired entries."""
        conn = self._get_conn()
        now = time.time()
        conn.execute("DELETE FROM cache WHERE ttl > 0 AND (? - created_at) > ttl", (now,))
        conn.execute("DELETE FROM sets WHERE ttl > 0 AND (? - created_at) > ttl", (now,))
        conn.execute("DELETE FROM lists WHERE ttl > 0 AND (? - created_at) > ttl", (now,))
        conn.commit()
    
    # String operations
    async def get(self, key: str) -> Optional[str]:
        """Get string value."""
        # Check memory first
        if key in _memory_cache:
            if key in _memory_ttl and time.time() < _memory_ttl[key]:
                return _memory_cache[key]
            else:
                del _memory_cache[key]
                if key in _memory_ttl:
                    del _memory_ttl[key]
        
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM cache WHERE key = ?", (key,)).fetchone()
        
        if row and not self._is_expired(row):
            return row['value']
        
        if row:
            # Clean up expired
            conn.execute("DELETE FROM cache WHERE key = ?", (key,))
            conn.commit()
        
        return None
    
    async def set(self, key: str, value: str, ex: int = 0):
        """Set string value with optional TTL."""
        # Store in memory for hot data (< 5 min TTL)
        if 0 < ex <= 300:
            _memory_cache[key] = value
            _memory_ttl[key] = time.time() + ex
        
        conn = self._get_conn()
        now = time.time()
        conn.execute(
            """INSERT OR REPLACE INTO cache (key, value, ttl, created_at) 
               VALUES (?, ?, ?, ?)""",
            (key, value, ex, int(now))
        )
        conn.commit()
    
    async def delete(self, key: str) -> int:
        """Delete key(s)."""
        if key in _memory_cache:
            del _memory_cache[key]
            if key in _memory_ttl:
                del _memory_ttl[key]
        
        conn = self._get_conn()
        cursor = conn.execute("DELETE FROM cache WHERE key = ?", (key,))
        conn.commit()
        return cursor.rowcount
    
    async def exists(self, key: str) -> int:
        """Check if key exists."""
        if key in _memory_cache:
            if key not in _memory_ttl or time.time() < _memory_ttl[key]:
                return 1
        
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM cache WHERE key = ?", (key,)).fetchone()
        
        if row and not self._is_expired(row):
            return 1
        
        return 0
    
    # List operations
    async def lpush(self, key: str, *values: str):
        """Push values to left of list."""
        conn = self._get_conn()
        
        # Get current max index
        row = conn.execute("SELECT MIN(idx) as min_idx FROM lists WHERE key = ?", (key,)).fetchone()
        start_idx = (row['min_idx'] or 0) - len(values)
        
        now = int(time.time())
        for i, val in enumerate(values):
            conn.execute(
                "INSERT INTO lists (key, idx, value, ttl, created_at) VALUES (?, ?, ?, 0, ?)",
                (key, start_idx + i, val, now)
            )
        
        conn.commit()
    
    async def rpush(self, key: str, *values: str):
        """Push values to right of list."""
        conn = self._get_conn()
        
        # Get current max index
        row = conn.execute("SELECT MAX(idx) as max_idx FROM lists WHERE key = ?", (key,)).fetchone()
        start_idx = (row['max_idx'] or -1) + 1
        
        now = int(time.time())
        for i, val in enumerate(values):
            conn.execute(
                "INSERT INTO lists (key, idx, value, ttl, created_at) VALUES (?, ?, ?, 0, ?)",
                (key, start_idx + i, val, now)
            )
        
        conn.commit()
    
    async def lpop(self, key: str) -> Optional[str]:
        """Pop from left of list."""
        conn = self._get_conn()
        
        row = conn.execute(
            "SELECT * FROM lists WHERE key = ? ORDER BY idx ASC LIMIT 1", (key,)
        ).fetchone()
        
        if row:
            conn.execute("DELETE FROM lists WHERE key = ? AND idx = ?", (key, row['idx']))
            conn.commit()
            return row['value']
        
        return None
    
    async def lindex(self, key: str, index: int) -> Optional[str]:
        """Get element at index."""
        conn = self._get_conn()
        
        # Get all items and index
        rows = conn.execute(
            "SELECT * FROM lists WHERE key = ? ORDER BY idx ASC", (key,)
        ).fetchall()
        
        if 0 <= index < len(rows):
            return rows[index]['value']
        
        return None
    
    async def llen(self, key: str) -> int:
        """Get list length."""
        conn = self._get_conn()
        row = conn.execute("SELECT COUNT(*) as cnt FROM lists WHERE key = ?", (key,)).fetchone()
        return row['cnt']
    
    async def lrange(self, key: str, start: int, end: int) -> List[str]:
        """Get range of list elements."""
        conn = self._get_conn()
        
        rows = conn.execute(
            "SELECT * FROM lists WHERE key = ? ORDER BY idx ASC", (key,)
        ).fetchall()
        
        if end == -1:
            end = len(rows)
        else:
            end = end + 1  # Redis end is inclusive
        
        return [r['value'] for r in rows[start:end]]
    
    async def ltrim(self, key: str, start: int, end: int) -> None:
        """Trim list to specified range, removing elements outside it."""
        conn = self._get_conn()
        
        # Get all rows sorted by index
        rows = conn.execute(
            "SELECT idx FROM lists WHERE key = ? ORDER BY idx ASC", (key,)
        ).fetchall()
        
        # Calculate which indices to keep
        if end == -1:
            end = len(rows) - 1
        
        rows_to_keep = set()
        for i in range(max(0, start), min(end + 1, len(rows))):
            rows_to_keep.add(rows[i]['idx'])
        
        # Delete all rows not in range
        placeholders = ', '.join('?' * len(rows_to_keep)) if rows_to_keep else 'NULL'
        if rows_to_keep:
            conn.execute(
                f"DELETE FROM lists WHERE key = ? AND idx NOT IN ({placeholders})",
                (key, *rows_to_keep)
            )
        else:
            conn.execute("DELETE FROM lists WHERE key = ?", (key,))
        
        conn.commit()

    # Set operations
    async def sadd(self, key: str, *members: str):
        """Add members to set."""
        conn = self._get_conn()
        now = int(time.time())
        
        for member in members:
            conn.execute(
                """INSERT OR REPLACE INTO sets (key, member, ttl, created_at) 
                   VALUES (?, ?, 0, ?)""",
                (key, member, now)
            )
        
        conn.commit()
    
    async def srem(self, key: str, member: str):
        """Remove member from set."""
        conn = self._get_conn()
        conn.execute("DELETE FROM sets WHERE key = ? AND member = ?", (key, member))
        conn.commit()
    
    async def sismember(self, key: str, member: str) -> bool:
        """Check if member exists in set."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM sets WHERE key = ? AND member = ?", (key, member)
        ).fetchone()
        return row is not None
    
    async def smembers(self, key: str) -> Set[str]:
        """Get all set members."""
        conn = self._get_conn()
        rows = conn.execute("SELECT member FROM sets WHERE key = ?", (key,)).fetchall()
        return {r['member'] for r in rows}
    
    async def expire(self, key: str, seconds: int):
        """Set TTL on key."""
        conn = self._get_conn()
        now = int(time.time())
        
        # Update cache table
        conn.execute(
            "UPDATE cache SET ttl = ?, created_at = ? WHERE key = ?",
            (seconds, now, key)
        )
        
        # Update sets table
        conn.execute(
            "UPDATE sets SET ttl = ?, created_at = ? WHERE key = ?",
            (seconds, now, key)
        )
        
        # Update lists table
        conn.execute(
            "UPDATE lists SET ttl = ?, created_at = ? WHERE key = ?",
            (seconds, now, key)
        )
        
        conn.commit()


# Global instance
sqlite_cache: Optional[SQLiteCache] = None


def init_sqlite_cache(db_path: str = "./data/cache.db"):
    """Initialize SQLite cache."""
    global sqlite_cache
    sqlite_cache = SQLiteCache(db_path)
    logger.info(f"SQLite cache initialized at {db_path}")
