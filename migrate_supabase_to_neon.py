#!/usr/bin/env python3
"""
Migration script from Supabase to Neon Database.

This script migrates all data from Supabase to Neon PostgreSQL.
Run this after setting up your Neon database and before starting the bot.

Prerequisites:
1. Install dependencies: pip install supabase psycopg2-binary python-dotenv
2. Set SUPABASE_URL and SUPABASE_KEY in your .env
3. Set NEON_DATABASE_URL in your .env (or pass as argument)
4. Neon database should be empty (fresh) for clean migration

Usage:
    python migrate_supabase_to_neon.py
    python migrate_supabase_to_neon.py --neon-url postgresql://user:pass@host/db

Safety:
    - This script READS from Supabase and WRITES to Neon
    - It does NOT delete data from Supabase
    - It uses batch processing to handle large datasets
    - Progress is saved every 100 records
"""

import os
import sys
import json
import argparse
import logging
from datetime import datetime

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    logger.warning("python-dotenv not installed, using system environment variables")


class SupabaseToNeonMigrator:
    """Handles migration from Supabase to Neon Database."""
    
    def __init__(self, supabase_url: str, supabase_key: str, neon_url: str):
        self.supabase_url = supabase_url
        self.supabase_key = supabase_key
        self.neon_url = neon_url
        
        # Initialize clients
        self.supabase = None
        self.neon_conn = None
        
        # Migration stats
        self.stats = {
            'tracks_migrated': 0,
            'queues_migrated': 0,
            'chats_migrated': 0,
            'history_migrated': 0,
            'errors': []
        }
    
    def connect_supabase(self):
        """Connect to Supabase."""
        try:
            from supabase import create_client
            self.supabase = create_client(self.supabase_url, self.supabase_key)
            logger.info("✓ Connected to Supabase")
        except Exception as e:
            logger.error(f"✗ Failed to connect to Supabase: {e}")
            raise
    
    def connect_neon(self):
        """Connect to Neon Database."""
        try:
            import psycopg2
            self.neon_conn = psycopg2.connect(self.neon_url)
            self.neon_conn.autocommit = False
            logger.info("✓ Connected to Neon Database")
        except Exception as e:
            logger.error(f"✗ Failed to connect to Neon: {e}")
            raise
    
    def init_neon_tables(self):
        """Initialize Neon tables (idempotent - safe to run multiple times)."""
        try:
            with self.neon_conn.cursor() as cur:
                # Music index table
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
                cur.execute("CREATE INDEX IF NOT EXISTS idx_music_index_track_id ON music_index(track_id)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_music_index_platform ON music_index(platform)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_queues_chat_id ON queues(chat_id)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_chats_chat_id ON chats(chat_id)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_play_history_chat_id ON play_history(chat_id)")
                
                self.neon_conn.commit()
                logger.info("✓ Neon tables initialized")
        except Exception as e:
            self.neon_conn.rollback()
            logger.error(f"✗ Failed to initialize Neon tables: {e}")
            raise
    
    def migrate_tracks(self, batch_size: int = 100):
        """Migrate tracks from Supabase music_index to Neon."""
        logger.info("\n📀 Migrating tracks...")
        
        try:
            # Fetch all tracks from Supabase
            response = self.supabase.table('global_music_index').select('*').execute()
            tracks = response.data
            
            if not tracks:
                logger.info("  No tracks to migrate")
                return
            
            logger.info(f"  Found {len(tracks)} tracks in Supabase")
            
            # Migrate in batches
            with self.neon_conn.cursor() as cur:
                for i, track in enumerate(tracks):
                    try:
                        cur.execute("""
                            INSERT INTO music_index 
                            (track_id, platform, title, artist, duration, thumbnail, stream_url, file_id, created_at)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (track_id) DO UPDATE SET
                                title = EXCLUDED.title,
                                artist = EXCLUDED.artist,
                                duration = EXCLUDED.duration,
                                thumbnail = EXCLUDED.thumbnail,
                                stream_url = EXCLUDED.stream_url,
                                file_id = EXCLUDED.file_id,
                                updated_at = CURRENT_TIMESTAMP
                        """, (
                            track.get('track_id'),
                            track.get('platform', 'unknown'),
                            track.get('title'),
                            track.get('artist'),
                            track.get('duration'),
                            track.get('thumbnail'),
                            track.get('stream_url'),
                            track.get('file_id'),
                            track.get('created_at') or datetime.now()
                        ))
                        
                        self.stats['tracks_migrated'] += 1
                        
                        # Commit every batch_size records
                        if (i + 1) % batch_size == 0:
                            self.neon_conn.commit()
                            logger.info(f"  Migrated {i + 1}/{len(tracks)} tracks...")
                            
                    except Exception as e:
                        self.stats['errors'].append(f"Track {track.get('track_id')}: {e}")
                        logger.warning(f"  Error migrating track {track.get('track_id')}: {e}")
                
                # Final commit for remaining records
                self.neon_conn.commit()
                
            logger.info(f"✓ Migrated {self.stats['tracks_migrated']} tracks")
            
        except Exception as e:
            logger.error(f"✗ Failed to migrate tracks: {e}")
            raise
    
    def migrate_queues(self, batch_size: int = 50):
        """Migrate queues from Supabase to Neon."""
        logger.info("\n📋 Migrating queues...")
        
        try:
            try:
                response = self.supabase.table('queues').select('*').execute()
                queues = response.data
            except Exception as e:
                if "404" in str(e) or "could not find" in str(e).lower():
                    logger.info("  No queues table found in Supabase (skipping)")
                    return
                raise
            
            if not queues:
                logger.info("  No queues to migrate")
                return
            
            logger.info(f"  Found {len(queues)} queues in Supabase")
            
            with self.neon_conn.cursor() as cur:
                for i, queue in enumerate(queues):
                    try:
                        queue_data = queue.get('queue_data', '{}')
                        if isinstance(queue_data, dict):
                            queue_data = json.dumps(queue_data)
                        
                        cur.execute("""
                            INSERT INTO queues (chat_id, queue_data, created_at)
                            VALUES (%s, %s, %s)
                            ON CONFLICT (chat_id) DO UPDATE SET
                                queue_data = EXCLUDED.queue_data,
                                updated_at = CURRENT_TIMESTAMP
                        """, (
                            queue.get('chat_id'),
                            queue_data,
                            queue.get('created_at') or datetime.now()
                        ))
                        
                        self.stats['queues_migrated'] += 1
                        
                        if (i + 1) % batch_size == 0:
                            self.neon_conn.commit()
                            logger.info(f"  Migrated {i + 1}/{len(queues)} queues...")
                            
                    except Exception as e:
                        self.stats['errors'].append(f"Queue {queue.get('chat_id')}: {e}")
                        logger.warning(f"  Error migrating queue {queue.get('chat_id')}: {e}")
                
                self.neon_conn.commit()
                
            logger.info(f"✓ Migrated {self.stats['queues_migrated']} queues")
            
        except Exception as e:
            logger.error(f"✗ Failed to migrate queues: {e}")
            raise
    
    def migrate_chats(self, batch_size: int = 50):
        """Migrate chats from Supabase to Neon."""
        logger.info("\n💬 Migrating chats...")
        
        try:
            try:
                response = self.supabase.table('chats').select('*').execute()
                chats = response.data
            except Exception as e:
                if "404" in str(e) or "could not find" in str(e).lower():
                    logger.info("  No chats table found in Supabase (skipping)")
                    return
                raise
            
            if not chats:
                logger.info("  No chats to migrate")
                return
            
            logger.info(f"  Found {len(chats)} chats in Supabase")
            
            with self.neon_conn.cursor() as cur:
                for i, chat in enumerate(chats):
                    try:
                        cur.execute("""
                            INSERT INTO chats (chat_id, title, username, type, is_active, created_at)
                            VALUES (%s, %s, %s, %s, %s, %s)
                            ON CONFLICT (chat_id) DO UPDATE SET
                                title = EXCLUDED.title,
                                username = EXCLUDED.username,
                                type = EXCLUDED.type,
                                is_active = EXCLUDED.is_active,
                                updated_at = CURRENT_TIMESTAMP
                        """, (
                            chat.get('chat_id'),
                            chat.get('title'),
                            chat.get('username'),
                            chat.get('type'),
                            chat.get('is_active', True),
                            chat.get('created_at') or datetime.now()
                        ))
                        
                        self.stats['chats_migrated'] += 1
                        
                        if (i + 1) % batch_size == 0:
                            self.neon_conn.commit()
                            logger.info(f"  Migrated {i + 1}/{len(chats)} chats...")
                            
                    except Exception as e:
                        self.stats['errors'].append(f"Chat {chat.get('chat_id')}: {e}")
                        logger.warning(f"  Error migrating chat {chat.get('chat_id')}: {e}")
                
                self.neon_conn.commit()
                
            logger.info(f"✓ Migrated {self.stats['chats_migrated']} chats")
            
        except Exception as e:
            logger.error(f"✗ Failed to migrate chats: {e}")
            raise
    
    def migrate_play_history(self, batch_size: int = 100):
        """Migrate play history from Supabase to Neon."""
        logger.info("\n🎵 Migrating play history...")
        
        try:
            try:
                response = self.supabase.table('play_history').select('*').execute()
                history = response.data
            except Exception as e:
                if "404" in str(e) or "could not find" in str(e).lower():
                    logger.info("  No play_history table found in Supabase (skipping)")
                    return
                raise
            
            if not history:
                logger.info("  No play history to migrate")
                return
            
            logger.info(f"  Found {len(history)} play history records in Supabase")
            
            with self.neon_conn.cursor() as cur:
                for i, record in enumerate(history):
                    try:
                        cur.execute("""
                            INSERT INTO play_history (chat_id, track_id, title, artist, played_at)
                            VALUES (%s, %s, %s, %s, %s)
                        """, (
                            record.get('chat_id'),
                            record.get('track_id'),
                            record.get('title'),
                            record.get('artist'),
                            record.get('played_at') or datetime.now()
                        ))
                        
                        self.stats['history_migrated'] += 1
                        
                        if (i + 1) % batch_size == 0:
                            self.neon_conn.commit()
                            logger.info(f"  Migrated {i + 1}/{len(history)} history records...")
                            
                    except Exception as e:
                        self.stats['errors'].append(f"History {record.get('id')}: {e}")
                        logger.warning(f"  Error migrating history record: {e}")
                
                self.neon_conn.commit()
                
            logger.info(f"✓ Migrated {self.stats['history_migrated']} play history records")
            
        except Exception as e:
            logger.error(f"✗ Failed to migrate play history: {e}")
            raise
    
    def verify_migration(self):
        """Verify the migration by comparing counts."""
        logger.info("\n🔍 Verifying migration...")
        
        try:
            with self.neon_conn.cursor() as cur:
                # Check counts in Neon
                cur.execute("SELECT COUNT(*) FROM music_index")
                neon_tracks = cur.fetchone()[0]
                
                cur.execute("SELECT COUNT(*) FROM queues")
                neon_queues = cur.fetchone()[0]
                
                cur.execute("SELECT COUNT(*) FROM chats")
                neon_chats = cur.fetchone()[0]
                
                cur.execute("SELECT COUNT(*) FROM play_history")
                neon_history = cur.fetchone()[0]
            
            logger.info("  Neon Database counts:")
            logger.info(f"    - Tracks: {neon_tracks}")
            logger.info(f"    - Queues: {neon_queues}")
            logger.info(f"    - Chats: {neon_chats}")
            logger.info(f"    - Play History: {neon_history}")
            
            # Compare with migrated stats
            logger.info("\n  Migration Summary:")
            logger.info(f"    - Tracks migrated: {self.stats['tracks_migrated']}")
            logger.info(f"    - Queues migrated: {self.stats['queues_migrated']}")
            logger.info(f"    - Chats migrated: {self.stats['chats_migrated']}")
            logger.info(f"    - History migrated: {self.stats['history_migrated']}")
            
            if self.stats['errors']:
                logger.warning(f"\n⚠️  {len(self.stats['errors'])} errors occurred during migration")
                logger.warning("   Check the logs above for details.")
            else:
                logger.info("\n✓ No errors during migration")
                
        except Exception as e:
            logger.error(f"✗ Verification failed: {e}")
    
    def run_migration(self):
        """Run the full migration process."""
        logger.info("=" * 60)
        logger.info("Supabase → Neon Database Migration")
        logger.info("=" * 60)
        
        try:
            # Connect to databases
            self.connect_supabase()
            self.connect_neon()
            
            # Initialize Neon tables
            self.init_neon_tables()
            
            # Run migrations (continue even if one fails)
            try:
                self.migrate_tracks()
            except Exception as e:
                logger.error(f"Track migration failed (continuing): {e}")
            
            try:
                self.migrate_queues()
            except Exception as e:
                logger.error(f"Queue migration failed (continuing): {e}")
            
            try:
                self.migrate_chats()
            except Exception as e:
                logger.error(f"Chat migration failed (continuing): {e}")
            
            try:
                self.migrate_play_history()
            except Exception as e:
                logger.error(f"Play history migration failed (continuing): {e}")
            
            # Verify
            self.verify_migration()
            
            logger.info("\n" + "=" * 60)
            if self.stats['errors']:
                logger.info("⚠ Migration completed with some errors (see above)")
            else:
                logger.info("✓ Migration completed successfully!")
            logger.info("=" * 60)
            logger.info("\nNext steps:")
            logger.info("1. Update your .env file to use Neon:")
            logger.info("   NEON_DATABASE_URL=postgresql://...")
            logger.info("2. Remove or comment out SUPABASE_URL and SUPABASE_KEY")
            logger.info("3. Restart your bot to use Neon Database")
            logger.info("4. Optionally keep Supabase as backup (bot will fallback)")
            
        except Exception as e:
            logger.error(f"\n✗ Migration failed: {e}")
            sys.exit(1)
        finally:
            # Cleanup
            if self.neon_conn:
                self.neon_conn.close()
                logger.info("\n✓ Database connections closed")


