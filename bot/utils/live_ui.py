"""
Soul King Concert-Themed Live Now Playing UI with Real-Time Progress Tracking.
Features:
  - Live progress bar that updates every 2-3 seconds
  - Rich song metadata with artwork display
  - Comprehensive inline controls organized by category
  - User stats and queue info
  - Auto-cleanup of old messages
"""

import asyncio
import logging
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
import random
from pyrogram import Client
from pyrogram.enums import ParseMode
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message
from pyrogram.errors import MessageNotModified, FloodWait
from io import BytesIO

from bot.core.queue import queue_manager
from bot.utils.cache import cache
from bot.utils.formatters import format_duration, create_progress_bar
from bot.utils.soul_king_thumbnail import soul_king_thumbnail

logger = logging.getLogger(__name__)

# Soul King Stage Aesthetic - Quotes & Vibes
SOUL_KING_VIBES = {
    "playing": [
        "🎸 **The Soul King is ON STAGE!** YOHOHOHO! 🎵",
        "🎼 **Violin strings SINGING!** Feel the music flow! 💀",
        "🎭 **LIVE CONCERT** — Let this melody be eternal! ✨",
        "🎤 **The Soul King PERFORMS!** My bones vibrate with joy! 🦴",
        "🌟 **Standing ovation for this MASTERPIECE!** YOHOHOHO! 🎸",
    ],
    "paused": [
        "⏸ **Intermission!** The Soul King takes a breath... 💀",
        "🎭 **Stage goes dark...** Waiting for the encore! 🌙",
        "⏸ **Bow and Step Back** — The music sleeps! 🎼",
    ],
    "idle": [
        "🎭 **The stage awaits a performer...** Use /play to summon the Soul King! 🎸",
        "💀 **The concert hall is empty.** Bring music to life! 🎵",
    ]
}

SOURCE_BADGES = {
    "vk": ("🟦 VK Music", "#0077FF"),
    "deezer": ("🎧 Deezer", "#00C7F2"),
    "telegram": ("✈️ Telegram", "#0088CC"),
}


