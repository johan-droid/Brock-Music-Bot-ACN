"""Utils package initialization."""

from bot.utils.database import db, init_database, Database
from bot.utils.cache import redis_client, cache, init_redis, init_cache, Cache
from bot.utils.thumbnails import thumb_generator, generate_np_thumbnail, ThumbnailGenerator
from bot.utils.formatters import (
    format_duration,
    format_time_simple,
    create_progress_bar,
    format_track_info,
    truncate_text,
    format_queue_list,
    format_bytes,
)
from bot.utils.permissions import (
    is_owner,
    is_sudo,
    is_gbanned,
    is_group_admin,
    get_permission_level,
    require_admin,
    require_sudo,
    require_owner,
    rate_limit,
)
from bot.utils.logger import setup_logging, TelegramLogHandler

__all__ = [
    # Database
    "db",
    "init_database",
    "Database",
    # Cache
    "redis_client",
    "cache",
    "init_redis",
    "init_cache",
    "Cache",
    # Thumbnails
    "thumb_generator",
    "generate_np_thumbnail",
    "ThumbnailGenerator",
    # Formatters
    "format_duration",
    "format_time_simple",
    "create_progress_bar",
    "format_track_info",
    "truncate_text",
    "format_queue_list",
    "format_bytes",
    # Permissions
    "is_owner",
    "is_sudo",
    "is_gbanned",
    "is_group_admin",
    "get_permission_level",
    "require_admin",
    "require_sudo",
    "require_owner",
    "rate_limit",
    # Logger
    "setup_logging",
    "TelegramLogHandler",
]
