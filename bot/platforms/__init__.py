"""
Platform detection, routing, and extraction waterfall.
The Soul King's scouts searching the green seas! 💀🌊
"""

import logging
import asyncio
import re
from typing import Optional, Dict, Any
from pyrogram.types import Message

from bot.platforms.youtube import youtube
from bot.platforms.spotify import spotify
from bot.platforms.soundcloud import soundcloud
from bot.platforms.jiosaavn import jiosaavn
from bot.platforms.telegram import TelegramAudioHandler

logger = logging.getLogger(__name__)

# ─── URL patterns for platform detection ──────────────────────────────────────
URL_PATTERNS = {
    "youtube": [
        r"(?:https?://)?(?:www\.)?(?:youtube\.com|youtu\.be|youtube-nocookie\.com)",
    ],
    "spotify": [
        r"(?:https?://)?(?:open\.)?spotify\.com",
        r"spotify:",
    ],
    "soundcloud": [
        r"(?:https?://)?(?:www\.)?soundcloud\.com",
        r"(?:https?://)?snd\.sc",
    ],
    "jiosaavn": [
        r"(?:https?://)?(?:www\.)?(?:jiosaavn|saavn)\.com",
        r"(?:https?://)?open\.jiosaavn\.com",
    ],
}


def detect_platform(query: str) -> str:
    """Detect platform from URL or query."""
    for platform, patterns in URL_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, query, re.IGNORECASE):
                return platform
    return "search"


def _sanitize_query(query: str) -> str:
    """Basic input sanitization to prevent accidental shell-like issues."""
    return re.sub(r'[;&|`$(){}[\]<>*?]', '', query).strip()


async def extract_audio(query: str, message: Message = None) -> Optional[Dict[str, Any]]:
    """
    Extract audio from any supported platform with a hard 45s timeout and
    source waterfall (YT -> SoundCloud -> JioSaavn) for searches.
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

    # 2. Detect platform
    platform = detect_platform(query)

    try:
        # Hard 45s timeout for any extraction
        async with asyncio.timeout(45.0):
            if platform == "youtube":
                return await youtube.extract(query)
            
            elif platform == "spotify":
                return await spotify.extract(query)
            
            elif platform == "soundcloud":
                return await soundcloud.extract(query)
            
            elif platform == "jiosaavn":
                return await jiosaavn.extract(query)
            
            else:
                # ── SOURCE WATERFALL ──────────────────────────────────────────
                # If a generic search, try YouTube first
                logger.info(f"💀 Waterfall search: {query}")
                
                # YouTube (Primary)
                result = await youtube.extract(query)
                if result: return result
                
                # SoundCloud (Secondary)
                logger.debug(f"💀 YT failed, trying SoundCloud waterfall for: {query}")
                result = await soundcloud.extract(query)
                if result: return result
                
                # JioSaavn (Last resort for audio)
                logger.debug(f"💀 SC failed, trying JioSaavn waterfall for: {query}")
                result = await jiosaavn.extract(query)
                if result: return result
                
                return None
                
    except asyncio.TimeoutError:
        logger.error(f"💀 Extraction TIMEOUT for {query}")
        return None
    except Exception as e:
        logger.error(f"💀 Extraction failed for {query}: {e}")
        return None


async def search_tracks(query: str, platform: str = "auto", limit: int = 5) -> list:
    """Search tracks on specified platform."""
    query = _sanitize_query(query)
    if not query:
        return []

    if platform == "auto":
        platform = "youtube"
    
    try:
        if platform == "youtube":
            return await youtube.search(query, limit)
        
        elif platform == "spotify":
            return await spotify.search(query, limit)
        
        elif platform == "jiosaavn":
            return await jiosaavn.search(query, limit)
        
        elif platform == "soundcloud":
            return await soundcloud.search(query, limit)
        
        else:
            return await youtube.search(query, limit)
            
    except Exception as e:
        logger.error(f"💀 Unified search failed: {e}")
        return []


__all__ = [
    "detect_platform",
    "extract_audio",
    "search_tracks",
]
