"""Telegram audio file handler."""

import logging
import os
from typing import Optional, Dict, Any
from pyrogram.types import Message
from bot.core import bot as bot_module

logger = logging.getLogger(__name__)

# Directory for downloaded files
DOWNLOAD_DIR = "/tmp/musicbot"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)


class TelegramAudioHandler:
    """Handle Telegram audio/video file downloads."""
    
    def __init__(self):
        self.download_dir = DOWNLOAD_DIR
    
    async def extract_from_message(self, message: Message) -> Optional[Dict[str, Any]]:
        """Extract audio from a Telegram message with audio/video.
        
        Args:
            message: Telegram message containing audio/video
            
        Returns:
            Dict with file path and metadata, or None
        """
        audio = None
        video = None
        
        # Check for audio
        if message.audio:
            audio = message.audio
        elif message.voice:
            audio = message.voice
        elif message.video_note:
            video = message.video_note
        elif message.video:
            video = message.video
        elif message.document:
            # Check if document is audio/video
            doc = message.document
            mime = doc.mime_type or ""
            if mime.startswith("audio/") or mime.startswith("video/"):
                audio = doc
        
        if not audio and not video:
            return None
        
        media = audio or video
        
        try:
            # Download the file
            file_path = await self._download_media(media)
            if not file_path:
                return None
            
            # Get metadata
            duration = 0
            title = "Unknown"
            performer = "Unknown"
            
            if hasattr(media, "duration"):
                duration = media.duration or 0
            if hasattr(media, "file_name"):
                title = media.file_name or "Unknown"
            if hasattr(media, "title"):
                title = media.title or title
            if hasattr(media, "performer"):
                performer = media.performer or performer
            
            return {
                "url": file_path,  # Local file path
                "title": title if title != "Unknown" else f"{performer} - {title}" if performer != "Unknown" else "Telegram Audio",
                "duration": duration,
                "thumbnail": None,
                "source": "telegram",
                "is_local": True,
            }
            
        except Exception as e:
            logger.error(f"Failed to extract Telegram audio: {e}")
            return None
    
    async def _download_media(self, media) -> Optional[str]:
        """Download media to local storage.
        
        Args:
            media: Pyrogram media object
            
        Returns:
            Local file path or None
        """
        try:
            if not bot_module.bot_client:
                logger.error("Bot client is not initialized for Telegram media download")
                return None

            file_name = f"tg_{media.file_unique_id}"
            if hasattr(media, 'file_name') and media.file_name:
                file_name = media.file_name
            
            file_path = os.path.join(self.download_dir, file_name)
            
            # Download using bot client
            downloaded = await bot_module.bot_client.download_media(
                media,
                file_name=file_path
            )
            
            return downloaded
            
        except Exception as e:
            logger.error(f"Download failed: {e}")
            return None


# Global handler
telegram_audio = TelegramAudioHandler()


async def extract_telegram_audio(message: Message) -> Optional[Dict[str, Any]]:
    """Extract audio from a Telegram message."""
    return await telegram_audio.extract_from_message(message)
