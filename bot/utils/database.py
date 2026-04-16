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
    """Initialize Supabase as the single source of truth."""
    global db

    if not config.SUPABASE_URL or not config.SUPABASE_KEY:
        logger.critical("SUPABASE_URL and SUPABASE_KEY are required in config vars. Shutting down.")
        sys.exit(1)

    try:
        from bot.utils.supabase_db import init_supabase

        init_supabase(config.SUPABASE_URL, config.SUPABASE_KEY)

        # Import AFTER init so we get the initialized singleton instance.
        import bot.utils.supabase_db as _supabase_module

        db = _supabase_module.supabase_db
        logger.info("Database standardized on Supabase Postgres.")
    except Exception as e:
        logger.critical(f"Supabase connection failed: {e}")
        sys.exit(1)
