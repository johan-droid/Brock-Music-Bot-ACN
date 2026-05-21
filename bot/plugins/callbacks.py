"""Callback query handlers for inline buttons."""

import logging
from typing import Optional
from pyrogram.client import Client
from pyrogram.enums import ParseMode
from pyrogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from bot.utils.permissions import get_permission_level
from bot.core.queue import queue_manager
from bot.core import call
from bot.utils.progress_tracker import progress_tracker
from bot.utils.cache import cache
from bot.core import bot as bot_module
from config import config
import asyncio
import time
from bot.utils.metrics import metrics_collector, CallbackMetrics


def _get_call_manager():
    if call.call_manager is None:
        raise RuntimeError("Call manager is not initialized")
    return call.call_manager

logger = logging.getLogger(__name__)


# ── Metrics tracking decorator ───────────────────────────────────────────────

def track_callback_latency(action_name: str):
    """Decorator to track callback execution latency and cache behavior.
    
    Args:
        action_name: Name of the callback action (e.g., "pause", "queue")
    """
    def decorator(func):
        async def wrapper(*args, **kwargs):
            start_time = time.time()
            callback = args[1] if len(args) > 1 else None
            chat_id = args[2] if len(args) > 2 else None
            
            try:
                result = await func(*args, **kwargs)
                return result
            finally:
                # Record metrics after callback completes
                elapsed_ms = (time.time() - start_time) * 1000
                
                if callback and chat_id:
                    # Check if this was a cache operation (look for cache_hit info in globals)
                    cache_hit = getattr(callback, '_metrics_cache_hit', None)
                    db_time = getattr(callback, '_metrics_db_time_ms', 0.0)
                    
                    metric = CallbackMetrics(
                        action=action_name,
                        chat_id=chat_id,
                        timestamp=start_time,
                        response_time_ms=elapsed_ms,
                        cache_hit=cache_hit,
                        db_lookup_time_ms=db_time,
                        background_task_created=True,  # Most of our handlers create background tasks
                    )
                    metrics_collector.record_callback(metric)
        
        return wrapper
    return decorator


# ── Optimistic state helpers ─────────────────────────────────────────────────

async def _verify_state_async(chat_id: int, expected_status: Optional[str] = None, 
                               action_fn=None, action_args=None) -> None:
    """Background task: verify state and perform action without blocking callback response."""
    try:
        if expected_status:
            actual_status = await queue_manager.get_status(chat_id)
            if actual_status != expected_status:
                logger.warning(f"State mismatch in {chat_id}: expected {expected_status}, got {actual_status}")
                # Refresh cache with actual state
                await cache.cache_playback_state(chat_id, status=actual_status)
                return
        
        # Execute action if provided
        if action_fn:
            args = action_args or {}
            await action_fn(**args)
    except Exception as e:
        logger.error(f"Async state verification failed: {e}")


async def handle_noop(client: Client, callback: CallbackQuery, chat_id: int):
    """Handle no-op (disabled button). Informs user the button is disabled in current state."""
    # Get current state to provide helpful message
    cached_state = await cache.get_playback_state(chat_id)
    current_status = cached_state.get("status", "idle")
    
    if current_status == "idle":
        msg = "💀 The stage is empty! Use /play to start the music, Yohoho!"
    elif current_status == "paused":
        msg = "⏸ The music is paused. Click 🟢 Resume to continue!"
    else:
        msg = "This action is not available right now."
    
    await callback.answer(msg, show_alert=False)


