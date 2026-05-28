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

        # Global Music Index for local caching
        conn.execute("""
            CREATE TABLE IF NOT EXISTS global_music_index (
                query_key TEXT PRIMARY KEY,
                jamendo_track_id INTEGER,
                title TEXT,
                artist TEXT,
                duration INTEGER,
                thumbnail_url TEXT,

                audio_url TEXT,
                metadata TEXT DEFAULT '{}',  -- JSON string
                sources TEXT DEFAULT '[]',    -- JSON string
                last_played TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Indexes for SQLite performance
        conn.execute("CREATE INDEX IF NOT EXISTS idx_music_title ON global_music_index(title)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_music_last_played ON global_music_index(last_played)")

        # Mini app session persistence
        conn.execute("""
            CREATE TABLE IF NOT EXISTS mini_app_sessions (
                user_id INTEGER PRIMARY KEY,
                recent_tracks TEXT DEFAULT '[]',
                preferences TEXT DEFAULT '{}',
                last_chat_id INTEGER,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mini_app_sessions_updated_at ON mini_app_sessions(updated_at)")


        conn.execute("""
            CREATE TABLE IF NOT EXISTS radio_shows (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                host_user_id INTEGER,
                show_name TEXT,
                description TEXT,
                schedule_day_of_week INTEGER,
                schedule_time TEXT,
                genre_tags TEXT,
                duration_minutes INTEGER,
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS show_tracks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                show_id INTEGER,
                jamendo_track_id INTEGER,
                position INTEGER,
                added_by INTEGER,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(show_id) REFERENCES radio_shows(id) ON DELETE CASCADE
            )
        """)
        # Lobby snapshots for cold-start recovery
        conn.execute("""
            CREATE TABLE IF NOT EXISTS lobby_snapshots (
                chat_id INTEGER PRIMARY KEY,
                now_playing TEXT,
                queue TEXT DEFAULT '[]',
                status TEXT DEFAULT 'idle',
                position_seconds INTEGER DEFAULT 0,
                participants TEXT DEFAULT '[]',
                version INTEGER DEFAULT 1,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_lobby_snapshots_updated_at ON lobby_snapshots(updated_at)")

        # Playlists table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS playlists (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                creator_user_id INTEGER NOT NULL,
                jamendo_playlist_id TEXT,
                is_collaborative INTEGER DEFAULT 0,
                is_public INTEGER DEFAULT 0,
                jamendo_token TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Playlist tracks table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS playlist_tracks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                playlist_id INTEGER,
                jamendo_track_id TEXT NOT NULL,
                position INTEGER,
                added_by INTEGER,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(playlist_id) REFERENCES playlists(id) ON DELETE CASCADE
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_playlists_creator ON playlists(creator_user_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_playlist_tracks_playlist ON playlist_tracks(playlist_id)")

        

        conn.execute("CREATE INDEX IF NOT EXISTS idx_radio_shows_chat ON radio_shows(chat_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_radio_shows_time ON radio_shows(schedule_day_of_week, schedule_time)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_show_tracks_show ON show_tracks(show_id)")
        conn.commit()
        logger.info(f"SQLite database initialized at {self.db_path} (with local index support)")
    
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
        
        # Get current values
        current = await self.get_group(chat_id)
        settings = current.get("settings", {}) or {}
        
        def _merge_dotted_settings(settings_dict, dotted_key, value):
            parts = dotted_key.split(".")[1:]
            target = settings_dict
            for part in parts[:-1]:
                if part not in target or not isinstance(target[part], dict):
                    target[part] = {}
                target = target[part]
            target[parts[-1]] = value

        # Apply direct settings merges
        if "settings" in updates and isinstance(updates["settings"], dict):
            settings.update(updates["settings"])

        # Apply dotted path updates like settings.loop_mode or settings.vol_default
        for key, value in updates.items():
            if key.startswith("settings."):
                _merge_dotted_settings(settings, key, value)

        # Only update settings if actual values have changed
        row = conn.execute("SELECT settings FROM groups WHERE id = ?", (chat_id,)).fetchone()
        current_settings = {}
        if row and row["settings"]:
            try:
                current_settings = json.loads(row["settings"])
            except json.JSONDecodeError:
                current_settings = {}

        if settings != current_settings:
            conn.execute(
                "UPDATE groups SET settings = ? WHERE id = ?",
                (json.dumps(settings), chat_id)
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

    async def prune_inactive_data(self) -> int:
        """Delete inactive groups from SQLite and return how many were removed."""
        conn = self._get_conn()
        cursor = conn.execute("DELETE FROM groups WHERE is_active = 0")
        conn.commit()
        deleted_count = cursor.rowcount if cursor is not None else 0
        logger.info(f"🧹 Auto-Prune: Freed space by deleting {deleted_count} inactive groups from SQLite.")
        return deleted_count

    # Music Index Implementation for SQLite
    async def search_global_music_index(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Search local SQLite index and return tracks as dicts."""
        q = (query or "").strip()
        if not q:
            return []
        
        conn = self._get_conn()
        like_query = f"%{q}%"
        
        rows = conn.execute("""
            SELECT * FROM global_music_index 
            WHERE title LIKE ? OR artist LIKE ?
            ORDER BY last_played DESC 
            LIMIT ?
        """, (like_query, like_query, max(1, limit))).fetchall()
        
        tracks = []
        for row in rows:
            try:
                metadata = json.loads(row["metadata"] or "{}")
                sources = json.loads(row["sources"] or "[]")
            except Exception:
                metadata = {}
                sources = []

            tracks.append({
                "title": row["title"],
                "artist": row["artist"],
                "uploader": row["artist"],
                "duration": row["duration"] or 0,
                "url": row["audio_url"] or "",
                "stream_url": row["audio_url"] or "",
                "thumbnail": row["thumbnail_url"],
                "source": "global_index",
                "origin_source": metadata.get("source") or "unknown",
                "id": row["jamendo_track_id"],
                "track_id": row["jamendo_track_id"],
                "metadata": metadata,
                "sources": sources,
                "query_key": row["query_key"],
            })
        
        return tracks

    async def save_track_to_index(self, query: str, track: dict):
        """Save a track to the local SQLite global index."""
        try:
            query_key = query.strip().lower()
            jamendo_track_id = track.get("id") or track.get("jamendo_track_id")
            source_name = track.get("source", "unknown")
            stream_url = track.get("url") or track.get("stream_url") or ""
            saved_at = datetime.utcnow().isoformat()

            metadata = track.get("metadata") or {}
            sources = track.get("sources") or []
            
            # Ensure basic info is in metadata for portability
            metadata.update({
                "title": track.get("title"),
                "artist": track.get("artist"),
                "duration": track.get("duration"),
                "thumbnail": track.get("thumbnail"),
                "source": source_name,
                "stream_url": stream_url
            })

            conn = self._get_conn()
            conn.execute("""
                INSERT OR REPLACE INTO global_music_index 
                (query_key, jamendo_track_id, title, artist, duration, thumbnail_url,  audio_url, metadata, sources, last_played)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                query_key,
                jamendo_track_id,
                track.get("title"),
                track.get("artist") or track.get("uploader"),
                track.get("duration") or 0,
                track.get("thumbnail_url") or track.get("thumbnail"),
                stream_url,
                json.dumps(metadata),
                json.dumps(sources),
                saved_at
            ))
            conn.commit()
        except Exception as e:
            logger.error(f"Failed to save track to SQLite index: {e}")

    # Mini app sessions
    async def get_mini_app_session(self, user_id: int) -> Optional[Dict[str, Any]]:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT user_id,recent_tracks,preferences,last_chat_id,updated_at,created_at FROM mini_app_sessions WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        if not row:
            return None
        try:
            recent_tracks = json.loads(row["recent_tracks"] or "[]")
        except Exception:
            recent_tracks = []
        try:
            preferences = json.loads(row["preferences"] or "{}")
        except Exception:
            preferences = {}
        return {
            "user_id": row["user_id"],
            "recent_tracks": recent_tracks if isinstance(recent_tracks, list) else [],
            "preferences": preferences if isinstance(preferences, dict) else {},
            "last_chat_id": row["last_chat_id"],
            "updated_at": row["updated_at"],
            "created_at": row["created_at"],
        }

    async def upsert_mini_app_session(
        self,
        user_id: int,
        recent_tracks: Optional[List[Dict[str, Any]]] = None,
        preferences: Optional[Dict[str, Any]] = None,
        last_chat_id: Optional[int] = None,
    ) -> None:
        existing = await self.get_mini_app_session(user_id) or {
            "recent_tracks": [],
            "preferences": {},
            "last_chat_id": None,
        }
        merged_tracks = recent_tracks if recent_tracks is not None else existing.get("recent_tracks", [])
        merged_prefs = preferences if preferences is not None else existing.get("preferences", {})
        merged_chat_id = last_chat_id if last_chat_id is not None else existing.get("last_chat_id")

        conn = self._get_conn()
        conn.execute(
            """
            INSERT INTO mini_app_sessions (user_id,recent_tracks,preferences,last_chat_id,updated_at,created_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET
                recent_tracks=excluded.recent_tracks,
                preferences=excluded.preferences,
                last_chat_id=excluded.last_chat_id,
                updated_at=CURRENT_TIMESTAMP
            """,
            (
                user_id,
                json.dumps(merged_tracks or []),
                json.dumps(merged_prefs or {}),
                merged_chat_id,
            ),
        )
        conn.commit()

    # Lobby snapshots
    async def get_lobby_snapshot(self, chat_id: int) -> Optional[Dict[str, Any]]:
        conn = self._get_conn()
        row = conn.execute(
            """
            SELECT chat_id,now_playing,queue,status,position_seconds,participants,version,updated_at,created_at
            FROM lobby_snapshots
            WHERE chat_id = ?
            """,
            (chat_id,),
        ).fetchone()
        if not row:
            return None
        try:
            now_playing = json.loads(row["now_playing"]) if row["now_playing"] else None
        except Exception:
            now_playing = None
        try:
            queue = json.loads(row["queue"] or "[]")
        except Exception:
            queue = []
        try:
            participants = json.loads(row["participants"] or "[]")
        except Exception:
            participants = []
        return {
            "chat_id": row["chat_id"],
            "now_playing": now_playing,
            "queue": queue if isinstance(queue, list) else [],
            "status": row["status"] or "idle",
            "position_seconds": int(row["position_seconds"] or 0),
            "participants": participants if isinstance(participants, list) else [],
            "version": int(row["version"] or 1),
            "updated_at": row["updated_at"],
            "created_at": row["created_at"],
        }

    async def upsert_lobby_snapshot(self, chat_id: int, snapshot: Dict[str, Any]) -> None:
        conn = self._get_conn()
        conn.execute(
            """
            INSERT INTO lobby_snapshots
            (chat_id,now_playing,queue,status,position_seconds,participants,version,updated_at,created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT(chat_id) DO UPDATE SET
                now_playing=excluded.now_playing,
                queue=excluded.queue,
                status=excluded.status,
                position_seconds=excluded.position_seconds,
                participants=excluded.participants,
                version=excluded.version,
                updated_at=CURRENT_TIMESTAMP
            """,
            (
                chat_id,
                json.dumps(snapshot.get("now_playing")) if snapshot.get("now_playing") is not None else None,
                json.dumps(snapshot.get("queue") or []),
                snapshot.get("status") or "idle",
                int(snapshot.get("position_seconds") or 0),
                json.dumps(snapshot.get("participants") or []),
                int(snapshot.get("version") or 1),
            ),
        )
        conn.commit()




# Global instance
sqlite_db: Optional[SQLiteDatabase] = None


def init_sqlite_db(db_path: str = "./data/bot.db"):
    """Initialize SQLite database."""
    global sqlite_db
    sqlite_db = SQLiteDatabase(db_path)

    # Radio Shows Implementation for SQLite
    async def create_radio_show(self, chat_id: int, host_user_id: int, show_name: str, description: str, day: int, time: str, genre: str, duration: int) -> int:
        """Create a new radio show."""
        conn = self._get_conn()
        cursor = conn.execute("""
            INSERT INTO radio_shows (chat_id, host_user_id, show_name, description, schedule_day_of_week, schedule_time, genre_tags, duration_minutes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (chat_id, host_user_id, show_name, description, day, time, genre, duration))
        conn.commit()
        return cursor.lastrowid

    async def add_track_to_show(self, show_id: int, track_id: int, added_by: int) -> bool:
        """Add a track to a radio show."""
        conn = self._get_conn()

        row = conn.execute("SELECT MAX(position) FROM show_tracks WHERE show_id = ?", (show_id,)).fetchone()
        pos = row[0] if row[0] is not None else 0

        conn.execute("""
            INSERT INTO show_tracks (show_id, jamendo_track_id, position, added_by)
            VALUES (?, ?, ?, ?)
        """, (show_id, track_id, pos + 1, added_by))
        conn.commit()
        return True

    async def get_upcoming_shows(self, chat_id: int) -> List[Dict[str, Any]]:
        """Get all upcoming shows for a chat."""
        conn = self._get_conn()
        rows = conn.execute("SELECT * FROM radio_shows WHERE chat_id = ? AND is_active = 1 ORDER BY schedule_day_of_week, schedule_time", (chat_id,)).fetchall()
        return [dict(row) for row in rows]

    async def get_show_tracks(self, show_id: int) -> List[Dict[str, Any]]:
        """Get all tracks for a radio show."""
        conn = self._get_conn()
        rows = conn.execute("SELECT * FROM show_tracks WHERE show_id = ? ORDER BY position", (show_id,)).fetchall()
        return [dict(row) for row in rows]

    async def get_shows_by_time(self, day: int, time: str) -> List[Dict[str, Any]]:
        """Get all shows scheduled for a specific time."""
        conn = self._get_conn()
        rows = conn.execute("SELECT * FROM radio_shows WHERE schedule_day_of_week = ? AND schedule_time = ? AND is_active = 1", (day, time)).fetchall()
        return [dict(row) for row in rows]

    async def delete_show(self, show_id: int) -> bool:
        """Delete a radio show (and its tracks via cascade if supported)."""
        conn = self._get_conn()
        conn.execute("DELETE FROM show_tracks WHERE show_id = ?", (show_id,))
        conn.execute("DELETE FROM radio_shows WHERE id = ?", (show_id,))
        conn.commit()
        return True

    async def get_past_shows(self, chat_id: int) -> List[Dict[str, Any]]:
        """Get past shows for a chat (currently we don't have a specific way to mark past shows other than active/inactive, but keeping for compatibility)."""
        conn = self._get_conn()
        rows = conn.execute("SELECT * FROM radio_shows WHERE chat_id = ? AND is_active = 0 ORDER BY created_at DESC", (chat_id,)).fetchall()
        return [dict(row) for row in rows]

    async def set_show_inactive(self, show_id: int) -> bool:
        """Mark a show as inactive (past)."""
        conn = self._get_conn()
        conn.execute("UPDATE radio_shows SET is_active = 0 WHERE id = ?", (show_id,))
        conn.commit()
        return True

    from types import MethodType
    sqlite_db.create_radio_show = MethodType(create_radio_show, sqlite_db)
    sqlite_db.add_track_to_show = MethodType(add_track_to_show, sqlite_db)
    sqlite_db.get_upcoming_shows = MethodType(get_upcoming_shows, sqlite_db)
    sqlite_db.get_show_tracks = MethodType(get_show_tracks, sqlite_db)
    sqlite_db.get_shows_by_time = MethodType(get_shows_by_time, sqlite_db)
    sqlite_db.delete_show = MethodType(delete_show, sqlite_db)
    sqlite_db.get_past_shows = MethodType(get_past_shows, sqlite_db)
    sqlite_db.set_show_inactive = MethodType(set_show_inactive, sqlite_db)
