"""Database layer strictly standardized on Supabase."""

import logging
import sys
from config import config

logger = logging.getLogger(__name__)

# Global instance
# Other modules import this directly: keep name stable.
db = None
DB_MODE = "supabase"


class Database:
    """Abstract marker class for type hinting."""
    pass


async def init_database():
    """Initialize primary database (Supabase) with SQLite fallback."""
    global db, DB_MODE

    supabase_url = config.SUPABASE_URL
    supabase_key = config.SUPABASE_KEY

    if not supabase_url or not supabase_key:
        logger.warning("SUPABASE_URL or SUPABASE_KEY missing. Falling back to SQLite database.")
        _init_sqlite_fallback()
        return

    try:
        from bot.utils.supabase_db import init_supabase
        init_supabase(supabase_url, supabase_key)
        
        # Import AFTER init so we get the initialized singleton instance.
        import bot.utils.supabase_db as _supabase_module
        db = _supabase_module.supabase_db
        DB_MODE = "supabase"
        logger.info("Database standardized on Supabase Postgres.")
    except Exception as e:
        logger.error(f"Supabase connection failed: {e}. Falling back to SQLite.")
        _init_sqlite_fallback()


def _init_sqlite_fallback():
    """Helper to initialize the SQLite database as a primary backend."""
    global db, DB_MODE
    try:
        from bot.utils.sqlite_db import init_sqlite_db
        init_sqlite_db(config.SQLITE_DB_PATH)
        
        import bot.utils.sqlite_db as _sqlite_module
        db = _sqlite_module.sqlite_db
        DB_MODE = "sqlite"
        logger.info("Database failed over to local SQLite.")
    except Exception as e:
        logger.critical(f"SQLite fallback also failed: {e}")
        sys.exit(1)