@Client.on_callback_query()  # type: ignore[call-arg]
async def callback_handler(client: Client, callback: CallbackQuery):
    """Handle all callback queries."""
    message = callback.message
    if message is None:
        await callback.answer("Unable to process callback: missing message context.", show_alert=True)
        return

    user_id = callback.from_user.id
    chat_id = message.chat.id
    data = callback.data
    if isinstance(data, (bytes, bytearray, memoryview)):
        data = bytes(data).decode("utf-8", errors="ignore")
    elif data is None:
        data = ""

    # Enforce group binder at callback level
    if config.BOUND_GROUP_ID is not None and chat_id != config.BOUND_GROUP_ID:
        await callback.answer(
            "⛔ This bot is bound to a different group and cannot be used here.",
            show_alert=True
        )
        return

    # Check permissions
    level = await get_permission_level(user_id, chat_id)

    # Handle play conflict resolution (new format "ps:N", legacy "play_select_N")
    if data.startswith("ps:") or data.startswith("play_select_"):
        if level < 1:
            await callback.answer("⛔ You are banned from using this bot!", show_alert=True)
            return
        await handle_play_select(client, callback, chat_id, user_id, data)
        return

    if data.startswith("pc:") or data == "play_cancel":
        if level < 1:
            await callback.answer("⛔ You are banned from using this bot!", show_alert=True)
            return
        await handle_play_cancel(client, callback, chat_id, user_id, data)
        return

    # Map callbacks to handlers
    handlers = {
        "pause": handle_pause,
        "resume": handle_resume,
        "skip": handle_skip,
        "stop": handle_stop,
        "queue": handle_queue,
        "shuffle": handle_shuffle,
        "clearqueue": handle_clearqueue,
        "loop": handle_loop,
        "vol_up": handle_vol_up,
        "vol_down": handle_vol_down,
        "more_options": handle_more_options,
        "replay": handle_replay,
        "previous": handle_previous,
        "export_queue": handle_export_queue,
        "forceresume": handle_forceresume,
        "brok_info": handle_brok_info,
        "help": handle_help_info,
        "help_menu": handle_help_info,
        "status_check": handle_status_check,
        "noop": handle_noop,  # No-op for disabled buttons
    }

    handler = handlers.get(data)
    if handler:
        # Match callback authority with command authority (skip for noop)
        if data == "noop":
            await handler(client, callback, chat_id)
            return
        
        public_actions = {"help", "help_menu", "status_check", "brok_info", "noop"}
        admin_actions = {
            "skip", "stop", "shuffle", "clearqueue", "loop", "forceresume",
            "vol_up", "vol_down", "replay", "previous",
        }
        member_actions = {"pause", "resume", "queue", "more_options", "export_queue"}

        if data not in public_actions and level < 1:
            await callback.answer("⛔ You are banned from using this bot!", show_alert=True)
            return

        if data in admin_actions and level < 3:
            await callback.answer("⛔ Admins only for this action.", show_alert=True)
            return

        if data in member_actions and level < 1:
            await callback.answer("⛔ You are banned from using this bot!", show_alert=True)
            return

        await handler(client, callback, chat_id)
    else:
        await callback.answer("Unknown action", show_alert=True)


@track_callback_latency("pause")
async def handle_pause(client: Client, callback: CallbackQuery, chat_id: int):
    """Handle pause callback (optimistic update)."""

    # Get cached state (instant, <1ms)
    cached_state = await cache.get_playback_state(chat_id)
    current_status = cached_state.get("status", "idle")
    
    if current_status == "paused":
        await callback.answer("Already paused!", show_alert=False)
        return
    
    if current_status != "playing":
        await callback.answer("Nothing is playing!", show_alert=True)
        return
    
    # Optimistic update: cache new state immediately (instant callback response)
    await cache.cache_playback_state(chat_id, status="paused")
    await callback.answer("⏸ Paused! The Soul King takes a breath... Yohoho!", show_alert=False)
    
    # Background task: verify and execute (non-blocking)
    async def _pause_bg():
        await queue_manager.set_status(chat_id, "paused")
        manager = _get_call_manager()
        await manager.pause(chat_id)
        progress_tracker.pause(chat_id)
        current = await queue_manager.get_current(chat_id)
        from bot.plugins.play import persist_playback_state
        await persist_playback_state(chat_id, "paused", current)
    
    asyncio.create_task(_pause_bg())


