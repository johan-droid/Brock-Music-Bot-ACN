"""Migration script: MongoDB Atlas → Supabase PostgreSQL

Usage:
    1. Set environment variables:
       - MONGO_URI: Your MongoDB Atlas connection string
       - SUPABASE_URL: Your Supabase project URL
       - SUPABASE_KEY: Your Supabase service role key
    
    2. Run: python3 migrate_to_supabase.py
    
    3. After migration, update your bot .env:
       - Comment out MONGO_URI
       - Add SUPABASE_URL and SUPABASE_KEY

Requirements:
    pip install motor supabase python-dotenv
"""

import asyncio
import os
import logging
from typing import Any, cast
from datetime import datetime

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables
from dotenv import load_dotenv
load_dotenv()


async def migrate():
    """Run the migration from MongoDB to Supabase."""
    
    # Check required env vars
    mongo_uri = os.getenv("MONGO_URI")
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_KEY")
    
    if not mongo_uri:
        logger.error("MONGO_URI environment variable not set!")
        return False
    
    if not supabase_url or not supabase_key:
        logger.error("SUPABASE_URL and SUPABASE_KEY environment variables required!")
        logger.info("Get these from your Supabase project Settings > API")
        return False
    
    logger.info("=" * 60)
    logger.info("MongoDB Atlas → Supabase Migration Tool")
    logger.info("=" * 60)
    
    # Connect to MongoDB
    logger.info("\n1. Connecting to MongoDB Atlas...")
    try:
        from motor.motor_asyncio import AsyncIOMotorClient
        mongo_client = AsyncIOMotorClient(mongo_uri, serverSelectionTimeoutMS=10000)
        await mongo_client.admin.command('ping')
        mongo_db = mongo_client.get_default_database()
        logger.info("✓ MongoDB connected")
    except Exception as e:
        logger.error(f"✗ Failed to connect to MongoDB: {e}")
        return False
    
    # Connect to Supabase
    logger.info("\n2. Connecting to Supabase...")
    try:
        from supabase import create_client
        supabase_client = create_client(supabase_url, supabase_key)
        
        # Test connection
        result = supabase_client.table("groups").select("count", count=cast(Any, "exact")).limit(1).execute()
        logger.info("✓ Supabase connected")
    except Exception as e:
        logger.error(f"✗ Failed to connect to Supabase: {e}")
        logger.error("Make sure you've created the tables in Supabase SQL Editor!")
        logger.info("\nRequired SQL schema:\n")
        print(SUPABASE_SCHEMA)
        return False
    
    # Migration stats
    stats = {
        "groups": 0,
        "sudo_users": 0,
        "gbanned": 0,
        "group_bans": 0
    }
    
    # Migrate groups
    logger.info("\n3. Migrating groups...")
    try:
        groups = await mongo_db.groups.find().to_list(length=None)
        if groups:
            supabase_groups = []
            for g in groups:
                joined_at = g.get("joined_at", datetime.utcnow())
                if isinstance(joined_at, datetime):
                    joined_at = joined_at.isoformat()
                else:
                    joined_at = datetime.utcnow().isoformat()
                
                supabase_groups.append({
                    "id": g["_id"],
                    "title": g.get("title", "")[:200],  # Limit length
                    "lang": g.get("lang", "en")[:10],
                    "is_active": g.get("is_active", True),
                    "settings": g.get("settings", {
                        "play_on_join": True,
                        "max_queue": 100,
                        "vol_default": 100,
                        "loop_mode": "none",
                        "quality": "high",
                        "thumb_mode": True
                    }),
                    "joined_at": joined_at
                })
            
            # Insert in batches of 100
            for i in range(0, len(supabase_groups), 100):
                batch = supabase_groups[i:i+100]
                supabase_client.table("groups").upsert(batch).execute()
            
            stats["groups"] = len(groups)
            logger.info(f"✓ Migrated {len(groups)} groups")
        else:
            logger.info("  No groups to migrate")
    except Exception as e:
        logger.error(f"✗ Error migrating groups: {e}")
    
    # Migrate sudo users
    logger.info("\n4. Migrating sudo users...")
    try:
        sudos = await mongo_db.sudousers.find().to_list(length=None)
        if sudos:
            supabase_sudos = []
            for s in sudos:
                added_at = s.get("added_at", datetime.utcnow())
                if isinstance(added_at, datetime):
                    added_at = added_at.isoformat()
                else:
                    added_at = datetime.utcnow().isoformat()
                
                supabase_sudos.append({
                    "id": s["_id"],
                    "name": s.get("name", "")[:100],
                    "added_by": s.get("added_by"),
                    "added_at": added_at
                })
            
            for i in range(0, len(supabase_sudos), 100):
                batch = supabase_sudos[i:i+100]
                supabase_client.table("sudo_users").upsert(batch).execute()
            
            stats["sudo_users"] = len(sudos)
            logger.info(f"✓ Migrated {len(sudos)} sudo users")
        else:
            logger.info("  No sudo users to migrate")
    except Exception as e:
        logger.error(f"✗ Error migrating sudo users: {e}")
    
    # Migrate gbanned
    logger.info("\n5. Migrating globally banned users...")
    try:
        gbanned = await mongo_db.gbanned.find().to_list(length=None)
        if gbanned:
            supabase_gbanned = []
            for g in gbanned:
                banned_at = g.get("banned_at", datetime.utcnow())
                if isinstance(banned_at, datetime):
                    banned_at = banned_at.isoformat()
                else:
                    banned_at = datetime.utcnow().isoformat()
                
                supabase_gbanned.append({
                    "id": g["_id"],
                    "reason": g.get("reason", "")[:500],
                    "banned_by": g.get("banned_by"),
                    "banned_at": banned_at
                })
            
            for i in range(0, len(supabase_gbanned), 100):
                batch = supabase_gbanned[i:i+100]
                supabase_client.table("gbanned").upsert(batch).execute()
            
            stats["gbanned"] = len(gbanned)
            logger.info(f"✓ Migrated {len(gbanned)} gbanned users")
        else:
            logger.info("  No banned users to migrate")
    except Exception as e:
        logger.error(f"✗ Error migrating gbanned: {e}")
    
    # Migrate group bans
    logger.info("\n6. Migrating group bans...")
    try:
        bans = await mongo_db.groupbans.find().to_list(length=None)
        if bans:
            supabase_bans = []
            for b in bans:
                banned_at = b.get("banned_at", datetime.utcnow())
                if isinstance(banned_at, datetime):
                    banned_at = banned_at.isoformat()
                else:
                    banned_at = datetime.utcnow().isoformat()
                
                supabase_bans.append({
                    "chat_id": b.get("chat_id"),
                    "user_id": b.get("user_id"),
                    "banned_at": banned_at
                })
            
            for i in range(0, len(supabase_bans), 100):
                batch = supabase_bans[i:i+100]
                supabase_client.table("group_bans").upsert(batch).execute()
            
            stats["group_bans"] = len(bans)
            logger.info(f"✓ Migrated {len(bans)} group bans")
        else:
            logger.info("  No group bans to migrate")
    except Exception as e:
        logger.error(f"✗ Error migrating group bans: {e}")
    
    # Summary
    logger.info("\n" + "=" * 60)
    logger.info("Migration Summary")
    logger.info("=" * 60)
    logger.info(f"Groups migrated:     {stats['groups']}")
    logger.info(f"Sudo users migrated: {stats['sudo_users']}")
    logger.info(f"GBanned migrated:    {stats['gbanned']}")
    logger.info(f"Group bans migrated: {stats['group_bans']}")
    logger.info("=" * 60)
    logger.info("\n✓ Migration completed!")
    
    # Close connections
    mongo_client.close()
    
    # Update instructions
    logger.info("\n" + "=" * 60)
    logger.info("Next Steps:")
    logger.info("=" * 60)
    logger.info("1. Update your bot's .env file:")
    logger.info("   - Comment out or remove: MONGO_URI")
    logger.info("   - Add: SUPABASE_URL=<your_supabase_url>")
    logger.info("   - Add: SUPABASE_KEY=<your_service_role_key>")
    logger.info("\n2. Install supabase package:")
    logger.info("   pip install supabase")
    logger.info("\n3. Restart your bot")
    logger.info("=" * 60)
    
    return True


