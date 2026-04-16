"""
Platform detection, routing, and extraction waterfall.
The Soul King's scouts searching the green seas! 💀🌊
"""

import logging
import asyncio
import re
from typing import Optional, Dict, Any
from pyrogram.types import Message

from bot.platforms.piped import piped
from bot.platforms.telegram import TelegramAudioHandler

logger = logging.getLogger(__name__)


def _sanitize_query(query: str) -> str:
    """Normalize user input without breaking valid URLs.

    NOTE: URLs require characters like '?', '&', '='. Do not strip them.
    """
    if not query:
        return ""
    # Remove only control characters; keep URL/query delimiters intact.
    query = re.sub(r"[\x00-\x1f\x7f]", "", query)
    return query.strip()


async def extract_audio(query: str, message: Message = None) -> Optional[Dict[str, Any]]:
    """
    Extract audio from Piped with a hard 45s timeout.
    """
    query = _sanitize_query(query)
    if not query:
        return None

    # 1. Telegram file check
    if message and message.reply_to_message:
        reply = message.reply_to_message
        if reply.audio or reply.voice or reply.video:
            handler = TelegramAudioHandler()
            return await handler.extract_from_message(reply)

    # 2. Piped public extraction
    try:
        async with asyncio.timeout(45.0):
            return await piped.extract(query)
    except asyncio.TimeoutError:
        logger.error(f"💀 Extraction TIMEOUT for {query}")
        return None
    except Exception as e:
        logger.error(f"💀 Extraction failed for {query}: {e}")
        return None


async def search_tracks(query: str, platform: str = "auto", limit: int = 5) -> list:
    """Search tracks on Piped."""
    query = _sanitize_query(query)
    if not query:
        return []

    try:
        return await piped.search(query, limit)
    except Exception as e:
        logger.error(f"💀 Unified search failed: {e}")
        return []


__all__ = [
    "extract_audio",
    "search_tracks",
]