class SoulKingLiveUI:
    """
    Soul King themed live now playing UI with real-time progress updates.
    
    Features:
      - Live message updates every 2-3 seconds
      - Rich metadata display with song artwork
      - Organized inline controls (playback, queue, admin, info)
      - Auto-cleanup after track ends
      - Theater-style animations and Brook quotes
    """
    
    def __init__(self):
        self.live_messages: Dict[int, Dict[str, Any]] = {}  # chat_id -> {msg_id, task, update_ts, track_hash}
        self.update_tasks: Dict[int, asyncio.Task] = {}
        self.update_interval = 2.5  # seconds
    
    def _log_background_task_exception(self, task: asyncio.Task) -> None:
        """Log any uncaught exception from a background asyncio task."""
        try:
            exception = task.exception()
        except asyncio.CancelledError:
            return
        if exception:
            logger.error("[Live UI] Background live update session failed", exc_info=exception)
    
    def _random_vibe(self, state: str) -> str:
        """Get a random Soul King quote for the current state."""
        quotes = SOUL_KING_VIBES.get(state, SOUL_KING_VIBES["idle"])
        return random.choice(quotes)
    
    def _get_source_badge(self, source: str) -> str:
        """Get emoji badge for music source."""
        source_lower = (source or "unknown").lower()
        badge, _ = SOURCE_BADGES.get(source_lower, ("🎵 Music", "#1F2937"))
        return badge
    
    def _create_progress_display(self, position: int, duration: int, include_bar: bool = True) -> str:
        """Create visual progress display with bar and times."""
        if duration <= 0:
            return "⏱ `0:00 / 0:00`"
        
        pos_str = format_duration(position)
        dur_str = format_duration(duration)
        
        if not include_bar:
            return f"⏱ `{pos_str} / {dur_str}`"
        
        # Create a fancy progress bar
        bar_length = 18
        filled = int((position / duration) * bar_length)
        empty = bar_length - filled
        
        # Use gradient blocks for fancy effect
        if filled == 0:
            bar = "🔵" + "▯" * (bar_length - 1)
        elif filled >= bar_length:
            bar = "▰" * bar_length
        else:
            bar = "▰" * filled + "🔵" + "▯" * (empty - 1)
        
        percentage = int((position / duration) * 100)
        
        return f"{bar}\n`{pos_str}` ▶ `{dur_str}` **[{percentage}%]**"
    
    def _format_live_np_text(
        self,
        track: Dict[str, Any],
        position: int,
        status: str,
        queue_len: int,
        queue_pos: int = 0
    ) -> str:
        """
        Format rich now playing text with Soul King concert theme.
        
        Args:
            track: Current track dict with title, artist, duration, source, etc.
            position: Current playback position in seconds
            status: "playing", "paused", or "idle"
            queue_len: Total songs in queue
            queue_pos: Position in queue (0-indexed)
        """
        title = track.get("title", "Unknown Track")
        artist = track.get("artist") or track.get("uploader", "Unknown Artist")
        duration = track.get("duration", 0)
        source = track.get("source", "unknown")
        
        # Truncate long titles
        title = (title[:60] + "...") if len(title) > 60 else title
        artist = (artist[:50] + "...") if len(artist) > 50 else artist
        
        # Get source badge
        badge = self._get_source_badge(source)
        
        # Get current vibe/quote
        vibe = self._random_vibe(status)
        
        # Status indicator
        status_indicator = {
            "playing": "▶️ 🎵 LIVE PERFORMANCE 🎵",
            "paused": "⏸️ INTERMISSION ⏸️",
            "idle": "🎭 STAGE AWAITS 🎭",
        }.get(status, "▶️ SOUL KING FM")
        
        # Build the message
        lines = [
            "╔════════════════════════════════════╗",
            f"║  {status_indicator:<32}  ║",
            "╚════════════════════════════════════╝",
            "",
            f"{vibe}",
            "",
            "─ 🎸 NOW ON STAGE 🎸 ─",
            f"<b>{title}</b>",
            f"<i>by {artist}</i>",
            f"{badge}",
            "",
            "─ CONCERT PROGRESS ─",
        ]
        
        # Add progress bar
        if status == "playing" and duration > 0:
            progress_text = self._create_progress_display(position, duration, include_bar=True)
            lines.append(progress_text)
        else:
            dur_str = format_duration(duration) if duration > 0 else "0:00"
            lines.append(f"⏱ Duration: `{dur_str}`")
        
        lines.extend([
            "",
            "─ STAGE INFO ─",
            f"🎵 Queue: `{queue_len}` songs" + (f" • Position: `#{queue_pos + 1}`" if queue_len > 0 else ""),
            "",
        ])
        
        text = "\n".join(lines)
        return text
    
    def _create_live_controls(
        self,
        status: str,
        user_level: int,
        chat_id: int,
        track_id: Optional[int] = None,
        playback_state: dict = None
    ) -> InlineKeyboardMarkup:
        """
        Create organized inline controls with state-aware button rendering (Soul King concert layout).
        
        Layout (4 rows):
          1. [Play/Pause] [Skip] [Queue] [More]
          2. [Vol-] [Loop] [Shuffle] [Vol+]
          3. [Export Queue] [Stats] [Help]
          4. [Admin: Force Resume] [Stop]
        
        Args:
            status: Current playback status ("playing", "paused", "idle")
            user_level: Permission level (1=member, 3=admin, 5=sudo)
            chat_id: Target chat
            track_id: Optional track ID for API calls
            playback_state: Dict with {status, loop_mode, shuffle, volume} from cache
        """
        # Use provided state or construct from current status
        if not playback_state:
            playback_state = {"status": status}
        
        current_status = playback_state.get("status", status)
        current_loop = playback_state.get("loop_mode", "none")
        is_shuffled = playback_state.get("shuffle", False)
        
        buttons = []
        
        # Row 1: Primary Controls
        row1 = []
        
        # Play/Pause toggle with state indicator
        if current_status == "playing":
            # Pause button (active - blue)
            row1.append(InlineKeyboardButton("🔵 Pause", callback_data="pause"))
        elif current_status == "paused":
            # Resume button (active - green)
            row1.append(InlineKeyboardButton("🟢 Resume", callback_data="resume"))
        else:
            # Disabled: can't play/pause if idle (gray circle)
            row1.append(InlineKeyboardButton("⚪ Play", callback_data="noop"))
        
        # Skip (admin only; grayed if not playing)
        if user_level >= 3:
            if current_status in ["playing", "paused"]:
                row1.append(InlineKeyboardButton("🟠 Skip", callback_data="skip"))
            else:
                row1.append(InlineKeyboardButton("⚪ Skip", callback_data="noop"))
        
        # Queue view (always available)
        row1.append(InlineKeyboardButton("📋 Queue", callback_data="queue"))
        
        # More options
        row1.append(InlineKeyboardButton("⚙️ More", callback_data="more_options"))
        
        buttons.append(row1)
        
        # Row 2: Volume & Effects (admin)
        if user_level >= 3:
            # Use colored emoji for active effects
            loop_emoji = {"none": "🔄", "track": "🔂", "queue": "🔁"}[current_loop]
            shuffle_emoji = "🔀" if not is_shuffled else "✅"
            
            row2 = [
                InlineKeyboardButton("🔊", callback_data="vol_up"),
                InlineKeyboardButton("🔉", callback_data="vol_down"),
                InlineKeyboardButton(f"{loop_emoji} Loop", callback_data="loop"),
                InlineKeyboardButton(f"{shuffle_emoji} Shuffle", callback_data="shuffle"),
            ]
            buttons.append(row2)
        
        # Row 3: Info & Utilities (always available)
        row3 = [
            InlineKeyboardButton("📊 Stats", callback_data="status_check"),
            InlineKeyboardButton("❓ Help", callback_data="help_menu"),
        ]
        buttons.append(row3)
        
        # Row 4: Emergency Admin (admin only; grayed if already playing)
        if user_level >= 3:
            row4 = []
            # Force Resume (grayed if playing)
            if current_status != "playing":
                row4.append(InlineKeyboardButton("🔄 Resume", callback_data="forceresume"))
            else:
                row4.append(InlineKeyboardButton("⚪ Resume", callback_data="noop"))
            
            row4.append(InlineKeyboardButton("🔴 Stop", callback_data="stop"))
            buttons.append(row4)
        
        return InlineKeyboardMarkup(buttons)
    
    async def start_live_update_session(
        self,
        client: Client,
        chat_id: int,
        message: Message,
        user_level: int = 1
    ) -> None:
        """
        Start a live update session for the now playing message.
        
        Args:
            client: Pyrogram client
            chat_id: Target chat ID
            message: Initial message object
            user_level: Permission level of the user who started it
        """
        msg_id = message.id
        logger.info(f"[Live UI] Started live session for chat {chat_id}, msg {msg_id}")
        
        # Cancel any existing update task for this chat
        if chat_id in self.update_tasks:
            task = self.update_tasks[chat_id]
            if not task.done():
                task.cancel()
        
        # Store session info
        self.live_messages[chat_id] = {
            "msg_id": msg_id,
            "start_time": datetime.now(),
            "last_update": datetime.now(),
            "user_level": user_level,
            "last_position": 0,
            "last_jamendo_track_id": None,
        }
        
        # Start update loop
        task = asyncio.create_task(self._live_update_loop(client, chat_id, user_level))
        self.update_tasks[chat_id] = task
        
        try:
            await task
        except asyncio.CancelledError:
            logger.debug(f"[Live UI] Update loop cancelled for chat {chat_id}")
        except Exception as e:
            logger.error(f"[Live UI] Update loop error for chat {chat_id}: {e}")
        finally:
            # Cleanup
            if chat_id in self.update_tasks:
                del self.update_tasks[chat_id]
            if chat_id in self.live_messages:
                del self.live_messages[chat_id]
    
    async def _live_update_loop(self, client: Client, chat_id: int, user_level: int) -> None:
        """Background task that updates the now playing message every 2-3 seconds."""
        max_idle_time = 300  # Stop updating after 5 minutes of paused/idle
        last_active_time = datetime.now()
        
        while chat_id in self.update_tasks:
            await asyncio.sleep(self.update_interval)
            
            try:
                session = self.live_messages.get(chat_id)
                if not session:
                    break
                
                msg_id = session["msg_id"]
                
                # Get current playback state
                current = await queue_manager.get_current(chat_id)
                status = await queue_manager.get_status(chat_id)
                position = await queue_manager.get_position(chat_id)
                queue_len = await queue_manager.get_queue_length(chat_id)
                queue = await queue_manager.get_queue(chat_id)
                queue_pos = 0
                
                # Check if playback changed
                if not current:
                    # No track playing - stop updating
                    logger.info(f"[Live UI] No track in chat {chat_id}, stopping updates")
                    break
                
                # Track activity for idle timeout
                if status == "playing":
                    last_active_time = datetime.now()
                elif (datetime.now() - last_active_time).total_seconds() > max_idle_time:
                    logger.info(f"[Live UI] Chat {chat_id} idle too long, stopping updates")
                    break
                
                # Calculate queue position
                for i, track in enumerate(queue):
                    if track.get("id") == current.get("id"):
                        queue_pos = i
                        break
                
                # Format new message text
                new_text = self._format_live_np_text(
                    current, position, status, queue_len, queue_pos
                )
                
                # Create fresh controls based on current permission and playback state
                from bot.utils.cache import cache
                playback_state = await cache.get_playback_state(chat_id)
                controls = self._create_live_controls(status, user_level, chat_id, playback_state=playback_state)
                
                # Update message
                try:
                    await client.edit_message_text(
                        chat_id=chat_id,
                        message_id=msg_id,
                        text=new_text,
                        reply_markup=controls,
                        parse_mode=ParseMode.HTML
                    )
                    session["last_update"] = datetime.now()
                    session["last_position"] = position
                
                except MessageNotModified:
                    # Text didn't change, skip update
                    pass
                except FloodWait as e:
                    logger.warning(f"[Live UI] FloodWait {e.value}s for chat {chat_id}")
                    await asyncio.sleep(e.value + 1)
                except Exception as e:
                    logger.warning(f"[Live UI] Failed to update message in chat {chat_id}: {e}")
                    # Don't break, keep trying
            
            except Exception as e:
                logger.error(f"[Live UI] Unexpected error in update loop: {e}")
                await asyncio.sleep(5)
    
    async def send_live_np_card(
        self,
        client: Client,
        chat_id: int,
        track: Dict[str, Any],
        message: Optional[Message] = None,
        user_level: int = 1,
        with_photo: bool = True
    ) -> Optional[Message]:
        """
        Send a new live now playing card with optional artwork.
        
        Args:
            client: Pyrogram client
            chat_id: Target chat
            track: Track information dict
            message: Optional message to reply to
            user_level: Permission level
            with_photo: Whether to include generated thumbnail
            
        Returns:
            The sent message object
        """
        try:
            # Format the card
            position = 0
            status = await queue_manager.get_status(chat_id)
            queue_len = await queue_manager.get_queue_length(chat_id)
            
            text = self._format_live_np_text(track, position, status, queue_len)
            
            # Get cached playback state for state-aware button rendering
            from bot.utils.cache import cache
            playback_state = await cache.get_playback_state(chat_id)
            if not playback_state:
                playback_state = {"status": status}
            
            controls = self._create_live_controls(status, user_level, chat_id, playback_state=playback_state)
            
            # Try to generate thumbnail if requested
            thumb_data = None
            if with_photo and track.get("thumb"):
                try:
                    thumb_data = await soul_king_thumbnail.generate_live_np_card(
                        title=track.get("title", ""),
                        artist=track.get("artist") or track.get("uploader", ""),
                        duration=track.get("duration", 0),
                        position=0,
                        thumbnail_url=track.get("thumb"),
                        source=track.get("source", "unknown")
                    )
                except Exception as e:
                    logger.debug(f"[Live UI] Could not generate Soul King thumbnail: {e}")
            
            # Send the message
            if thumb_data:
                sent_msg = await client.send_photo(
                    chat_id=chat_id,
                    photo=thumb_data,
                    caption=text,
                    reply_markup=controls,
                    parse_mode=ParseMode.HTML,
                    reply_to_message_id=message.id if message else None
                )
            else:
                sent_msg = await client.send_message(
                    chat_id=chat_id,
                    text=text,
                    reply_markup=controls,
                    parse_mode=ParseMode.HTML,
                    reply_to_message_id=message.id if message else None
                )
            
            # Start live update session in the background so send_live_np_card returns immediately
            task = asyncio.create_task(
                self.start_live_update_session(client, chat_id, sent_msg, user_level)
            )
            task.add_done_callback(self._log_background_task_exception)
            
            return sent_msg
        
        except Exception as e:
            logger.error(f"[Live UI] Failed to send live NP card: {e}")
            return None
    
    async def stop_live_session(self, chat_id: int) -> None:
        """Stop the live update session for a chat."""
        if chat_id in self.update_tasks:
            task = self.update_tasks[chat_id]
            if not task.done():
                task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


# Global instance
soul_king_ui = SoulKingLiveUI()