@track_callback_latency("resume")
async def handle_resume(client: Client, callback: CallbackQuery, chat_id: int):
    """Handle resume callback (optimistic update)."""
    # Get cached state (instant, <1ms)
    cached_state = await cache.get_playback_state(chat_id)
    current_status = cached_state.get("status", "idle")
    
    if current_status == "playing":
        await callback.answer("Already playing!", show_alert=False)
        return
    
    if current_status != "paused":
        await callback.answer("Not paused!", show_alert=True)
        return
    
    # Optimistic update: cache new state immediately
    await cache.cache_playback_state(chat_id, status="playing")
    await callback.answer("▶️ Resumed! YOHOHOHO! 🎸", show_alert=False)
    
    # Background task: verify and execute
    async def _resume_bg():
        await queue_manager.set_status(chat_id, "playing")
        manager = _get_call_manager()
        await manager.resume(chat_id)
        progress_tracker.resume(chat_id)
        current = await queue_manager.get_current(chat_id)
        from bot.plugins.play import persist_playback_state
        await persist_playback_state(chat_id, "playing", current)
    
    asyncio.create_task(_resume_bg())


@track_callback_latency("skip")
async def handle_skip(client: Client, callback: CallbackQuery, chat_id: int):
    """Handle skip callback (optimistic update with cache invalidation)."""
    # Get cached state
    cached_state = await cache.get_playback_state(chat_id)
    current_status = cached_state.get("status", "idle")
    
    if current_status not in ["playing", "paused"]:
        await callback.answer("Nothing playing!", show_alert=True)
        return
    
    # Optimistic update: invalidate queue cache since queue position changes
    await cache.invalidate_queue_snapshot(chat_id)
    
    await callback.answer("⏭ Skipping to the next track! Yohohoho!", show_alert=False)
    
    # Background task: perform skip
    async def _skip_bg():
        manager = _get_call_manager()
        await manager.leave_call(chat_id)
        progress_tracker.stop(chat_id)
        
        from bot.plugins.play import start_playback
        await start_playback(chat_id)
    
    asyncio.create_task(_skip_bg())


@track_callback_latency("stop")
async def handle_stop(client: Client, callback: CallbackQuery, chat_id: int):
    """Handle stop callback (optimistic update with cache invalidation)."""
    # Get cached state
    cached_state = await cache.get_playback_state(chat_id)
    current_status = cached_state.get("status", "idle")
    
    if current_status == "idle":
        await callback.answer("Already stopped!", show_alert=True)
        return
    
    # Optimistic update: invalidate both state and queue caches
    await cache.invalidate_playback_state(chat_id)
    await cache.invalidate_queue_snapshot(chat_id)
    
    await callback.answer("⏹ Stopped! The Soul King bows down! Yohoho!", show_alert=False)
    
    # Background task: perform stop
    async def _stop_bg():
        manager = _get_call_manager()
        await manager.leave_call(chat_id)
        await queue_manager.clear_queue(chat_id)
        progress_tracker.stop(chat_id)
        from bot.plugins.play import persist_playback_state
        await persist_playback_state(chat_id, "idle")

        # Trigger NP card auto-clean
        np_msg_id = await cache.get_np_message(chat_id)
        if np_msg_id:
            async def _nuke_np():
                await asyncio.sleep(config.NP_AUTOCLEAN_DELAY)
                try:
                    bot_client = bot_module.bot_client
                    if bot_client:
                        await bot_client.delete_messages(chat_id, np_msg_id)
                except Exception:
                    pass
                await cache.clear_np_message(chat_id)
            asyncio.create_task(_nuke_np())

        try:
            message = callback.message
            if message is not None:
                await message.edit(
                    "⏹ <b>Playback stopped &amp; queue cleared.</b>\n<i>The concert has ended, Yohoho!</i>",
                    parse_mode=ParseMode.HTML,
                )
        except Exception:
            pass
    
    asyncio.create_task(_stop_bg())


