"""Database layer with support for Neon or SQLite fallback."""

import logging
import sys
from config import config

logger = logging.getLogger(__name__)

# Global instance
# Other modules import this directly: keep name stable.
db = None
DB_MODE = "sqlite"


class Database:
    """Abstract marker class for type hinting."""
    pass

    async def get_quiz_score(self, user_id: int) -> dict:
        """Get user quiz score."""
        pass

    async def save_quiz_score(self, user_id: int, score_added: int) -> dict:
        """Save user quiz score."""
        pass

    async def get_top_quiz_scores(self, limit: int = 10, user_ids: list = None) -> list:
        """Get top quiz scores."""
        pass


async def init_database():
    """Initialize primary database (Neon > SQLite fallback)."""
    global db, DB_MODE

    # Priority 1: Neon Database
    neon_url = config.NEON_DATABASE_URL
    if neon_url:
        try:
            from bot.utils.neon_db import init_neon
            init_neon(neon_url)
            
            import bot.utils.neon_db as _neon_module
            db = _neon_module.neon_db
            DB_MODE = "neon"
            logger.info("Database initialized on Neon PostgreSQL.")
            return
        except Exception as e:
            logger.error(f"Neon connection failed: {e}. Falling back to SQLite.")

    # Priority 2: SQLite fallback
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

