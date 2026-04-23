"""Environment settings for the Soul King Telegram Mini App backend."""

from __future__ import annotations

import re
from typing import List, Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class MiniAppSettings(BaseSettings):
    """Settings loaded from environment for mini app service."""

    model_config = SettingsConfigDict(
        env_file=(".env.local", ".env", "bot/.env.local", "bot/.env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    BOT_TOKEN: Optional[str] = None

    MINI_APP_WEB_URL: Optional[str] = None
    MINI_APP_ALLOWED_ORIGINS: str = "*"
    MINI_APP_ALLOW_CREDENTIALS: bool = False

    MINI_APP_INITDATA_MAX_AGE_SECONDS: int = 3600
    MINI_APP_RATE_LIMIT_PER_MINUTE: int = 180

    MINI_APP_STREAM_PROXY_TIMEOUT_SECONDS: int = 20
    MINI_APP_STREAM_PROXY_CHUNK_SIZE: int = 65536
    MINI_APP_STREAM_PROXY_SECRET: Optional[str] = None

    MINI_APP_LOBBY_STATE_TTL_SECONDS: int = 300
    MINI_APP_SESSION_TTL_SECONDS: int = 604800
    MINI_APP_SESSION_MAX_RECENT_TRACKS: int = 50

    @property
    def allowed_origins(self) -> List[str]:
        value = (self.MINI_APP_ALLOWED_ORIGINS or "").strip()
        if not value:
            return []
        return [item.strip() for item in re.split(r"[\s,;]+", value) if item.strip()]

    @property
    def stream_proxy_secret(self) -> str:
        return (
            (self.MINI_APP_STREAM_PROXY_SECRET or "").strip()
            or (self.BOT_TOKEN or "").strip()
            or "mini-app-dev-secret"
        )


settings = MiniAppSettings()