async def handle_forceresume(client: Client, callback: CallbackQuery, chat_id: int):
    """Handle force resume callback - clean stuck state and restart playback."""
    status = await queue_manager.get_status(chat_id)
    queue_len = await queue_manager.get_queue_length(chat_id)
    
    if queue_len == 0:
        await callback.answer("❌ Queue is empty! Add songs first.", show_alert=True)
        return
    
    try:
        # Import cleanup function
        from bot.plugins.play import cleanup_vc_session, start_playback
        
        # Clean up stuck state but preserve the remaining queue
        await cleanup_vc_session(chat_id, send_message=False, preserve_queue=True)
        
        # Start fresh playback from existing queue
        await start_playback(chat_id)
        
        await callback.answer("🔄 Force resumed! Cleaned up and restarting the concert!", show_alert=False)
        logger.info(f"Force resumed playback in {chat_id}")
    except Exception as e:
        logger.error(f"Force resume failed: {e}")
        await callback.answer("❌ Force resume failed. Try /play or /cleanup instead.", show_alert=True)


@track_callback_latency("queue")
async def handle_queue(client: Client, callback: CallbackQuery, chat_id: int):
    """Handle queue refresh callback (with caching for batch operations)."""
    # Try to use cached queue snapshot first (30-second cache)
    snapshot = await cache.get_queue_snapshot(chat_id)
    
    if snapshot:
        # Use cached snapshot (fast path)
        current = snapshot.get("current")
        queue = snapshot.get("queue", [])
        # Mark cache hit for metrics
        setattr(callback, "_metrics_cache_hit", True)
    else:
        # Cache miss - fetch fresh data
        db_start = time.time()
        queue = await queue_manager.get_queue(chat_id)
        current = await queue_manager.get_current(chat_id)
        setattr(callback, "_metrics_db_time_ms", (time.time() - db_start) * 1000)
        setattr(callback, "_metrics_cache_hit", False)
        
        # Cache the snapshot for next 30 seconds
        await cache.cache_queue_snapshot(chat_id, current, queue, ttl=30)

    if not queue and not current:
        await callback.answer("Queue is empty", show_alert=True)
        return

    lines = []
    if current:
        now = current.get("title", "Unknown")[:50]
        duration = current.get("duration", 0)
        lines.append(f"▶️ Now: {now} ({duration}s)")

    if queue:
        lines.append("\n📜 Upcoming:")
        for i, track in enumerate(queue[:8], start=1):
            title = track.get("title", "Unknown")[:45]
            duration = track.get("duration", 0)
            lines.append(f"{i}. {title} ({duration}s)")
        if len(queue) > 8:
            lines.append(f"... plus {len(queue)-8} more")

    text = "\n".join(lines)
    try:
        message = callback.message
        if message is not None:
            await message.edit(text, parse_mode=ParseMode.HTML)
    except Exception:
        pass
    await callback.answer("📋 Queue updated", show_alert=False)


@track_callback_latency("shuffle")
async def handle_shuffle(client: Client, callback: CallbackQuery, chat_id: int):
    """Handle shuffle callback (optimistic update with cache invalidation)."""
    queue = await queue_manager.get_queue(chat_id)
    if len(queue) < 2:
        await callback.answer("Need 2+ songs to shuffle!", show_alert=True)
        return

    # Get current shuffle state from cache
    cached_state = await cache.get_playback_state(chat_id)
    current_shuffle = cached_state.get("shuffle", False)
    
    # Toggle shuffle state
    new_shuffle = not current_shuffle
    
    # Optimistic update: cache new shuffle state
    await cache.cache_playback_state(chat_id, shuffle=new_shuffle)
    
    # Invalidate queue cache since order changed
    await cache.invalidate_queue_snapshot(chat_id)
    
    status_text = "✅ Shuffle ON!" if new_shuffle else "🔀 Shuffle OFF"
    await callback.answer(status_text, show_alert=False)
    
    # Background task: perform shuffle
    async def _shuffle_bg():
        await queue_manager.shuffle(chat_id)
    
    asyncio.create_task(_shuffle_bg())


