import logging
from pathlib import Path
from pydantic_settings import BaseSettings
from pydantic import field_validator
from typing import Optional, List

logger = logging.getLogger(__name__)


class Config(BaseSettings):
    """Bot configuration loaded from environment variables."""
    
    # Telegram API mode (set FALSE to run without Telegram client auth)
    TELEGRAM_ENABLED: bool = True

    # Telegram API credentials (from my.telegram.org)
    # Required only when TELEGRAM_ENABLED=true
    API_ID: Optional[int] = None
    API_HASH: Optional[str] = None
    
    # Bot token from @BotFather
    BOT_TOKEN: Optional[str] = None
    BOT_USERNAME: Optional[str] = None
    
    # Owner user ID
    OWNER_ID: Optional[int] = None
    
    # Userbot session strings (1 required when TELEGRAM_ENABLED=true)
    SESSION_STRING_1: Optional[str] = None
    SESSION_STRING_2: Optional[str] = None
    SESSION_STRING_3: Optional[str] = None
    SESSION_STRING_4: Optional[str] = None
    SESSION_STRING_5: Optional[str] = None
    
    # MongoDB
    MONGO_URI: str = "mongodb://mongo:27017/musicbot"
    
    # Redis (optional - falls back to SQLite if not configured)
    REDIS_HOST: Optional[str] = None
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: Optional[str] = None
    
    # Upstash Redis (optional)
    UPSTASH_REDIS_REST_URL: Optional[str] = None
    UPSTASH_REDIS_REST_TOKEN: Optional[str] = None
    
    # SQLite cache path (used when Redis is not available)
    SQLITE_CACHE_PATH: str = "./data/cache.db"
    
    # Supabase (alternative to MongoDB)
    SUPABASE_URL: Optional[str] = None
    SUPABASE_KEY: Optional[str] = None
    
    # Spotify (optional)
    SPOTIFY_CLIENT_ID: Optional[str] = None
    SPOTIFY_CLIENT_SECRET: Optional[str] = None
    
    # Genius (optional - for lyrics)
    GENIUS_TOKEN: Optional[str] = None
    
    # Log group/channel ID (optional)
    LOG_GROUP_ID: Optional[int] = None

    @field_validator("LOG_GROUP_ID", mode="before")
    def normalize_log_group_id(cls, v):
        if v in (None, "", "None"):
            return None
        return v

    # Bot behavior settings
    MAX_QUEUE_SIZE: int = 100
    DEFAULT_VOLUME: int = 100
    COMMAND_COOLDOWN: int = 3  # seconds
    
    # Audio quality settings (Telegram 2025 optimized)
    AUDIO_QUALITY: str = "high"  # standard, high, premium, lossless
    AUDIO_BITRATE: int = 192  # kbps (128-320)
    AUDIO_LOUDNORM: bool = True  # EBU R128 loudness normalization

    # Now Playing card auto-clean (seconds)
    NP_AUTOCLEAN_DELAY: int = 30       # delete NP card N seconds after track ends / /stop
    SEARCH_MSG_AUTOCLEAN: int = 8      # delete "Searching..." msg N seconds after reply sent
    NP_UPDATE_INTERVAL: int = 20       # seconds between progress bar edits (higher = less CPU load)

    # yt-dlp concurrency & caching
    YTDL_CONCURRENT_LIMIT: int = 3     # max parallel yt-dlp extractions
    YTDL_CACHE_TTL: int = 19800        # CDN URL cache TTL seconds (5.5h)

    @property
    def session_strings(self) -> List[str]:
        """Return list of valid (non-empty) session strings."""
        raw = [
            self.SESSION_STRING_1, 
            self.SESSION_STRING_2, 
            self.SESSION_STRING_3, 
            self.SESSION_STRING_4, 
            self.SESSION_STRING_5
        ]
        return [s for s in raw if s and s.strip()]
    
    class Config:
        # Priority: Environment Variables -> .env.local -> .env
        env_file = ".env", ".env.local"
        env_file_encoding = "utf-8"
        extra = "ignore"
        # Make .env file optional for Docker/Cloud environments
        case_sensitive = False


# Global config instance
# Use .env.local (or bot/.env.local) by default when available for local development credentials.
import os
from dotenv import load_dotenv

