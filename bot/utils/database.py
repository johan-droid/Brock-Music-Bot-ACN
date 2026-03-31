"""Database layer with MongoDB primary and SQLite fallback for zero-cost deployment."""

import logging
import os
from config import config

logger = logging.getLogger(__name__)

# Global instances
db = None
mongo_client = None
sqlite_db = None
supabase_db = None

# Database mode: "mongo", "supabase", or "sqlite"
DB_MODE = "sqlite"


class Database:
    """Abstract marker class for supported database backends."""
    pass


class MongoDatabase(Database):
    """MongoDB database wrapper."""
    
    def __init__(self, client):
        self.client = client
        self.db = client.get_default_database()
    
    async def disconnect(self):
        """Disconnect from MongoDB."""
        if self.client:
            self.client.close()
            logger.info("MongoDB disconnected")
    
    async def get_group(self, chat_id: int) -> dict:
        """Get group settings or create default."""
        group = await self.db.groups.find_one({"_id": chat_id})
        if not group:
            group = {
                "_id": chat_id,
                "title": "",
                "lang": "en",
                "is_active": True,
                "settings": {
                    "play_on_join": True,
                    "max_queue": config.MAX_QUEUE_SIZE,
                    "vol_default": config.DEFAULT_VOLUME,
                    "loop_mode": "none",
                    "quality": "high",
                    "thumb_mode": True,
                }
            }
            await self.db.groups.insert_one(group)
        return group
    
    async def update_group(self, chat_id: int, updates: dict):
        """Update group settings."""
        await self.db.groups.update_one({"_id": chat_id}, {"$set": updates}, upsert=True)
    
    async def set_group_active(self, chat_id: int, active: bool):
        """Set group active status."""
        await self.db.groups.update_one({"_id": chat_id}, {"$set": {"is_active": active}})
    
    async def add_sudo(self, user_id: int, name: str, added_by: int):
        from datetime import datetime
        await self.db.sudousers.update_one(
            {"_id": user_id},
            {"$set": {"name": name, "added_by": added_by, "added_at": datetime.utcnow()}},
            upsert=True
        )
    
    async def remove_sudo(self, user_id: int):
        await self.db.sudousers.delete_one({"_id": user_id})
    
    async def get_sudo_users(self) -> list:
        return await self.db.sudousers.find().to_list(length=None)
    
    async def is_sudo(self, user_id: int) -> bool:
        count = await self.db.sudousers.count_documents({"_id": user_id})
        return count > 0
    
    async def gban_user(self, user_id: int, reason: str, banned_by: int):
        from datetime import datetime
        await self.db.gbanned.update_one(
            {"_id": user_id},
            {"$set": {"reason": reason, "banned_by": banned_by, "banned_at": datetime.utcnow()}},
            upsert=True
        )
    
    async def ungban_user(self, user_id: int):
        await self.db.gbanned.delete_one({"_id": user_id})
    
    async def is_gbanned(self, user_id: int) -> bool:
        count = await self.db.gbanned.count_documents({"_id": user_id})
        return count > 0
    
    async def ban_user(self, chat_id: int, user_id: int):
        await self.db.groupbans.update_one(
            {"chat_id": chat_id, "user_id": user_id},
            {"$set": {"banned": True}},
            upsert=True
        )
    
    async def unban_user(self, chat_id: int, user_id: int):
        await self.db.groupbans.delete_one({"chat_id": chat_id, "user_id": user_id})
    
    async def is_banned(self, chat_id: int, user_id: int) -> bool:
        count = await self.db.groupbans.count_documents({"chat_id": chat_id, "user_id": user_id})
        return count > 0
    
    async def get_stats(self) -> dict:
        total_groups = await self.db.groups.count_documents({})
        active_groups = await self.db.groups.count_documents({"is_active": True})
        sudo_count = await self.db.sudousers.count_documents({})
        gban_count = await self.db.gbanned.count_documents({})
        return {
            "total_groups": total_groups,
            "active_groups": active_groups,
            "sudo_users": sudo_count,
            "gbanned_users": gban_count,
        }

    async def get_all_groups(self) -> list:
        """Return all active groups as list of dicts with '_id' key."""
        rows = await self.db.groups.find({"is_active": True}, {"_id": 1}).to_list(length=None)
        return [{"_id": row["_id"]} for row in rows]



async def init_database():
    """Initialize database - MongoDB, Supabase, or SQLite."""
    global db, mongo_client, sqlite_db, supabase_db, DB_MODE
    
    # Try Supabase first if configured (preferred for migration)
    if config.SUPABASE_URL and config.SUPABASE_KEY:
        try:
            from bot.utils.supabase_db import init_supabase
            init_supabase(config.SUPABASE_URL, config.SUPABASE_KEY)
            # Import AFTER init so we get the initialized instance
            import bot.utils.supabase_db as _supabase_module
            supabase_db = _supabase_module.supabase_db
            db = supabase_db
            DB_MODE = "supabase"
            logger.info("Supabase connected")
            return
        except Exception as e:
            logger.warning(f"Supabase connection failed: {e}")
    
    # Try MongoDB
    if config.MONGO_URI and config.MONGO_URI.strip() and config.MONGO_URI != "mongodb://mongo:27017/musicbot":
        try:
            from motor.motor_asyncio import AsyncIOMotorClient
            mongo_client = AsyncIOMotorClient(config.MONGO_URI, serverSelectionTimeoutMS=5000)
            await mongo_client.admin.command('ping')
            db = MongoDatabase(mongo_client)
            DB_MODE = "mongo"
            logger.info("MongoDB connected")
            return
        except Exception as e:
            logger.warning(f"MongoDB failed, using SQLite: {e}")
    
    # Use SQLite fallback
    from bot.utils.sqlite_db import init_sqlite_db
    init_sqlite_db(os.getenv("SQLITE_DB_PATH", "./data/bot.db"))
    # Import AFTER init so we get the initialized instance
    import bot.utils.sqlite_db as _sqlite_module
    sqlite_db = _sqlite_module.sqlite_db
    db = sqlite_db
    DB_MODE = "sqlite"
    logger.info("Using SQLite (zero-cost mode)")
