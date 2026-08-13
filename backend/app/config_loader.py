"""Config loader - extracted from root config.py"""
import logging
import os
from pathlib import Path
from pydantic_settings import BaseSettings
from pydantic import field_validator
from typing import Optional, List, Dict
from dotenv import dotenv_values

logger = logging.getLogger(__name__)

# Resolve env file paths relative to this file so config loads correctly
# no matter where the process is launched from.
_BASE_DIR = Path(__file__).resolve().parent           # app/
_ROOT_DIR = _BASE_DIR.parent                          # project root
_ENV_FILES = tuple(
    str(p) for p in (
        _ROOT_DIR / ".env.local",
        _ROOT_DIR / ".env",
        _BASE_DIR / ".env.local",
    )
)
_ENV_CANDIDATES = list(_ENV_FILES) + ["/app/.env.local"]


class Config(BaseSettings):
    """Bot configuration loaded from environment variables."""

    TELEGRAM_ENABLED: bool = True
    API_ID: Optional[int] = None
    API_HASH: Optional[str] = None
    BOT_TOKEN: Optional[str] = None
    BOT_ID: Optional[int] = None
    BOT_USERNAME: Optional[str] = None
    BOT_USERNAME_ALT: Optional[str] = None
    ADMIN_PASSWORD: Optional[str] = None
    OWNER_ID: Optional[int] = None

    SESSION_STRING_1: Optional[str] = None
    SESSION_STRING_2: Optional[str] = None
    SESSION_STRING_3: Optional[str] = None
    SESSION_STRING_4: Optional[str] = None
    SESSION_STRING_5: Optional[str] = None

    SESSION_FILE_PATH_1: Optional[str] = None
    SESSION_FILE_PATH_2: Optional[str] = None
    SESSION_FILE_PATH_3: Optional[str] = None
    SESSION_FILE_PATH_4: Optional[str] = None
    SESSION_FILE_PATH_5: Optional[str] = None

    SESSION_FILE_B64_1: Optional[str] = None
    SESSION_FILE_B64_2: Optional[str] = None
    SESSION_FILE_B64_3: Optional[str] = None
    SESSION_FILE_B64_4: Optional[str] = None
    SESSION_FILE_B64_5: Optional[str] = None

    MONGO_URI: str = "mongodb://mongo:27017/musicbot"
    REDIS_HOST: Optional[str] = None
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: Optional[str] = None
    UPSTASH_REDIS_REST_URL: Optional[str] = None
    UPSTASH_REDIS_REST_TOKEN: Optional[str] = None
    SQLITE_CACHE_PATH: str = "./data/cache.db"
    SQLITE_DB_PATH: str = "./data/database.db"
    NEON_DATABASE_URL: Optional[str] = None
    GENIUS_TOKEN: Optional[str] = None
    LOG_GROUP_ID: Optional[int] = None
    METRICS_HTTP_ENABLED: bool = False
    METRICS_HTTP_TOKEN: Optional[str] = None
    METRICS_PROMETHEUS_ENABLED: bool = False
    WEBHOOK_URL: Optional[str] = None
    WEBHOOK_PATH: str = "/webhook"
    WEBHOOK_SECRET: Optional[str] = None
    BOUND_GROUP_ID: Optional[int] = None

    @field_validator("LOG_GROUP_ID", mode="before")
    def normalize_log_group_id(cls, v):
        if v in (None, "", "None"):
            return None
        return v

    MAX_QUEUE_SIZE: int = 100
    DEFAULT_VOLUME: int = 100
    COMMAND_COOLDOWN: int = 3
    AUDIO_QUALITY: str = "high"
    AUDIO_BITRATE: int = 192
    AUDIO_LOUDNORM: bool = True
    LEGAL_SOURCES_FIRST: bool = True
    PRIORITIZE_EXTRACTORS: bool = False
    PARALLEL_SEARCH: bool = False
    MUSIC_MICROSERVICE_URL: Optional[str] = None
    MUSIC_PROVIDER_PRIORITY: str = "youtube,soundcloud,apple_music"
    NP_AUTOCLEAN_DELAY: int = 30
    SEARCH_MSG_AUTOCLEAN: int = 8
    NP_UPDATE_INTERVAL: int = 3
    VC_PLAY_TIMEOUT: int = 20
    AUTO_START_VC: bool = True
    AUTO_START_VC_TITLE: str = "Music Bot Live"
    ASSISTANT_MAX_ACTIVE_CHATS: int = 0
    ENABLE_PREVIOUS_TRACK: bool = True
    ENABLE_VC_DEBUG: bool = True
    ENABLE_QUEUE_EXPORT: bool = True
    ENABLE_AUTO_RETRY_USERBOT_AUTH: bool = True

    @property
    def session_strings(self) -> List[str]:
        raw = [self.SESSION_STRING_1, self.SESSION_STRING_2, self.SESSION_STRING_3, self.SESSION_STRING_4, self.SESSION_STRING_5]
        return [s for s in raw if s and s.strip()]

    @property
    def bot_usernames(self) -> List[str]:
        candidates = [self.BOT_USERNAME, self.BOT_USERNAME_ALT]
        return [u.strip() for u in candidates if u and u.strip()]

    @property
    def bound_group_id(self) -> Optional[int]:
        return self.BOUND_GROUP_ID

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
        entries: List[Dict[str, str]] = []
        for idx in range(1, 6):
            session_str = self._clean_optional(getattr(self, f"SESSION_STRING_{idx}", None))
            if session_str:
                entries.append({"type": "string", "value": session_str, "label": f"SESSION_STRING_{idx}"})
                continue
            file_path = self._clean_optional(getattr(self, f"SESSION_FILE_PATH_{idx}", None))
            if file_path:
                entries.append({"type": "file", "value": file_path, "label": f"SESSION_FILE_PATH_{idx}"})
                continue
            file_b64 = self._clean_optional(getattr(self, f"SESSION_FILE_B64_{idx}", None))
            if file_b64:
                entries.append({"type": "b64", "value": file_b64, "label": f"SESSION_FILE_B64_{idx}"})
                continue
        return entries

    class Config:
        env_file = _ENV_FILES
        env_file_encoding = "utf-8"
        extra = "ignore"
        case_sensitive = False