async def handle_clearqueue(client: Client, callback: CallbackQuery, chat_id: int):
    """Handle clear queue callback (with cache invalidation)."""
    queue_len = await queue_manager.get_queue_length(chat_id)
    if queue_len == 0:
        await callback.answer("Queue already empty!", show_alert=True)
        return

    # Optimistic: invalidate cache immediately
    await cache.invalidate_queue_snapshot(chat_id)
    
    await callback.answer(f"🗑️ Cleared {queue_len} songs from the setlist! Yohoho!", show_alert=False)
    
    # Background task: clear the queue
    async def _clear_bg():
        await queue_manager.clear_queue(chat_id)
    
    asyncio.create_task(_clear_bg())


@track_callback_latency("loop")
async def handle_loop(client: Client, callback: CallbackQuery, chat_id: int):
    """Handle loop toggle callback (optimistic update)."""
    import bot.utils.database as app_db

    db = app_db.db
    if db is None:
        raise RuntimeError("Database is not initialized")

    group = await db.get_group(chat_id)
    current_mode = group.get("settings", {}).get("loop_mode", "none")

    modes = {"none": "track", "track": "queue", "queue": "none"}
    new_mode = modes.get(current_mode, "none")

    mode_text = {
        "none": "🔄 Loop OFF",
        "track": "🔂 Looping Track! Yohoho!",
        "queue": "🔁 Looping Queue! Yohohoho!"
    }

    # Optimistic update: cache new loop mode immediately
    await cache.cache_playback_state(chat_id, loop_mode=new_mode)
    await callback.answer(mode_text[new_mode], show_alert=False)
    
    # Background task: persist to database
    async def _loop_bg():
        await db.update_group(chat_id, {"settings": {"loop_mode": new_mode}})
        try:
            message = callback.message
            if message is not None and isinstance(message.reply_markup, InlineKeyboardMarkup):
                await message.edit_reply_markup(reply_markup=message.reply_markup)
        except Exception:
            pass
    
    asyncio.create_task(_loop_bg())


async def handle_brok_info(client: Client, callback: CallbackQuery, chat_id: int):
    """Handle the brok theme details callback."""
    text = (
        "🎵 **Brok Bot Theme**\n\n"
        "💀 One Piece inspired music bot\n"
        "🎸 High-quality audio\n"
        "Yohohoho!"
    )
    await callback.answer(text, show_alert=True)


async def handle_help_info(client: Client, callback: CallbackQuery, chat_id: int):
    """Handle help callback prompt by editing the message."""
    text = (
        "🍁 <b>Commands &amp; Authority List</b>\n\n"
        "<b>👥 Members:</b> /play, /vibe, /queue (/q), /now (/np), /pause, /resume, /uptime, /anonplay, /showlist, /showhistory\n"
        "<b>🛡 Admins:</b> /vplay, /skip (/next), /prev (/previous), /seek, /replay, /volume, /clearqueue, /stop (/off), /remove, /shuffle, /loop, /effects, /sleep, /starthunter, /stophunter, /block, /unblock\n"
        "<b>👑 Owner/Sudo:</b> /addsudo, /delsudo, /sudolist, /gban, /ungban, /stats, /broadcast, /restart, /maintenance\n\n"
        "<i>Authority is strictly role-based.</i>"
    )
    from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    back_button = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="status_check")]])

    try:
        message = callback.message
        if message is not None:
            await message.edit(text, reply_markup=back_button, parse_mode=ParseMode.HTML)
    except Exception:
        await callback.answer("Use /help for full command list!", show_alert=True)


async def handle_status_check(client: Client, callback: CallbackQuery, chat_id: int):
    """Handle status check inline button."""
    status = await queue_manager.get_status(chat_id)
    current = await queue_manager.get_current(chat_id)

    if status == "idle" or not current:
        text = "💀 The stage is empty! Use /play to start the music, Yohoho!"
    elif status == "paused":
        text = f"⏸ Paused: {current.get('title', 'Unknown')[:40]}"
    else:
        text = f"▶️ Now Playing: {current.get('title', 'Unknown')[:40]} 🎸"

    await callback.answer(text, show_alert=False)


