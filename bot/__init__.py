"""Bot package initialization."""

from bot.core.bot import bot_client
from bot.core.userbot import userbot_clients
from bot.utils.database import db
from bot.utils.cache import redis_client

__all__ = [
    "bot_client",
    "userbot_clients", 
    "db",
    "redis_client",
]