def load_config() -> Config:
    POSSIBLE_ENV_PATHS = [p for p in _ENV_CANDIDATES if p]
    env_path = next((p for p in POSSIBLE_ENV_PATHS if os.path.exists(p)), None)
    if env_path:
        env_values = dotenv_values(env_path)
        for key, value in env_values.items():
            if value is None:
                continue
            if len(value) > 32767:
                sensitive_prefixes = ("SESSION", "TOKEN", "PASSWORD", "SECRET", "KEY", "B64")
                display_key = key if not any(key.upper().startswith(p) for p in sensitive_prefixes) else f"{key[:3]}***"
                logger.warning("Skipping env var %s from %s because its value is too large for the OS env (len=%d)", display_key, env_path, len(value))
                continue
            os.environ.setdefault(key, value)

    config = Config()

    env_keys_id = ["API_ID", "TELEGRAM_API_ID", "TG_API_ID", "BOT_API_ID", "APP_ID"]
    env_keys_hash = ["API_HASH", "TELEGRAM_API_HASH", "TG_API_HASH", "BOT_HASH", "APP_HASH"]

    found_id_val = None
    found_id_key = None
    for k in env_keys_id:
        val = os.getenv(k)
        if val and "your_" not in val.lower():
            found_id_key = k
            found_id_val = val
            break

    found_hash_val = None
    found_hash_key = None
    for k in env_keys_hash:
        val = os.getenv(k)
        if val and "your_" not in val.lower():
            found_hash_key = k
            found_hash_val = val
            break

    if found_id_val is not None:
        try:
            config.API_ID = int(found_id_val)
        except ValueError:
            logger.error(f"API_ID variable '{found_id_key}' must be numeric")
            config.API_ID = None

    if found_hash_val:
        config.API_HASH = found_hash_val

    if not config.API_ID or not config.API_HASH:
        for candidate in POSSIBLE_ENV_PATHS:
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

    if config.TELEGRAM_ENABLED and (not config.API_ID or not config.API_HASH):
        missing = []
        if not config.API_ID:
            missing.append("API_ID")
        if not config.API_HASH:
            missing.append("API_HASH")
        logger.warning("CRITICAL: TELEGRAM_ENABLED is true but missing/invalid credentials: %s. Bot will idle until configured.", ", ".join(missing))
        config.TELEGRAM_ENABLED = False

    if config.TELEGRAM_ENABLED:
        token_keys = ["BOT_TOKEN", "TELEGRAM_BOT_TOKEN", "TG_BOT_TOKEN", "BOT_API_TOKEN"]
        for k in token_keys:
            val = os.getenv(k)
            if val and "your_" not in val.lower():
                if not config.BOT_TOKEN or "your_" in config.BOT_TOKEN.lower():
                    config.BOT_TOKEN = val
                    break

    if config.TELEGRAM_ENABLED and not config.userbot_auth_entries:
        str_val = os.getenv("SESSION_STRING_1")
        if str_val and "your_" not in str_val.lower():
            config.SESSION_STRING_1 = str_val

    return config


config = load_config()