@track_callback_latency("vol_up")
async def handle_vol_up(client: Client, callback: CallbackQuery, chat_id: int):
    """Handle volume up callback (optimistic update)."""
    current = await queue_manager.get_current(chat_id)
    if not current:
        await callback.answer("Nothing is playing", show_alert=True)
        return

    current_state = await cache.get_playback_state(chat_id)
    current_volume = current_state.get("volume", config.DEFAULT_VOLUME)
    try:
        current_volume = int(current_volume)
    except (ValueError, TypeError):
        current_volume = config.DEFAULT_VOLUME

    new_vol = min(200, current_volume + 10)
    await callback.answer(f"🔊 Volume +10% ({new_vol}%)", show_alert=False)
    
    # Background task: perform actual volume change
    async def _vol_up_bg():
        try:
            manager = _get_call_manager()
            await manager.set_volume(chat_id, new_vol)
            await cache.cache_playback_state(chat_id, volume=new_vol)
        except Exception as e:
            logger.error(f"Volume up failed: {e}")
    
    asyncio.create_task(_vol_up_bg())


@track_callback_latency("vol_down")
async def handle_vol_down(client: Client, callback: CallbackQuery, chat_id: int):
    """Handle volume down callback (optimistic update)."""
    current = await queue_manager.get_current(chat_id)
    if not current:
        await callback.answer("Nothing is playing", show_alert=True)
        return

    current_state = await cache.get_playback_state(chat_id)
    current_volume = current_state.get("volume", config.DEFAULT_VOLUME)
    try:
        current_volume = int(current_volume)
    except (ValueError, TypeError):
        current_volume = config.DEFAULT_VOLUME

    new_vol = max(0, current_volume - 10)
    await callback.answer(f"🔉 Volume -10% ({new_vol}%)", show_alert=False)
    
    # Background task: perform actual volume change
    async def _vol_down_bg():
        try:
            manager = _get_call_manager()
            await manager.set_volume(chat_id, new_vol)
            await cache.cache_playback_state(chat_id, volume=new_vol)
        except Exception as e:
            logger.error(f"Volume down failed: {e}")
    
    asyncio.create_task(_vol_down_bg())


async def handle_more_options(client: Client, callback: CallbackQuery, chat_id: int):
    """Handle more options callback."""
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎶 Replay", callback_data="replay"), InlineKeyboardButton("↩️ Previous", callback_data="previous")],
        [InlineKeyboardButton("📤 Export Queue", callback_data="export_queue"), InlineKeyboardButton("🔁 Loop", callback_data="loop")],
    ])
    try:
        message = callback.message
        if message is not None:
            await message.edit_reply_markup(reply_markup=keyboard)
    except Exception:
        pass
    await callback.answer("More options shown", show_alert=False)


async def handle_replay(client: Client, callback: CallbackQuery, chat_id: int):
    """Replay current track from beginning."""
    current = await queue_manager.get_current(chat_id)
    if not current:
        await callback.answer("No track to replay", show_alert=True)
        return

    from bot.plugins.play import start_playback
    manager = _get_call_manager()
    await manager.leave_call(chat_id)
    await start_playback(chat_id, seek=0)
    await callback.answer("🔁 Replay started", show_alert=False)


async def handle_previous(client: Client, callback: CallbackQuery, chat_id: int):
    """Play previously completed track if possible."""
    if not config.ENABLE_PREVIOUS_TRACK:
        await callback.answer("⏮️ Previous track feature is disabled by admin.", show_alert=True)
        return

    from bot.plugins.controls import _play_previous_track

    prev = await _play_previous_track(chat_id)
    if not prev:
        await callback.answer("⏮️ No previous track in history yet.", show_alert=True)
        return

    title = prev.get("title") if isinstance(prev, dict) else None
    display_title = title[:40] if title else "Unknown"
    await callback.answer(f"⏮️ Playing previous track: {display_title}", show_alert=False)


