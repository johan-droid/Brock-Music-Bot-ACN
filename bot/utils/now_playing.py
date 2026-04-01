"""
Brook-themed Now Playing UI with auto-clean functionality.
Displays current song with progress bar and control buttons.
"""

import asyncio
import logging
from typing import Optional, Dict, Any
from pyrogram import Client
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message
from datetime import datetime, timedelta

from bot.core.queue import queue_manager
from bot.utils.cache import cache
from bot.utils.formatters import format_duration, create_progress_bar

logger = logging.getLogger(__name__)

# Brook-themed quotes for different states
BROOK_QUOTES = {
    "playing": [
        "🎵 Let the soul of music flow! YOHOHOHO!",
        "💀 My violin weeps with joy!",
        "🎸 Even a skeleton can feel this beat!",
        "🎼 Ah, what a melodious tune!",
        "💀 My heart... though I don't have one!",
    ],
    "paused": [
        "⏸ Even the Soul King needs a breath!",
        "💀 Paused... my violin rests!",
        "🎵 A moment of silence... Yohoho!",
    ],
    "queued": [
        "📋 Adding to the setlist!",
        "🎵 Another tune for the crew!",
        "💀 The queue grows! YOHOHOHO!",
    ]
}

# Auto-clean delays (from config)
NP_AUTOCLEAN_DELAY = 30  # seconds
SEARCH_MSG_AUTOCLEAN = 300  # seconds (5 minutes for music selection)


class NowPlayingUI:
    """
    Manages Now Playing messages with Brook theme.
    Auto-cleans old messages to prevent chat spam.
    """
    
    def __init__(self):
        self.active_messages: Dict[int, Message] = {}  # chat_id -> message
        self.cleanup_tasks: Dict[int, asyncio.Task] = {}
    
    def _get_random_quote(self, state: str) -> str:
        """Get a random Brook quote for the state."""
        import random
        quotes = BROOK_QUOTES.get(state, BROOK_QUOTES["playing"])
        return random.choice(quotes)
    
    def _format_np_text(self, track: Dict[str, Any], progress: int = 0, status: str = "playing") -> str:
        """Format Now Playing text with Brook theme."""
        title = track.get("title", "Unknown Title")
        artist = track.get("artist") or track.get("uploader", "Unknown Artist")
        duration = track.get("duration", 0)
        source = track.get("source", "unknown").upper()
        
        # Format duration
        duration_str = format_duration(duration)
        
        # Progress bar (if playing)
        if status == "playing" and duration > 0:
            progress_bar = create_progress_bar(progress, duration, length=20)
            time_str = f"{format_duration(progress)} / {duration_str}"
        else:
            progress_bar = "▱" * 20
            time_str = duration_str
        
        # Source emoji
        source_emoji = {
            "YOUTUBE": "📺",
            "JIOSAAVN": "🎵",
            "SOUNDCLOUD": "☁️",
            "SPOTIFY": "🎧",
            "TELEGRAM": "📱",
        }.get(source, "🎵")
        
        # Status emoji
        status_emoji = {
            "playing": "▶️",
            "paused": "⏸",
            "queued": "📋",
        }.get(status, "▶️")
        
        quote = self._get_random_quote(status)
        
        text = f"""
💀 **{status_emoji} NOW PLAYING - Soul King FM**

🎵 **{title}**
🎤 {artist}

{progress_bar}
⏱ {time_str} | {source_emoji} {source}

💬 _{quote}_
"""
        return text.strip()
    
    def _create_control_buttons(self, status: str = "playing") -> InlineKeyboardMarkup:
        """Create control buttons based on status."""
        if status == "playing":
            buttons = [
                [
                    InlineKeyboardButton("⏸ Pause", callback_data="pause"),
                    InlineKeyboardButton("⏭ Skip", callback_data="skip"),
                ],
                [
                    InlineKeyboardButton("🔊 Volume", callback_data="volume"),
                    InlineKeyboardButton("📋 Queue", callback_data="queue"),
                ],
                [
                    InlineKeyboardButton("💀 Soul King Info", callback_data="brok_info"),
                ]
            ]
        elif status == "paused":
            buttons = [
                [
                    InlineKeyboardButton("▶️ Resume", callback_data="resume"),
                    InlineKeyboardButton("⏹ Stop", callback_data="stop"),
                ],
                [
                    InlineKeyboardButton("📋 Queue", callback_data="queue"),
                ]
            ]
        else:
            buttons = [
                [
                    InlineKeyboardButton("▶️ Play", callback_data="play"),
                    InlineKeyboardButton("📋 Queue", callback_data="queue"),
                ]
            ]
        
        return InlineKeyboardMarkup(buttons)
    
    async def send_now_playing(self, client: Client, chat_id: int, track: Dict[str, Any], 
                               progress: int = 0, status: str = "playing"):
        """Send or update Now Playing message."""
        text = self._format_np_text(track, progress, status)
        buttons = self._create_control_buttons(status)
        
        # Delete old message if exists
        if chat_id in self.active_messages:
            try:
                await self.active_messages[chat_id].delete()
            except Exception:
                pass
            del self.active_messages[chat_id]
        
        # Send new message
        try:
            message = await client.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=buttons,
                disable_web_page_preview=True
            )
            self.active_messages[chat_id] = message
            
            # Schedule auto-clean
            self._schedule_cleanup(chat_id, NP_AUTOCLEAN_DELAY)
            
            return message
        except Exception as e:
            logger.error(f"Failed to send Now Playing: {e}")
            return None
    
    async def update_progress(self, client: Client, chat_id: int, track: Dict[str, Any], 
                             progress: int, status: str = "playing"):
        """Update progress bar on existing message."""
        if chat_id not in self.active_messages:
            return
        
        message = self.active_messages[chat_id]
        text = self._format_np_text(track, progress, status)
        buttons = self._create_control_buttons(status)
        
        try:
            await message.edit_text(text, reply_markup=buttons, disable_web_page_preview=True)
        except Exception as e:
            logger.debug(f"Failed to update NP: {e}")
    
    def _schedule_cleanup(self, chat_id: int, delay: int):
        """Schedule auto-cleanup of message."""
        # Cancel existing task
        if chat_id in self.cleanup_tasks:
            self.cleanup_tasks[chat_id].cancel()
        
        # Create new cleanup task
        task = asyncio.create_task(self._cleanup_message(chat_id, delay))
        self.cleanup_tasks[chat_id] = task
    
    async def _cleanup_message(self, chat_id: int, delay: int):
        """Auto-clean message after delay."""
        await asyncio.sleep(delay)
        
        if chat_id in self.active_messages:
            try:
                await self.active_messages[chat_id].delete()
            except Exception:
                pass
            del self.active_messages[chat_id]
        
        if chat_id in self.cleanup_tasks:
            del self.cleanup_tasks[chat_id]
    
    async def cleanup_chat(self, chat_id: int):
        """Clean up all messages for a chat immediately."""
        # Cancel cleanup task
        if chat_id in self.cleanup_tasks:
            self.cleanup_tasks[chat_id].cancel()
            del self.cleanup_tasks[chat_id]
        
        # Delete message
        if chat_id in self.active_messages:
            try:
                await self.active_messages[chat_id].delete()
            except Exception:
                pass
            del self.active_messages[chat_id]


# Global instance
np_ui = NowPlayingUI()