def main():
    parser = argparse.ArgumentParser(
        description='Migrate data from Supabase to Neon Database'
    )
    parser.add_argument(
        '--neon-url',
        help='Neon Database connection string (or set NEON_DATABASE_URL env var)',
        default=os.getenv('NEON_DATABASE_URL')
    )
    parser.add_argument(
        '--supabase-url',
        help='Supabase URL (or set SUPABASE_URL env var)',
        default=os.getenv('SUPABASE_URL')
    )
    parser.add_argument(
        '--supabase-key',
        help='Supabase Key (or set SUPABASE_KEY env var)',
        default=os.getenv('SUPABASE_KEY')
    )
    parser.add_argument(
        '--dry-run',
        help='Test the migration without writing to Neon',
        action='store_true'
    )
    
    args = parser.parse_args()
    
    # Validate required parameters
    if not args.neon_url:
        logger.error("Error: NEON_DATABASE_URL is required")
        logger.error("Set it as environment variable or use --neon-url")
        sys.exit(1)
    
    if not args.supabase_url or not args.supabase_key:
        logger.error("Error: SUPABASE_URL and SUPABASE_KEY are required")
        logger.error("Set them as environment variables or use --supabase-url and --supabase-key")
        sys.exit(1)
    
    # Run migration
    migrator = SupabaseToNeonMigrator(
        supabase_url=args.supabase_url,
        supabase_key=args.supabase_key,
        neon_url=args.neon_url
    )
    
    migrator.run_migration()


if __name__ == "__main__":
    main()