async def handle_export_queue(client: Client, callback: CallbackQuery, chat_id: int):
    """Export queue to a text file for sharing."""
    if not config.ENABLE_QUEUE_EXPORT:
        await callback.answer("📤 Queue export is disabled by admin.", show_alert=True)
        return

    queue = await queue_manager.get_queue(chat_id)
    if not queue:
        await callback.answer("Queue is empty", show_alert=True)
        return

    lines = [f"{i+1}. {t.get('title', 'Unknown')} ({t.get('duration',0)}s)" for i,t in enumerate(queue)]
    text = "\n".join(lines[:200])
    if len(lines) > 200:
        text += f"\n... (+{len(lines)-200} more)"

    if not bot_module.bot_client:
        await callback.answer("Bot client not initialized yet.", show_alert=True)
        return

    try:
        await bot_module.bot_client.send_message(chat_id, f"📤 Queue export:\n{text}")
        await callback.answer("Queue exported", show_alert=False)
    except Exception as e:
        logger.error(f"export_queue failed: {e}")
        await callback.answer("Export failed", show_alert=True)


async def handle_play_select(client: Client, callback: CallbackQuery, chat_id: int, user_id: int, data: str):
    """Handle song selection from conflict resolution (supports ps:token:index and legacy formats)."""
    token = None

    try:
        if data.startswith("ps:"):
            parts = data.split(":")
            if len(parts) == 2:
                idx = int(parts[1])
            elif len(parts) == 3:
                token = parts[1]
                idx = int(parts[2])
            else:
                raise ValueError()
        else:
            idx = int(data.split("_")[-1])
    except (IndexError, ValueError):
        await callback.answer("Invalid selection", show_alert=True)
        return

    from bot.plugins.play import get_pending_conflict, resolve_conflict

    conflict, resolved_token = await get_pending_conflict(chat_id, user_id, token)
    token = token or resolved_token

    if not conflict:
        await callback.answer("⚠️ Selection expired — please search again.", show_alert=True)
        return

    if conflict.get("user_id") not in (None, user_id):
        await callback.answer("This menu belongs to someone else.", show_alert=True)
        return

    tracks = conflict.get("tracks", [])
    if idx < 0 or idx >= len(tracks):
        await callback.answer("Invalid selection", show_alert=True)
        return

    selected = tracks[idx]
    title = selected.title if hasattr(selected, "title") else selected.get("title", "?")
    await callback.answer(f"🎵 {title[:40]}", show_alert=False)

    # Delegate to resolve_conflict which handles dict/Track normalisation and enqueuing
    message = callback.message
    message.from_user = callback.from_user
    await resolve_conflict(chat_id, user_id, idx, message, token)


async def handle_play_cancel(client: Client, callback: CallbackQuery, chat_id: int, user_id: int, data: str):
    """Handle cancel from conflict resolution with token scoping."""
    from bot.plugins.play import _pending_conflicts

    token = data.split(":", 1)[1] if data.startswith("pc:") and ":" in data else None

    chat_conflicts = _pending_conflicts.get(chat_id, {})
    removed = False

    if token and token in chat_conflicts:
        chat_conflicts.pop(token, None)
        removed = True
    else:
        for tok, conf in list(chat_conflicts.items()):
            if conf.get("user_id") == user_id:
                chat_conflicts.pop(tok, None)
                removed = True

    if not chat_conflicts:
        _pending_conflicts.pop(chat_id, None)

    await callback.answer("❌ Cancelled")
    try:
        message = callback.message
        if message is not None:
            await message.edit(
                "❌ <b>Selection cancelled.</b>\n<i>Use /play to search again, Yohoho!</i>",
                parse_mode=ParseMode.HTML,
            )
    except Exception:
        pass