# SQL Schema for Supabase
SUPABASE_SCHEMA = """
-- Run this in Supabase SQL Editor before migration

-- Groups table
CREATE TABLE IF NOT EXISTS groups (
    id BIGINT PRIMARY KEY,
    title TEXT,
    lang TEXT DEFAULT 'en',
    is_active BOOLEAN DEFAULT TRUE,
    joined_at TIMESTAMP DEFAULT NOW(),
    settings JSONB DEFAULT '{
        "play_on_join": true,
        "max_queue": 100,
        "vol_default": 100,
        "loop_mode": "none",
        "quality": "high",
        "thumb_mode": true
    }'::jsonb
);

-- Sudo users table
CREATE TABLE IF NOT EXISTS sudo_users (
    id BIGINT PRIMARY KEY,
    name TEXT,
    added_by BIGINT,
    added_at TIMESTAMP DEFAULT NOW()
);

-- Globally banned users
CREATE TABLE IF NOT EXISTS gbanned (
    id BIGINT PRIMARY KEY,
    reason TEXT,
    banned_by BIGINT,
    banned_at TIMESTAMP DEFAULT NOW()
);

-- Group-specific bans
CREATE TABLE IF NOT EXISTS group_bans (
    chat_id BIGINT,
    user_id BIGINT,
    banned_at TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (chat_id, user_id)
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_groups_active ON groups(is_active);
CREATE INDEX IF NOT EXISTS idx_gbanned_id ON gbanned(id);
CREATE INDEX IF NOT EXISTS idx_group_bans_chat ON group_bans(chat_id);
CREATE INDEX IF NOT EXISTS idx_group_bans_user ON group_bans(user_id);

-- Enable RLS (Row Level Security) - optional but recommended
ALTER TABLE groups ENABLE ROW LEVEL SECURITY;
ALTER TABLE sudo_users ENABLE ROW LEVEL SECURITY;
ALTER TABLE gbanned ENABLE ROW LEVEL SECURITY;
ALTER TABLE group_bans ENABLE ROW LEVEL SECURITY;

-- Create policies (allow all for service role)
CREATE POLICY "Allow all" ON groups FOR ALL USING (true);
CREATE POLICY "Allow all" ON sudo_users FOR ALL USING (true);
CREATE POLICY "Allow all" ON gbanned FOR ALL USING (true);
CREATE POLICY "Allow all" ON group_bans FOR ALL USING (true);
"""


if __name__ == "__main__":
    # Print schema first
    print("\n" + "=" * 60)
    print("Supabase SQL Schema (Run this first in Supabase SQL Editor):")
    print("=" * 60)
    print(SUPABASE_SCHEMA)
    print("=" * 60)
    
    # Run migration
    result = asyncio.run(migrate())
    
    if result:
        print("\n✓ Migration script completed successfully!")
    else:
        print("\n✗ Migration failed. Check errors above.")
        exit(1)
