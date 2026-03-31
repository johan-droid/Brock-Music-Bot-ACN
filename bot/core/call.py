"""
py-tgcalls call manager — production-grade Telegram Voice Chat streaming.

CRITICAL ARCHITECTURAL NOTE:
py-tgcalls v2.x + NTgCalls handles ALL FFmpeg transcoding internally.
We pass the raw stream URL (from yt-dlp) directly to MediaStream().
NTgCalls runs its own embedded FFmpeg pipeline to decode → Opus → Telegram VC.
DO NOT run a separate FFmpeg subprocess — it is redundant and causes instability.
"""

import asyncio
import logging
from typing import Dict, Optional, Callable, List

from pytgcalls import PyTgCalls
from pytgcalls.types import MediaStream
from pytgcalls.exceptions import (
    NoActiveGroupCall,
    NotInCallError,
)
from config import config

logger = logging.getLogger(__name__)

# Global instance — set by init_calls()
call_manager: Optional["CallManager"] = None


class CallManager:
    """Manages Telegram Voice Chat connections and audio streaming."""

    def __init__(self, userbot_clients: list):
        self.userbots = userbot_clients
        # userbot_idx (int) → PyTgCalls instance
        self.calls: Dict[int, PyTgCalls] = {}
        # chat_id (int) → userbot_idx (int)
        self.active_chats: Dict[int, int] = {}
        # External handlers called when a stream ends
        self.on_stream_end_handlers: List[Callable] = []

    # ─── Initialization ───────────────────────────────────────────────────────

    async def init(self):
        """Initialize py-tgcalls for each userbot and register event handlers."""
        for idx, userbot in enumerate(self.userbots):
            call = PyTgCalls(userbot)

            # Register all update handlers BEFORE calling .start()
            @call.on_update()
            async def _update_handler(client, update, _idx=idx):
                await self._dispatch_update(_idx, update)

            await call.start()
            self.calls[idx] = call
            logger.info(f"py-tgcalls initialized for userbot {idx + 1}")

    async def _dispatch_update(self, userbot_idx: int, update):
        """Route py-tgcalls updates to the correct internal handler."""
        from pytgcalls.types.stream import StreamEnded, StreamAudioEnded, StreamVideoEnded
        from pytgcalls.types import Update

        chat_id = getattr(update, "chat_id", None)
        if chat_id is None:
            return

        if isinstance(update, (StreamEnded, StreamAudioEnded, StreamVideoEnded)):
            logger.info(f"Stream ended in chat {chat_id} (userbot {userbot_idx + 1})")
            await self._on_stream_end(chat_id)

        elif hasattr(update, "__class__") and "KickedFromGroupCall" in type(update).__name__:
            logger.warning(f"Kicked from VC in chat {chat_id}")
            await self._on_kicked(chat_id)

        elif hasattr(update, "__class__") and "ClosedVoiceChat" in type(update).__name__:
            logger.info(f"Voice chat closed in chat {chat_id}")
            await self._on_closed(chat_id)

        elif hasattr(update, "__class__") and "LeftCall" in type(update).__name__:
            logger.info(f"Left VC in chat {chat_id}")
            self.active_chats.pop(chat_id, None)

    # ─── Playback control ─────────────────────────────────────────────────────

    # ─── Playback control ─────────────────────────────────────────────────────
    
    async def play(
        self,
        chat_id: int,
        stream_url: str,
        video: bool = False,
        userbot_idx: int = 0,
        seek: Optional[int] = None,
        force_join: bool = False,
        headers: Optional[Dict[str, str]] = None,
    ) -> None:
        """
        Start playback in a chat. Handles both initial join and stream switches.
        
        Args:
            chat_id:     Telegram group chat ID
            stream_url:  Audio/Video source URL
            video:       True if video should be enabled
            userbot_idx: Which userbot to use (default 0)
            seek:        Optional skip to X seconds
            force_join:  Always call .play instead of .change_stream
        """
        call = self.calls.get(userbot_idx)
        if not call:
            raise RuntimeError(f"No call instance for userbot {userbot_idx}")

        stream = self._build_stream(stream_url, video=video, seek=seek, headers=headers)
        
        # Check if we're already active in this chat
        is_active = chat_id in self.active_chats and not force_join
        
        try:
            if is_active:
                try:
                    await call.change_stream(chat_id, stream)
                    logger.info(f"Changed stream in {chat_id}")
                    return
                except NotInCallError:
                    # Inconsistent state, fallback to play()
                    logger.warning(f"Inconsistent call state for {chat_id}, rejoining...")
            
            # Peer Resolution Pre-check:
            # Pyrogram clients need to "see" a chat (be in their SQLite cache) before 
            # PyTgCalls can resolve the peer and join. We force a get_chat() here.
            try:
                # userbot_idx is passed in self.play() arguments
                client = self.userbots[userbot_idx]
                await client.get_chat(chat_id)
            except Exception as e:
                logger.debug(f"Pre-play get_chat on userbot failed: {e}")
                # We don't raise here yet; call.play might still work or give a better error 
            
            await call.play(chat_id, stream)
            self.active_chats[chat_id] = userbot_idx
            logger.info(f"Started playback in {chat_id} (video={video})")

        except Exception as exc:
            # Handle 'Already Joined' scenario which can happen with PyTgCalls
            exc_str = str(exc).lower()
            
            if "already joined" in exc_str or "already_joined" in exc_str:
                await call.change_stream(chat_id, stream)
                self.active_chats[chat_id] = userbot_idx
                return

            if "peer id invalid" in exc_str or "id not found" in exc_str or "peer_id_invalid" in exc_str:
                raise RuntimeError(
                    "❌ PEER ERROR: The Assistant account cannot see this chat!\n"
                    "Please make sure you have added your Assistant account (@Justahuman6996) "
                    "to this group as a Member or Admin, then try again."
                )

            if "bot_method_invalid" in exc_str or "bot method invalid" in exc_str:
                 raise RuntimeError(
                    "ERROR: Your Userbot Session is a BOT account! "
                    "PyTgCalls requires a REAL USER account (Phone Number) to stream music. "
                    "Please run 'python generate_session.py' and log in with a phone number."
                )

            if "no active group call" in exc_str or isinstance(exc, NoActiveGroupCall):
                raise RuntimeError(
                    "No Voice Chat is active in this group! "
                    "Please start a Voice Chat first, then use /play again."
                )
            
            logger.error(f"Playback failed in {chat_id}: {exc}")
            raise

    async def join_call(self, *args, **kwargs):
        """Deprecated: Use .play() instead."""
        return await self.play(*args, **kwargs)

    async def change_stream(self, *args, **kwargs):
        """Deprecated: Use .play() instead."""
        return await self.play(*args, **kwargs)

    async def pause(self, chat_id: int) -> None:
        call = self._call_for(chat_id)
        if call:
            try:
                await call.pause(chat_id)
                logger.info(f"Paused in chat {chat_id}")
            except Exception as exc:
                logger.warning(f"Pause error: {exc}")

    async def resume(self, chat_id: int) -> None:
        call = self._call_for(chat_id)
        if call:
            try:
                await call.resume(chat_id)
                logger.info(f"Resumed in chat {chat_id}")
            except Exception as exc:
                logger.warning(f"Resume error: {exc}")

    async def leave_call(self, chat_id: int) -> None:
        userbot_idx = self.active_chats.pop(chat_id, None)
        if userbot_idx is None:
            return
        call = self.calls.get(userbot_idx)
        if call:
            try:
                await call.leave_call(chat_id)
                logger.info(f"Left VC in chat {chat_id}")
            except Exception as exc:
                logger.warning(f"Leave call error: {exc}")

    async def set_volume(self, chat_id: int, volume: int) -> None:
        call = self._call_for(chat_id)
        if call:
            try:
                vol = max(1, min(200, volume))
                await call.change_volume_call(chat_id, vol)
                logger.info(f"Volume → {vol} in chat {chat_id}")
            except Exception as exc:
                logger.warning(f"Volume change error: {exc}")

    async def mute(self, chat_id: int) -> None:
        call = self._call_for(chat_id)
        if call:
            try:
                await call.mute(chat_id)
            except Exception:
                pass

    async def unmute(self, chat_id: int) -> None:
        call = self._call_for(chat_id)
        if call:
            try:
                await call.unmute(chat_id)
            except Exception:
                pass

    # ─── Event handlers ───────────────────────────────────────────────────────

    async def _on_stream_end(self, chat_id: int) -> None:
        """Triggered when a track finishes. Fires all registered handlers."""
        for handler in self.on_stream_end_handlers:
            try:
                await handler(chat_id)
            except Exception as exc:
                logger.error(f"Stream end handler error: {exc}")

    async def _on_kicked(self, chat_id: int) -> None:
        """Bot was kicked from VC — clean up all state."""
        self.active_chats.pop(chat_id, None)
        try:
            from bot.core.queue import queue_manager
            await queue_manager.clear_queue(chat_id)
        except Exception:
            pass

    async def _on_closed(self, chat_id: int) -> None:
        """VC was closed by a group admin."""
        self.active_chats.pop(chat_id, None)
        try:
            from bot.core.queue import queue_manager
            await queue_manager.set_status(chat_id, "idle")
        except Exception:
            pass

    # ─── Helpers ──────────────────────────────────────────────────────────────

    def _call_for(self, chat_id: int) -> Optional[PyTgCalls]:
        """Return the PyTgCalls instance for a chat, or None."""
        idx = self.active_chats.get(chat_id)
        if idx is not None:
            return self.calls.get(idx)
        return None

    @staticmethod
    def _build_stream(
        stream_url: str, 
        video: bool = False, 
        seek: Optional[int] = None,
        headers: Optional[Dict[str, str]] = None
    ) -> MediaStream:
        """
        Build a MediaStream for py-tgcalls using config parameters.
        """
        from pytgcalls.types.raw.audio_parameters import AudioParameters
        from pytgcalls.types.raw.video_parameters import VideoParameters

        # Use configurable bitrate (bits/s)
        audio_cfg = AudioParameters(
            bitrate=config.AUDIO_BITRATE * 1000,
        )

        video_flags = MediaStream.Flags.IGNORE
        video_cfg = None
        
        if video:
            # For video, we use a higher bitrate if possible
            video_cfg = VideoParameters(
                bitrate=2_000_000,  # 2 Mbps for decent 720p/1080p
            )
            video_flags = MediaStream.Flags.AUTO_DETECT

        # FFmpeg Input Options: placed before the input URL
        ffmpeg_params = "-reconnect 1 -reconnect_at_eof 1 -reconnect_streamed 1 -reconnect_delay_max 5 "
        
        if headers:
            ua = headers.get("User-Agent")
            if ua:
                ffmpeg_params += f'-user_agent "{ua}" '
            referer = headers.get("Referer")
            if referer:
                ffmpeg_params += f'-referer "{referer}" '

        if seek and seek > 0:
            ffmpeg_params += f"-ss {seek} "

        kwargs = {
            "media_path": stream_url,
            "audio_parameters": audio_cfg,
            "video_flags": video_flags,
            "ffmpeg_parameters": ffmpeg_params.strip() if ffmpeg_params else None,
        }
        if video_cfg:
            kwargs["video_parameters"] = video_cfg
            
        return MediaStream(**kwargs)

    def on_stream_end(self, func: Callable) -> Callable:
        """Decorator to register a stream-end callback."""
        self.on_stream_end_handlers.append(func)
        return func


# ─── Initialization helper ────────────────────────────────────────────────────

async def init_calls(userbot_clients: list) -> None:
    """Create and start the global CallManager."""
    global call_manager
    call_manager = CallManager(userbot_clients)
    await call_manager.init()