POSSIBLE_ENV_PATHS = ["bot/.env.local", ".env.local", ".env"]
env_path = next((p for p in POSSIBLE_ENV_PATHS if os.path.exists(p)), None)

if env_path:
    load_dotenv(env_path)
    # keep as fallback; pydantic loads env by name too
    Config.Config.env_file = env_path

# Also prefer absolute /app/bot/.env.local when running in container root
container_local_env = "/app/bot/.env.local"
if not env_path and os.path.exists(container_local_env):
    load_dotenv(container_local_env)
    Config.Config.env_file = container_local_env

config = Config()

# Robust API credential synchronization for production environments
def synchronize_api_credentials():
    """Ensure API credentials are correctly prioritized from environment variables."""
    global config
    
    # 1. Environment variable search (Highest Priority)
    env_keys_id = ["API_ID", "TELEGRAM_API_ID", "TG_API_ID", "BOT_API_ID", "APP_ID"]
    env_keys_hash = ["API_HASH", "TELEGRAM_API_HASH", "TG_API_HASH", "BOT_API_HASH", "APP_HASH"]
    
    found_id_key = None
    found_id_val = None
    for k in env_keys_id:
        val = os.getenv(k)
        if val and "your_" not in val.lower():
            found_id_key = k
            found_id_val = val
            break
            
    found_hash_key = None
    found_hash_val = None
    for k in env_keys_hash:
        val = os.getenv(k)
        if val and "your_" not in val.lower():
            found_hash_key = k
            found_hash_val = val
            break

    # 2. Log detections for debugging
    if found_id_key:
        logger.info(f"Detected API_ID via environment variable: {found_id_key}")
        try:
            config.API_ID = int(found_id_val)
        except ValueError:
            logger.error(f"Environment variable {found_id_key} must be numeric, got: {found_id_val}")
            config.API_ID = None
    
    if found_hash_key:
        logger.info(f"Detected API_HASH via environment variable: {found_hash_key}")
        config.API_HASH = found_hash_val

    # 3. Fallback to file reading if still missing (for local dev)
    if not config.API_ID or not config.API_HASH:
        for candidate in POSSIBLE_ENV_PATHS + [container_local_env]:
            if os.path.exists(candidate):
                try:
                    with open(candidate, "r", encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if not line or line.startswith("#") or "=" not in line:
                                continue
                            k, v = line.split("=", 1)
                            k, v = k.strip(), v.strip().strip('"').strip("'")
                            
                            if not config.API_ID and k in env_keys_id and "your_" not in v.lower():
                                try:
                                    config.API_ID = int(v)
                                    logger.info(f"Found API_ID in file {candidate}")
                                except: pass
                                
                            if not config.API_HASH and k in env_keys_hash and "your_" not in v.lower():
                                config.API_HASH = v
                                logger.info(f"Found API_HASH in file {candidate}")
                except Exception as e:
                    logger.debug(f"Could not read env file {candidate}: {e}")

    # 4. Final Validation & Graceful Fallback
    if config.TELEGRAM_ENABLED and (not config.API_ID or not config.API_HASH):
        missing = []
        if not config.API_ID: missing.append("API_ID")
        if not config.API_HASH: missing.append("API_HASH")

        logger.warning(
            "CRITICAL: TELEGRAM_ENABLED is true but missing/invalid credentials: %s. "
            "Please ensure these are set in your Railway Dashboard Variables exactly. "
            "Bot will idle until configured.",
            ", ".join(missing),
        )
        # safe fallback - disable bot features while idling
        config.TELEGRAM_ENABLED = False

# Run synchronization
synchronize_api_credentials()


# Ensure session strings are loaded from env directly if empty config
if config.TELEGRAM_ENABLED and not config.session_strings:
    val = os.getenv("SESSION_STRING_1")
    if val and "your_" not in val.lower():
        config.SESSION_STRING_1 = val
    config.SESSION_STRING_2 = config.SESSION_STRING_2 or os.getenv("SESSION_STRING_2")
    config.SESSION_STRING_3 = config.SESSION_STRING_3 or os.getenv("SESSION_STRING_3")
    config.SESSION_STRING_4 = config.SESSION_STRING_4 or os.getenv("SESSION_STRING_4")
    config.SESSION_STRING_5 = config.SESSION_STRING_5 or os.getenv("SESSION_STRING_5")

