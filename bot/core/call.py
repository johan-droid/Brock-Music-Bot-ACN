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
import random
from typing import Dict, Optional, Callable, List, Any

from pytgcalls import PyTgCalls
from pytgcalls.types import MediaStream
from pytgcalls.exceptions import (
    NoActiveGroupCall,
    NotInCallError,
)
from config import config

logger = logging.getLogger(__name__)

_QUALITY_MIN_BITRATE = {
    "standard": 128,
    "high": 192,
    "premium": 256,
    "lossless": 320,
}

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
        # chat-scoped lock to avoid concurrent join/stream race in the same group
        self.chat_locks: Dict[int, asyncio.Lock] = {}
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

    async def _start_voice_chat(self, chat_id: int, userbot_idx: int) -> bool:
        """Attempt to create/start a voice chat via userbot raw API."""
        if not getattr(config, "AUTO_START_VC", True):
            return False

        client = self.userbots[userbot_idx]
        try:
            from pyrogram.raw.functions.phone import CreateGroupCall

            peer = await client.resolve_peer(chat_id)
            title = (getattr(config, "AUTO_START_VC_TITLE", "Music Bot Live") or "Music Bot Live").strip()
            await client.invoke(
                CreateGroupCall(
                    peer=peer,
                    random_id=random.randint(1, 2_147_483_647),
                    title=title,
                )
            )
            logger.info(f"Auto-started voice chat in {chat_id}")
            return True
        except Exception as exc:
            err = str(exc).lower()
            if "groupcall already" in err or "already" in err:
                logger.info(f"Voice chat already active in {chat_id}, continuing")
                return True
            logger.warning(f"Auto-start voice chat failed in {chat_id}: {exc}")
            return False

    def _chat_lock(self, chat_id: int) -> asyncio.Lock:
        """Return a per-chat lock to serialize VC operations for that group."""
        lock = self.chat_locks.get(chat_id)
        if lock is None:
            lock = asyncio.Lock()
            self.chat_locks[chat_id] = lock
        return lock

    def _current_loads(self) -> Dict[int, int]:
        """Return active chat counts per userbot index."""
        loads = {idx: 0 for idx in self.calls.keys()}
        for idx in self.active_chats.values():
            loads[idx] = loads.get(idx, 0) + 1
        return loads

    def _candidate_userbots(self, preferred_idx: Optional[int] = None) -> List[int]:
        """Build userbot candidates sorted by current load (least loaded first)."""
        loads = self._current_loads()
        candidates = sorted(self.calls.keys(), key=lambda idx: (loads.get(idx, 0), idx))

        # Apply per-assistant load cap if configured (>0).
        max_chats = int(getattr(config, "ASSISTANT_MAX_ACTIVE_CHATS", 0) or 0)
        if max_chats > 0:
            under_limit = [idx for idx in candidates if loads.get(idx, 0) < max_chats]
            if under_limit:
                candidates = under_limit

        # If caller explicitly requested an assistant, prioritize it when available.
        if preferred_idx is not None and preferred_idx in candidates:
            candidates.remove(preferred_idx)
            candidates.insert(0, preferred_idx)

        return candidates

    def _select_assistant_for_chat(
        self,
        chat_id: int,
        preferred_idx: Optional[int] = None,
        force_reassign: bool = False,
    ) -> int:
        """
        Choose userbot for this chat:
        1) Sticky assignment while active (prevents cross-assistant stream switches)
        2) Least-loaded candidate for new chat joins
        """
        sticky_idx = self.active_chats.get(chat_id)
        if not force_reassign and sticky_idx in self.calls:
            return sticky_idx

        candidates = self._candidate_userbots(preferred_idx=preferred_idx)
        if not candidates:
            raise RuntimeError("No userbot call instances are available")
        return candidates[0]

    def get_balancer_snapshot(self) -> Dict[str, Any]:
        """Expose load-balancer state for /vcdebug and diagnostics."""
        loads = self._current_loads()
        return {
            "total_userbots": len(self.calls),
            "active_chats": len(self.active_chats),
            "loads": {str(idx): loads.get(idx, 0) for idx in sorted(self.calls.keys())},
            "assignments": {str(chat_id): idx for chat_id, idx in self.active_chats.items()},
        }

    # ─── Playback control ─────────────────────────────────────────────────────

    # ─── Playback control ─────────────────────────────────────────────────────
    
    async def play(
        self,
        chat_id: int,
        stream_url: str,
        video: bool = False,
        userbot_idx: Optional[int] = None,
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
        async with self._chat_lock(chat_id):
            selected_idx = self._select_assistant_for_chat(
                chat_id,
                preferred_idx=userbot_idx,
                force_reassign=force_join,
            )
            call = self.calls.get(selected_idx)
            if not call:
                raise RuntimeError(f"No call instance for userbot {selected_idx}")

            stream = self._build_stream(stream_url, video=video, seek=seek, headers=headers)
            timeout_s = max(5, int(getattr(config, "VC_PLAY_TIMEOUT", 20) or 20))

            # Keep stream changes sticky to the assistant that owns this chat.
            is_active = chat_id in self.active_chats and not force_join

            try:
                if is_active:
                    active_idx = self.active_chats.get(chat_id, selected_idx)
                    call = self.calls.get(active_idx)
                    if not call:
                        raise RuntimeError(f"No call instance for active userbot {active_idx}")
                    try:
                        logger.info(
                            f"Attempting stream change in {chat_id} via userbot #{active_idx + 1} "
                            f"(timeout={timeout_s}s)"
                        )
                        await asyncio.wait_for(call.change_stream(chat_id, stream), timeout=timeout_s)
                        logger.info(f"Changed stream in {chat_id}")
                        return
                    except NotInCallError:
                        # Inconsistent state, fallback to play()
                        logger.warning(f"Inconsistent call state for {chat_id}, rejoining...")
                        selected_idx = active_idx
                    except asyncio.TimeoutError:
                        raise RuntimeError(
                            "Voice Chat stream change timed out. Please ensure the assistant is in the VC and try /play again."
                        )

                # For fresh join, try least-loaded candidates until one succeeds.
                join_candidates = [selected_idx] + [
                    idx for idx in self._candidate_userbots() if idx != selected_idx
                ]

                last_exc: Optional[Exception] = None
                for idx in join_candidates:
                    call = self.calls.get(idx)
                    if not call:
                        continue

                    try:
                        # Peer pre-cache for selected assistant.
                        try:
                            client = self.userbots[idx]
                            await client.get_chat(chat_id)
                        except Exception as e:
                            logger.debug(f"Pre-play get_chat on userbot #{idx + 1} failed: {e}")

                        await self._start_voice_chat(chat_id, idx)
                        logger.info(
                            f"Attempting VC playback join in {chat_id} via userbot #{idx + 1} "
                            f"(timeout={timeout_s}s)"
                        )
                        await asyncio.wait_for(call.play(chat_id, stream), timeout=timeout_s)
                        self.active_chats[chat_id] = idx
                        logger.info(f"Started playback in {chat_id} (video={video}) via userbot #{idx + 1}")
                        return
                    except Exception as join_exc:
                        last_exc = join_exc
                        logger.warning(
                            f"Join attempt failed for chat {chat_id} on userbot #{idx + 1}: {join_exc}"
                        )
                        continue

                if last_exc is not None:
                    raise last_exc
                raise RuntimeError("No available userbot could join the voice chat")

            except Exception as exc:
                # Handle 'Already Joined' scenario which can happen with PyTgCalls
                exc_str = str(exc).lower()

                if isinstance(exc, asyncio.TimeoutError):
                    raise RuntimeError(
                        "Voice Chat join/play timed out. Verify an active VC exists and the assistant has permission to speak."
                    )

                if "already joined" in exc_str or "already_joined" in exc_str:
                    active_idx = self.active_chats.get(chat_id, selected_idx)
                    call = self.calls.get(active_idx)
                    if not call:
                        raise RuntimeError(f"No call instance for active userbot {active_idx}")
                    try:
                        await asyncio.wait_for(call.change_stream(chat_id, stream), timeout=timeout_s)
                    except asyncio.TimeoutError:
                        raise RuntimeError(
                            "Voice Chat stream switch timed out. Please restart VC and try again."
                        )
                    self.active_chats[chat_id] = active_idx
                    return

                if "peer id invalid" in exc_str or "id not found" in exc_str or "peer_id_invalid" in exc_str:
                    # Try to diagnose member visibility for the selected assistant.
                    note = ""
                    try:
                        userbot = self.userbots[selected_idx]
                        member = await userbot.get_chat_member(chat_id, userbot.me.id)
                        if member and member.status in ["member", "administrator", "creator"]:
                            note = "Your assistant account is present in the group, but may not have permission to access voice chat or the group is a channel-type chat."
                        else:
                            note = "Your assistant account is not in the group. Add it as member/admin and retry."
                    except Exception as e:
                        logger.debug(f"Peer-id check failed: {e}")
                        note = "Your assistant account may not be in the group, or there may be chat privacy restrictions."

                    raise RuntimeError(
                        "❌ PEER ERROR: The Assistant account cannot see this chat!\n"
                        "Please make sure you have added your Assistant account (@Justahuman6996) "
                        "to this group as a Member or Admin, then try again.\n"
                        f"Details: {note}"
                    )

                if "bot_method_invalid" in exc_str or "bot method invalid" in exc_str:
                    raise RuntimeError(
                        "ERROR: Your Userbot Session is a BOT account! "
                        "PyTgCalls requires a REAL USER account (Phone Number) to stream music. "
                        "Please run 'python generate_session.py' and log in with a phone number."
                    )

                if "no active group call" in exc_str or isinstance(exc, NoActiveGroupCall):
                    started = await self._start_voice_chat(chat_id, selected_idx)
                    if started:
                        try:
                            await asyncio.sleep(1.2)
                            logger.info(f"Retrying VC playback join in {chat_id} after auto-start")
                            call = self.calls.get(selected_idx)
                            if not call:
                                raise RuntimeError(f"No call instance for userbot {selected_idx}")
                            await asyncio.wait_for(call.play(chat_id, stream), timeout=timeout_s)
                            self.active_chats[chat_id] = selected_idx
                            logger.info(f"Started playback in {chat_id} after auto VC start (video={video})")
                            return
                        except Exception as retry_exc:
                            logger.error(f"VC retry failed in {chat_id}: {retry_exc}")

                    raise RuntimeError(
                        "No active Voice Chat was found and auto-start failed. "
                        "Please grant the assistant 'Manage Video Chats' permission or start VC manually, then /play again."
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

        # Use configurable bitrate (bits/s) with a quality-tier floor.
        quality_name = (getattr(config, "AUDIO_QUALITY", "high") or "high").lower()
        min_bitrate = _QUALITY_MIN_BITRATE.get(quality_name, 192)
        bitrate_kbps = max(int(getattr(config, "AUDIO_BITRATE", 192) or 192), min_bitrate)
        bitrate_kbps = min(max(bitrate_kbps, 128), 320)

        audio_cfg = AudioParameters(
            bitrate=bitrate_kbps * 1000,
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
        ffmpeg_params = "-nostdin "
        if not video:
            ffmpeg_params += "-vn "
        ffmpeg_params += "-reconnect 1 -reconnect_at_eof 1 -reconnect_streamed 1 -reconnect_delay_max 5 "
        
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
