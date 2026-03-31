"""SQLite database fallback for zero-cost deployment."""

import os
import json
import logging
import sqlite3
import threading
from datetime import datetime
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

_local = threading.local()


class SQLiteDatabase:
    """SQLite-based database for zero-cost deployment."""
    
    def __init__(self, db_path: str = "./data/bot.db"):
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
        
        # Groups table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS groups (
                id INTEGER PRIMARY KEY,
                title TEXT,
                lang TEXT DEFAULT 'en',
                is_active INTEGER DEFAULT 1,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                settings TEXT DEFAULT '{}'  -- JSON
            )
        """)
        
        # Sudo users table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sudousers (
                id INTEGER PRIMARY KEY,
                name TEXT,
                added_by INTEGER,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Globally banned users
        conn.execute("""
            CREATE TABLE IF NOT EXISTS gbanned (
                id INTEGER PRIMARY KEY,
                reason TEXT,
                banned_by INTEGER,
                banned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Group-specific bans
        conn.execute("""
            CREATE TABLE IF NOT EXISTS groupbans (
                chat_id INTEGER,
                user_id INTEGER,
                banned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (chat_id, user_id)
            )
        """)
        
        conn.commit()
        logger.info(f"SQLite database initialized at {self.db_path}")
    
    # Group management
    async def get_group(self, chat_id: int) -> dict:
        """Get group settings or create default."""
        conn = self._get_conn()
        
        row = conn.execute("SELECT * FROM groups WHERE id = ?", (chat_id,)).fetchone()
        
        if not row:
            # Create default
            default_settings = {
                "play_on_join": True,
                "max_queue": 100,
                "vol_default": 100,
                "loop_mode": "none",
                "quality": "high",
                "thumb_mode": True,
            }
            
            conn.execute(
                "INSERT INTO groups (id, title, is_active, settings) VALUES (?, ?, ?, ?)",
                (chat_id, "", 1, json.dumps(default_settings))
            )
            conn.commit()
            
            return {
                "_id": chat_id,
                "title": "",
                "lang": "en",
                "is_active": True,
                "settings": default_settings
            }
        
        return {
            "_id": row["id"],
            "title": row["title"] or "",
            "lang": row["lang"] or "en",
            "is_active": bool(row["is_active"]),
            "settings": json.loads(row["settings"] or "{}")
        }
    
    async def update_group(self, chat_id: int, updates: dict):
        """Update group settings."""
        conn = self._get_conn()
        
        # Get current
        current = await self.get_group(chat_id)
        
        # Apply updates
        if "settings" in updates:
            current["settings"].update(updates["settings"])
            conn.execute(
                "UPDATE groups SET settings = ? WHERE id = ?",
                (json.dumps(current["settings"]), chat_id)
            )
        
        if "title" in updates:
            conn.execute("UPDATE groups SET title = ? WHERE id = ?", (updates["title"], chat_id))
        
        if "is_active" in updates:
            conn.execute(
                "UPDATE groups SET is_active = ? WHERE id = ?",
                (1 if updates["is_active"] else 0, chat_id)
            )
        
        conn.commit()
    
    async def set_group_active(self, chat_id: int, active: bool):
        """Set group active status."""
        conn = self._get_conn()
        conn.execute(
            "UPDATE groups SET is_active = ? WHERE id = ?",
            (1 if active else 0, chat_id)
        )
        conn.commit()
    
    # Sudo users
    async def add_sudo(self, user_id: int, name: str, added_by: int):
        """Add a sudo user."""
        conn = self._get_conn()
        conn.execute(
            """INSERT OR REPLACE INTO sudousers (id, name, added_by, added_at) 
               VALUES (?, ?, ?, ?)""",
            (user_id, name, added_by, datetime.utcnow())
        )
        conn.commit()
    
    async def remove_sudo(self, user_id: int):
        """Remove a sudo user."""
        conn = self._get_conn()
        conn.execute("DELETE FROM sudousers WHERE id = ?", (user_id,))
        conn.commit()
    
    async def get_sudo_users(self) -> list:
        """Get all sudo users."""
        conn = self._get_conn()
        rows = conn.execute("SELECT * FROM sudousers").fetchall()
        return [{"_id": r["id"], "name": r["name"], "added_by": r["added_by"]} for r in rows]
    
    async def is_sudo(self, user_id: int) -> bool:
        """Check if user is sudo."""
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM sudousers WHERE id = ?", (user_id,)).fetchone()
        return row is not None
    
    # Global bans
    async def gban_user(self, user_id: int, reason: str, banned_by: int):
        """Globally ban a user."""
        conn = self._get_conn()
        conn.execute(
            """INSERT OR REPLACE INTO gbanned (id, reason, banned_by, banned_at) 
               VALUES (?, ?, ?, ?)""",
            (user_id, reason, banned_by, datetime.utcnow())
        )
        conn.commit()
    
    async def ungban_user(self, user_id: int):
        """Remove global ban."""
        conn = self._get_conn()
        conn.execute("DELETE FROM gbanned WHERE id = ?", (user_id,))
        conn.commit()
    
    async def is_gbanned(self, user_id: int) -> bool:
        """Check if user is globally banned."""
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM gbanned WHERE id = ?", (user_id,)).fetchone()
        return row is not None
    
    # Group bans
    async def ban_user(self, chat_id: int, user_id: int):
        """Ban user in a specific group."""
        conn = self._get_conn()
        conn.execute(
            """INSERT OR REPLACE INTO groupbans (chat_id, user_id, banned_at) 
               VALUES (?, ?, ?)""",
            (chat_id, user_id, datetime.utcnow())
        )
        conn.commit()
    
    async def unban_user(self, chat_id: int, user_id: int):
        """Unban user in a specific group."""
        conn = self._get_conn()
        conn.execute(
            "DELETE FROM groupbans WHERE chat_id = ? AND user_id = ?",
            (chat_id, user_id)
        )
        conn.commit()
    
    async def is_banned(self, chat_id: int, user_id: int) -> bool:
        """Check if user is banned in a group."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM groupbans WHERE chat_id = ? AND user_id = ?",
            (chat_id, user_id)
        ).fetchone()
        return row is not None
    
    # Stats
    async def get_stats(self) -> dict:
        """Get bot statistics."""
        conn = self._get_conn()
        
        total_groups = conn.execute("SELECT COUNT(*) FROM groups").fetchone()[0]
        active_groups = conn.execute("SELECT COUNT(*) FROM groups WHERE is_active = 1").fetchone()[0]
        sudo_count = conn.execute("SELECT COUNT(*) FROM sudousers").fetchone()[0]
        gban_count = conn.execute("SELECT COUNT(*) FROM gbanned").fetchone()[0]
        
        return {
            "total_groups": total_groups,
            "active_groups": active_groups,
            "sudo_users": sudo_count,
            "gbanned_users": gban_count,
        }

    async def get_all_groups(self) -> list:
        """Return all active groups as a list of dicts with an '_id' key."""
        conn = self._get_conn()
        rows = conn.execute("SELECT id FROM groups WHERE is_active = 1").fetchall()
        return [{"_id": row["id"]} for row in rows]



# Global instance
sqlite_db: Optional[SQLiteDatabase] = None


def init_sqlite_db(db_path: str = "./data/bot.db"):
    """Initialize SQLite database."""
    global sqlite_db
    sqlite_db = SQLiteDatabase(db_path)
