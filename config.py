import logging
from pathlib import Path
from pydantic_settings import BaseSettings
from pydantic import field_validator
from typing import Optional, List, Dict

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
    # Generate with: python generate_session.py
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

    # Source policy settings
    # LEGAL_SOURCES_FIRST=true prefers licensed/official catalogs for generic text search.
    LEGAL_SOURCES_FIRST: bool = True
    # For Spotify links: keep YouTube as a final fallback only when explicitly enabled.
    SPOTIFY_YOUTUBE_FALLBACK: bool = False

    # Now Playing card auto-clean (seconds)
    NP_AUTOCLEAN_DELAY: int = 30       # delete NP card N seconds after track ends / /stop
    SEARCH_MSG_AUTOCLEAN: int = 8      # delete "Searching..." msg N seconds after reply sent
    NP_UPDATE_INTERVAL: int = 5        # seconds between progress bar edits for live tracking

    # yt-dlp concurrency & caching
    YTDL_CONCURRENT_LIMIT: int = 3     # max parallel yt-dlp extractions
    YTDL_CACHE_TTL: int = 19800        # CDN URL cache TTL seconds (5.5h)

    # Voice Chat control timeout (seconds) to avoid silent py-tgcalls hangs
    VC_PLAY_TIMEOUT: int = 20
    AUTO_START_VC: bool = True
    AUTO_START_VC_TITLE: str = "Music Bot Live"
    # Per-assistant active VC cap. 0 means unlimited.
    ASSISTANT_MAX_ACTIVE_CHATS: int = 0

    # Optional feature flags
    ENABLE_PREVIOUS_TRACK: bool = True
    ENABLE_VC_DEBUG: bool = True
    ENABLE_QUEUE_EXPORT: bool = True
    ENABLE_AUTO_RETRY_USERBOT_AUTH: bool = True

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

    @staticmethod
    def _clean_optional(value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        trimmed = value.strip()
        if not trimmed or trimmed.lower() == "none":
            return None
        return trimmed

    @property
    def userbot_auth_entries(self) -> List[Dict[str, str]]:
        """Return ordered userbot session string entries."""
        entries: List[Dict[str, str]] = []

        for idx in range(1, 6):
            session_str = self._clean_optional(getattr(self, f"SESSION_STRING_{idx}", None))
            if session_str:
                entries.append({
                    "mode": "string",
                    "value": session_str,
                    "label": f"SESSION_STRING_{idx}",
                })

        return entries
    
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
from dotenv import dotenv_values

POSSIBLE_ENV_PATHS = ["bot/.env.local", ".env.local", ".env"]
env_path = next((p for p in POSSIBLE_ENV_PATHS if os.path.exists(p)), None)

if env_path:
    # Do not push super-long values (like SESSION_FILE_B64) into OS environment on Windows
    # where there is a hard limit of 32767 characters per variable.
    env_values = dotenv_values(env_path)
    for key, value in env_values.items():
        if value is None:
            continue
        if len(value) > 32767:
            logger.warning(
                "Skipping env var %s from %s because its value is too large for the OS env (len=%d)",
                key,
                env_path,
                len(value),
            )
            continue
        os.environ.setdefault(key, value)

    # Set target env file path with runtime assignment (type may vary from tuple default)
    setattr(Config.Config, "env_file", env_path)

# Also prefer absolute /app/bot/.env.local when running in container root
container_local_env = "/app/bot/.env.local"
if not env_path and os.path.exists(container_local_env):
    env_values = dotenv_values(container_local_env)
    for key, value in env_values.items():
        if value is None:
            continue
        if len(value) > 32767:
            logger.warning(
                "Skipping env var %s from %s because its value is too large for the OS env (len=%d)",
                key,
                container_local_env,
                len(value),
            )
            continue
        os.environ.setdefault(key, value)

    # We rely on os.environ overrides instead of forcing Config.Config.env_file typing mismatch.
    # (env_file is a strict tuple of filenames in pydantic Settings, so assign only in class definition.)
    pass

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

    # 2. Apply detections
    if found_id_key and found_id_val is not None:
        try:
            config.API_ID = int(found_id_val)
        except ValueError:
            logger.error(f"❌ API_ID variable '{found_id_key}' must be numeric, got: {found_id_val}")
            config.API_ID = None
    
    if found_hash_key:
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

                            if not config.API_ID and v and k in env_keys_id and "your_" not in v.lower():
                                try:
                                    config.API_ID = int(v)
                                except ValueError:
                                    pass
                                
                            if not config.API_HASH and v and k in env_keys_hash and "your_" not in v.lower():
                                config.API_HASH = v
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


# Ensure BOT_TOKEN and session strings are loaded from env directly if empty config
def synchronize_bot_token():
    global config
    if config.TELEGRAM_ENABLED:
        token_keys = ["BOT_TOKEN", "TELEGRAM_BOT_TOKEN", "TG_BOT_TOKEN", "BOT_API_TOKEN"]
        for k in token_keys:
            val = os.getenv(k)
            if val and "your_" not in val.lower():
                if not config.BOT_TOKEN or "your_" in config.BOT_TOKEN.lower():
                    config.BOT_TOKEN = val
                    break

    # Userbot auth fallback (direct env fallback)
    if config.TELEGRAM_ENABLED and not config.userbot_auth_entries:
        str_val = os.getenv("SESSION_STRING_1")
        if str_val and "your_" not in str_val.lower():
            config.SESSION_STRING_1 = str_val

# Run token/session sync
synchronize_bot_token()


