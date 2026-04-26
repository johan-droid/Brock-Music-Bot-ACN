"""Neon Database (PostgreSQL) support for the music bot."""

import os
import json
import logging
import psycopg2
from psycopg2.extras import RealDictCursor
from typing import Optional, Dict, Any, List
from datetime import datetime

logger = logging.getLogger(__name__)

# Global singleton
neon_db: Optional['NeonDatabase'] = None


class NeonDatabase:
    """Neon PostgreSQL database wrapper for bot data."""
    
    def __init__(self, database_url: str):
        self.database_url = database_url
        self.conn = None
        self._connect()
        self._init_tables()
    
    def _connect(self):
        """Establish connection to Neon Database."""
        try:
            self.conn = psycopg2.connect(self.database_url)
            self.conn.autocommit = False
            logger.info("Connected to Neon Database.")
        except Exception as e:
            logger.error(f"Failed to connect to Neon Database: {e}")
            raise
    
    def _init_tables(self):
        """Initialize database tables if they don't exist."""
        try:
            with self.conn.cursor() as cur:
                # Music index table (cached tracks)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS music_index (
                        id SERIAL PRIMARY KEY,
                        track_id VARCHAR(255) UNIQUE NOT NULL,
                        platform VARCHAR(50) NOT NULL,
                        title TEXT NOT NULL,
                        artist TEXT NOT NULL,
                        duration INTEGER,
                        thumbnail TEXT,
                        stream_url TEXT,
                        file_id TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                # Queues table
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS queues (
                        id SERIAL PRIMARY KEY,
                        chat_id BIGINT NOT NULL,
                        queue_data JSONB NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(chat_id)
                    )
                """)
                
                # Chats table
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS chats (
                        id SERIAL PRIMARY KEY,
                        chat_id BIGINT UNIQUE NOT NULL,
                        title TEXT,
                        username TEXT,
                        type VARCHAR(50),
                        is_active BOOLEAN DEFAULT TRUE,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                # Play history table
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS play_history (
                        id SERIAL PRIMARY KEY,
                        chat_id BIGINT NOT NULL,
                        track_id VARCHAR(255) NOT NULL,
                        title TEXT,
                        artist TEXT,
                        played_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                # Create indexes
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_music_index_track_id 
                    ON music_index(track_id)
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_music_index_platform 
                    ON music_index(platform)
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_queues_chat_id 
                    ON queues(chat_id)
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_chats_chat_id 
                    ON chats(chat_id)
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_play_history_chat_id 
                    ON play_history(chat_id)
                """)
                
                self.conn.commit()
                logger.info("Neon Database tables initialized.")
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Error initializing Neon tables: {e}")
            raise
    
    async def get_track(self, track_id: str) -> Optional[Dict[str, Any]]:
        """Get a track by ID from the music index."""
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM music_index WHERE track_id = %s",
                    (track_id,)
                )
                result = cur.fetchone()
                if result:
                    return dict(result)
                return None
        except Exception as e:
            logger.error(f"Error getting track from Neon: {e}")
            return None
    
    async def save_track(self, track_data: Dict[str, Any]) -> bool:
        """Save or update a track in the music index."""
        try:
            with self.conn.cursor() as cur:
                # Check if track exists
                cur.execute(
                    "SELECT id FROM music_index WHERE track_id = %s",
                    (track_data.get('track_id'),)
                )
                existing = cur.fetchone()
                
                if existing:
                    # Update existing
                    cur.execute("""
                        UPDATE music_index 
                        SET title = %s, artist = %s, duration = %s, 
                            thumbnail = %s, stream_url = %s, file_id = %s,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE track_id = %s
                    """, (
                        track_data.get('title'),
                        track_data.get('artist'),
                        track_data.get('duration'),
                        track_data.get('thumbnail'),
                        track_data.get('stream_url'),
                        track_data.get('file_id'),
                        track_data.get('track_id')
                    ))
                else:
                    # Insert new
                    cur.execute("""
                        INSERT INTO music_index 
                        (track_id, platform, title, artist, duration, thumbnail, stream_url, file_id)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        track_data.get('track_id'),
                        track_data.get('platform', 'unknown'),
                        track_data.get('title'),
                        track_data.get('artist'),
                        track_data.get('duration'),
                        track_data.get('thumbnail'),
                        track_data.get('stream_url'),
                        track_data.get('file_id')
                    ))
                
                self.conn.commit()
                return True
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Error saving track to Neon: {e}")
            return False
    
    async def search_tracks(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Search tracks by title or artist."""
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT * FROM music_index 
                    WHERE title ILIKE %s OR artist ILIKE %s
                    ORDER BY created_at DESC
                    LIMIT %s
                """, (f'%{query}%', f'%{query}%', limit))
                results = cur.fetchall()
                return [dict(row) for row in results]
        except Exception as e:
            logger.error(f"Error searching tracks in Neon: {e}")
            return []
    
    async def get_queue(self, chat_id: int) -> Optional[Dict[str, Any]]:
        """Get queue for a chat."""
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM queues WHERE chat_id = %s",
                    (chat_id,)
                )
                result = cur.fetchone()
                if result:
                    return dict(result)
                return None
        except Exception as e:
            logger.error(f"Error getting queue from Neon: {e}")
            return None
    
    async def save_queue(self, chat_id: int, queue_data: Dict[str, Any]) -> bool:
        """Save or update queue for a chat."""
        try:
            with self.conn.cursor() as cur:
                # Convert queue_data to JSON string if it's a dict
                if isinstance(queue_data, dict):
                    queue_data = json.dumps(queue_data)
                
                cur.execute("""
                    INSERT INTO queues (chat_id, queue_data)
                    VALUES (%s, %s)
                    ON CONFLICT (chat_id) 
                    DO UPDATE SET queue_data = EXCLUDED.queue_data, 
                                  updated_at = CURRENT_TIMESTAMP
                """, (chat_id, queue_data))
                
                self.conn.commit()
                return True
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Error saving queue to Neon: {e}")
            return False
    
    async def delete_queue(self, chat_id: int) -> bool:
        """Delete queue for a chat."""
        try:
            with self.conn.cursor() as cur:
                cur.execute("DELETE FROM queues WHERE chat_id = %s", (chat_id,))
                self.conn.commit()
                return True
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Error deleting queue from Neon: {e}")
            return False
    
    async def add_chat(self, chat_id: int, title: str = None, 
                       username: str = None, chat_type: str = None) -> bool:
        """Add or update a chat."""
        try:
            with self.conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO chats (chat_id, title, username, type)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (chat_id) 
                    DO UPDATE SET title = EXCLUDED.title,
                                  username = EXCLUDED.username,
                                  type = EXCLUDED.type,
                                  updated_at = CURRENT_TIMESTAMP
                """, (chat_id, title, username, chat_type))
                
                self.conn.commit()
                return True
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Error adding chat to Neon: {e}")
            return False
    
    async def get_active_chats(self) -> List[Dict[str, Any]]:
        """Get all active chats."""
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM chats WHERE is_active = TRUE")
                results = cur.fetchall()
                return [dict(row) for row in results]
        except Exception as e:
            logger.error(f"Error getting active chats from Neon: {e}")
            return []
    
    async def log_play(self, chat_id: int, track_id: str, 
                       title: str = None, artist: str = None) -> bool:
        """Log a play event."""
        try:
            with self.conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO play_history (chat_id, track_id, title, artist)
                    VALUES (%s, %s, %s, %s)
                """, (chat_id, track_id, title, artist))
                
                self.conn.commit()
                return True
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Error logging play to Neon: {e}")
            return False
    
    def health_check(self) -> bool:
        """Check database connection health."""
        try:
            with self.conn.cursor() as cur:
                cur.execute("SELECT 1")
                return True
        except Exception as e:
            logger.error(f"Neon health check failed: {e}")
            return False


def init_neon(database_url: str):
    """Initialize Neon database singleton."""
    global neon_db
    neon_db = NeonDatabase(database_url)
    logger.info("Neon Database initialized.")
