"""Supabase PostgreSQL database support for migration from MongoDB."""

import os
import json
import logging
import urllib.request
from typing import Optional, Dict, Any, List
from datetime import datetime

logger = logging.getLogger(__name__)

# Try to import supabase
try:
    from supabase import create_client, Client
    HAS_SUPABASE = True
except ImportError:
    HAS_SUPABASE = False
    logger.warning("supabase package not installed. Run: pip install supabase")


class SupabaseDatabase:
    """Supabase PostgreSQL database wrapper for bot data."""
    
    def __init__(self, url: str, key: str):
        if not HAS_SUPABASE:
            raise ImportError("supabase package required. Install with: pip install supabase")
        
        self.url = url
        self.key = key
        self.client: Client = create_client(url, key)
        self._init_tables()
        self._init_storage()
    
    def _init_storage(self):
        """Initialize bot-assets bucket and ensure startup assets exist."""
        try:
            # Check if bucket exists
            buckets = self.client.storage.list_buckets()
            bucket_exists = any(b.name == "bot-assets" for b in buckets)
            
            if not bucket_exists:
                # Create a public bucket using the service role key
                self.client.storage.create_bucket("bot-assets", {"public": True})
                logger.info("Created Supabase storage bucket 'bot-assets'")
                
            # Pre-upload Brook welcome image if missing
            files = self.client.storage.from_("bot-assets").list()
            brook_exists = any(f.get("name") == "brook_start.png" for f in files)
            
            if not brook_exists:
                local_path = "assets/brook_start.png"
                if os.path.exists(local_path):
                    try:
                        with open(local_path, "rb") as f:
                            img_data = f.read()
                            
                        self.client.storage.from_("bot-assets").upload("brook_start.png", img_data, {"content-type": "image/png"})
                        logger.info("Successfully uploaded Brook start image to Supabase storage")
                    except Exception as e:
                        logger.warning(f"Failed to upload local Brook image to Supabase: {e}")
                else:
                    logger.warning(f"Local asset {local_path} not found to upload.")
                    
        except Exception as e:
            logger.error(f"Error initializing Supabase storage: {e}")

    def get_start_image(self) -> str:
        """Get the public URL for the Brook start image from Supabase."""
        try:
            url = self.client.storage.from_("bot-assets").get_public_url("brook_start.png")
            return url
        except Exception:
            return "https://github.com/edent/SuperTinyIcons/raw/master/images/svg/telegram.svg" # A tiny fallback

            
    def _init_tables(self):
        """Initialize database tables if they don't exist."""
        # Note: Tables should be created via Supabase dashboard or migrations
        # This is just for reference of the schema
        schema = """
        -- groups table
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
            }'
        );

        -- sudo_users table
        CREATE TABLE IF NOT EXISTS sudo_users (
            id BIGINT PRIMARY KEY,
            name TEXT,
            added_by BIGINT,
            added_at TIMESTAMP DEFAULT NOW()
        );

        -- gbanned table
        CREATE TABLE IF NOT EXISTS gbanned (
            id BIGINT PRIMARY KEY,
            reason TEXT,
            banned_by BIGINT,
            banned_at TIMESTAMP DEFAULT NOW()
        );

        -- group_bans table
        CREATE TABLE IF NOT EXISTS group_bans (
            chat_id BIGINT,
            user_id BIGINT,
            banned_at TIMESTAMP DEFAULT NOW(),
            PRIMARY KEY (chat_id, user_id)
        );

        -- playlists table (optional)
        CREATE TABLE IF NOT EXISTS playlists (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            name TEXT,
            tracks JSONB DEFAULT '[]',
            created_at TIMESTAMP DEFAULT NOW()
        );

        -- Create indexes
        CREATE INDEX IF NOT EXISTS idx_groups_active ON groups(is_active);
        CREATE INDEX IF NOT EXISTS idx_gbanned_id ON gbanned(id);
        CREATE INDEX IF NOT EXISTS idx_group_bans_chat ON group_bans(chat_id);
        CREATE INDEX IF NOT EXISTS idx_group_bans_user ON group_bans(user_id);
        """
        logger.info("Supabase tables initialized (create tables via Supabase dashboard)")
    
    # Group management
    async def get_group(self, chat_id: int) -> dict:
        """Get group settings or create default."""
        try:
            result = self.client.table("groups").select("*").eq("id", chat_id).execute()
            
            if result.data and len(result.data) > 0:
                row = result.data[0]
                return {
                    "_id": row["id"],
                    "title": row.get("title", ""),
                    "lang": row.get("lang", "en"),
                    "is_active": row.get("is_active", True),
                    "settings": row.get("settings", {}),
                    "joined_at": row.get("joined_at", datetime.utcnow())
                }
            
            # Create default group
            default_settings = {
                "play_on_join": True,
                "max_queue": 100,
                "vol_default": 100,
                "loop_mode": "none",
                "quality": "high",
                "thumb_mode": True,
            }
            
            new_group = {
                "id": chat_id,
                "title": "",
                "lang": "en",
                "is_active": True,
                "settings": default_settings,
                "joined_at": datetime.utcnow().isoformat()
            }
            
            self.client.table("groups").insert(new_group).execute()
            
            return {
                "_id": chat_id,
                "title": "",
                "lang": "en",
                "is_active": True,
                "settings": default_settings
            }
            
        except Exception as e:
            logger.error(f"Error getting group from Supabase: {e}")
            # Return default on error
            return {
                "_id": chat_id,
                "title": "",
                "lang": "en",
                "is_active": True,
                "settings": {
                    "play_on_join": True,
                    "max_queue": 100,
                    "vol_default": 100,
                    "loop_mode": "none",
                    "quality": "high",
                    "thumb_mode": True,
                }
            }
    
    async def update_group(self, chat_id: int, updates: dict):
        """Update group settings."""
        try:
            # Get current data first
            result = self.client.table("groups").select("*").eq("id", chat_id).execute()
            
            if not result.data:
                # Create if doesn't exist
                await self.get_group(chat_id)
                result = self.client.table("groups").select("*").eq("id", chat_id).execute()
            
            current = result.data[0]
            
            # Build update data
            update_data = {}
            
            if "settings" in updates:
                # Merge settings
                current_settings = current.get("settings", {})
                current_settings.update(updates["settings"])
                update_data["settings"] = current_settings
            
            if "title" in updates:
                update_data["title"] = updates["title"]
            
            if "is_active" in updates:
                update_data["is_active"] = updates["is_active"]
            
            if "lang" in updates:
                update_data["lang"] = updates["lang"]
            
            if update_data:
                self.client.table("groups").update(update_data).eq("id", chat_id).execute()
                
        except Exception as e:
            logger.error(f"Error updating group in Supabase: {e}")
    
    async def set_group_active(self, chat_id: int, active: bool):
        """Set group active status."""
        try:
            self.client.table("groups").update({"is_active": active}).eq("id", chat_id).execute()
        except Exception as e:
            logger.error(f"Error setting group active: {e}")
    
    # Sudo users
    async def add_sudo(self, user_id: int, name: str, added_by: int):
        """Add a sudo user."""
        try:
            data = {
                "id": user_id,
                "name": name,
                "added_by": added_by,
                "added_at": datetime.utcnow().isoformat()
            }
            self.client.table("sudo_users").upsert(data).execute()
        except Exception as e:
            logger.error(f"Error adding sudo: {e}")
    
    async def remove_sudo(self, user_id: int):
        """Remove a sudo user."""
        try:
            self.client.table("sudo_users").delete().eq("id", user_id).execute()
        except Exception as e:
            logger.error(f"Error removing sudo: {e}")
    
    async def get_sudo_users(self) -> list:
        """Get all sudo users."""
        try:
            result = self.client.table("sudo_users").select("*").execute()
            if result.data:
                return [{"_id": r["id"], "name": r.get("name"), "added_by": r.get("added_by")} for r in result.data]
            return []
        except Exception as e:
            logger.error(f"Error getting sudo users: {e}")
            return []
    
    async def is_sudo(self, user_id: int) -> bool:
        """Check if user is sudo."""
        try:
            result = self.client.table("sudo_users").select("*").eq("id", user_id).execute()
            return len(result.data) > 0
        except Exception as e:
            err = str(e)
            if "PGRST205" in err or "lookup_failed" in err.lower():
                # Table missing - only log once or keep it concise
                logger.warning("Supabase table 'sudo_users' missing. Create it via SQL: CREATE TABLE sudo_users (id BIGINT PRIMARY KEY, name TEXT);")
            else:
                logger.debug(f"Sudo check error: {e}")
            return False
    
    # Global bans
    async def gban_user(self, user_id: int, reason: str, banned_by: int):
        """Globally ban a user."""
        try:
            data = {
                "id": user_id,
                "reason": reason,
                "banned_by": banned_by,
                "banned_at": datetime.utcnow().isoformat()
            }
            self.client.table("gbanned").upsert(data).execute()
        except Exception as e:
            logger.error(f"Error gbanning user: {e}")
    
    async def ungban_user(self, user_id: int):
        """Remove global ban."""
        try:
            self.client.table("gbanned").delete().eq("id", user_id).execute()
        except Exception as e:
            logger.error(f"Error ungbanning: {e}")
    
    async def is_gbanned(self, user_id: int) -> bool:
        """Check if user is globally banned."""
        try:
            result = self.client.table("gbanned").select("*").eq("id", user_id).execute()
            return len(result.data) > 0
        except Exception as e:
            err = str(e)
            if "PGRST205" in err or "lookup_failed" in err.lower():
                logger.warning("Supabase table 'gbanned' missing. Create it via SQL: CREATE TABLE gbanned (id BIGINT PRIMARY KEY, reason TEXT);")
            else:
                logger.debug(f"Gban check error: {e}")
            return False
    
    # Group bans
    async def ban_user(self, chat_id: int, user_id: int):
        """Ban user in a specific group."""
        try:
            data = {
                "chat_id": chat_id,
                "user_id": user_id,
                "banned_at": datetime.utcnow().isoformat()
            }
            self.client.table("group_bans").upsert(data).execute()
        except Exception as e:
            logger.error(f"Error banning user: {e}")
    
    async def unban_user(self, chat_id: int, user_id: int):
        """Unban user in a specific group."""
        try:
            self.client.table("group_bans").delete().eq("chat_id", chat_id).eq("user_id", user_id).execute()
        except Exception as e:
            logger.error(f"Error unbanning: {e}")
    
    async def is_banned(self, chat_id: int, user_id: int) -> bool:
        """Check if user is banned in a group."""
        try:
            result = self.client.table("group_bans").select("*").eq("chat_id", chat_id).eq("user_id", user_id).execute()
            return len(result.data) > 0
        except Exception as e:
            logger.error(f"Error checking ban: {e}")
            return False
    
    # Stats
    async def get_stats(self) -> dict:
        """Get bot statistics."""
        try:
            groups_result = self.client.table("groups").select("*").execute()
            active_result = self.client.table("groups").select("*").eq("is_active", True).execute()
            sudo_result = self.client.table("sudo_users").select("*").execute()
            gban_result = self.client.table("gbanned").select("*").execute()
            
            return {
                "total_groups": len(groups_result.data) if groups_result.data else 0,
                "active_groups": len(active_result.data) if active_result.data else 0,
                "sudo_users": len(sudo_result.data) if sudo_result.data else 0,
                "gbanned_users": len(gban_result.data) if gban_result.data else 0,
            }
        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            return {
                "total_groups": 0,
                "active_groups": 0,
                "sudo_users": 0,
                "gbanned_users": 0,
            }

    async def get_all_groups(self) -> list:
        """Return all active groups as list of dicts with '_id' key."""
        try:
            result = self.client.table("groups").select("id").eq("is_active", True).execute()
            return [{"_id": row["id"]} for row in (result.data or [])]
        except Exception as e:
            logger.error(f"Error getting all groups: {e}")
            return []

    # Migration helper
    async def migrate_from_mongodb(self, mongo_db):
        """Migrate data from MongoDB to Supabase."""
        logger.info("Starting migration from MongoDB to Supabase...")
        
        try:
            # Migrate groups
            groups = await mongo_db.db.groups.find().to_list(length=None)
            if groups:
                supabase_groups = []
                for g in groups:
                    supabase_groups.append({
                        "id": g["_id"],
                        "title": g.get("title", ""),
                        "lang": g.get("lang", "en"),
                        "is_active": g.get("is_active", True),
                        "settings": g.get("settings", {}),
                        "joined_at": g.get("joined_at", datetime.utcnow()).isoformat() if isinstance(g.get("joined_at"), datetime) else datetime.utcnow().isoformat()
                    })
                
                # Insert in batches
                for i in range(0, len(supabase_groups), 100):
                    batch = supabase_groups[i:i+100]
                    self.client.table("groups").upsert(batch).execute()
                
                logger.info(f"Migrated {len(groups)} groups")
            
            # Migrate sudo users
            sudos = await mongo_db.db.sudousers.find().to_list(length=None)
            if sudos:
                supabase_sudos = []
                for s in sudos:
                    supabase_sudos.append({
                        "id": s["_id"],
                        "name": s.get("name", ""),
                        "added_by": s.get("added_by"),
                        "added_at": s.get("added_at", datetime.utcnow()).isoformat() if isinstance(s.get("added_at"), datetime) else datetime.utcnow().isoformat()
                    })
                
                for i in range(0, len(supabase_sudos), 100):
                    batch = supabase_sudos[i:i+100]
                    self.client.table("sudo_users").upsert(batch).execute()
                
                logger.info(f"Migrated {len(sudos)} sudo users")
            
            # Migrate gbanned
            gbanned = await mongo_db.db.gbanned.find().to_list(length=None)
            if gbanned:
                supabase_gbanned = []
                for g in gbanned:
                    supabase_gbanned.append({
                        "id": g["_id"],
                        "reason": g.get("reason", ""),
                        "banned_by": g.get("banned_by"),
                        "banned_at": g.get("banned_at", datetime.utcnow()).isoformat() if isinstance(g.get("banned_at"), datetime) else datetime.utcnow().isoformat()
                    })
                
                for i in range(0, len(supabase_gbanned), 100):
                    batch = supabase_gbanned[i:i+100]
                    self.client.table("gbanned").upsert(batch).execute()
                
                logger.info(f"Migrated {len(gbanned)} gbanned users")
            
            # Migrate group bans
            bans = await mongo_db.db.groupbans.find().to_list(length=None)
            if bans:
                supabase_bans = []
                for b in bans:
                    supabase_bans.append({
                        "chat_id": b.get("chat_id"),
                        "user_id": b.get("user_id"),
                        "banned_at": b.get("banned_at", datetime.utcnow()).isoformat() if isinstance(b.get("banned_at"), datetime) else datetime.utcnow().isoformat()
                    })
                
                for i in range(0, len(supabase_bans), 100):
                    batch = supabase_bans[i:i+100]
                    self.client.table("group_bans").upsert(batch).execute()
                
                logger.info(f"Migrated {len(bans)} group bans")
            
            logger.info("Migration completed successfully!")
            return True
            
        except Exception as e:
            logger.error(f"Migration failed: {e}")
            return False


# Global instance
supabase_db: Optional[SupabaseDatabase] = None


def init_supabase(url: str, key: str):
    """Initialize Supabase database."""
    global supabase_db
    supabase_db = SupabaseDatabase(url, key)
    logger.info("Supabase database initialized")
