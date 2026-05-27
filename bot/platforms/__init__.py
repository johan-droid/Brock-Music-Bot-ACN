"""
Platform detection, routing, and extraction waterfall.
The Soul King's scouts searching the green seas! 💀🌊
"""

import logging
import asyncio
import re
from typing import Optional, Dict, Any
from pyrogram.types import Message

from bot.platforms.telegram import TelegramAudioHandler

logger = logging.getLogger(__name__)


def _get_music_backend():
    from bot.core.music_backend import music_backend

    return music_backend


def _sanitize_query(query: str) -> str:
    """Normalize user input without breaking valid URLs.

    NOTE: URLs require characters like '?', '&', '='. Do not strip them.
    """
    if not query:
        return ""
    # Remove only control characters; keep URL/query delimiters intact.
    query = re.sub(r"[\x00-\x1f\x7f]", "", query)
    return query.strip()


async def extract_audio(query: str, message: Optional[Message] = None) -> Optional[Dict[str, Any]]:
    """Extract audio using the shared VK-first aggregator with a hard 45s timeout."""
    query = _sanitize_query(query)
    if not query:
        return None

    # 1. Telegram file check
    if message and message.reply_to_message:
        reply = message.reply_to_message
        if reply.audio or reply.voice or reply.video:
            handler = TelegramAudioHandler()
            return await handler.extract_from_message(reply)

    # 2. Shared backend resolution
    try:
        return await asyncio.wait_for(_get_music_backend().resolve(query), timeout=45.0)
    except asyncio.TimeoutError:
        logger.error(f"💀 Extraction TIMEOUT for {query}")
        return None
    except Exception as e:
        logger.error(f"💀 Extraction failed for {query}: {e}")
        return None


async def search_tracks(query: str, platform: str = "auto", limit: int = 5) -> list:
    """Search tracks using the shared VK-first aggregator."""
    query = _sanitize_query(query)
    if not query:
        return []

    try:
        return await _get_music_backend().search(query, limit)
    except Exception as e:
        logger.error(f"💀 Unified search failed: {e}")
        return []


__all__ = [
    "extract_audio",
    "search_tracks",
]
