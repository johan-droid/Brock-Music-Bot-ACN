"""Callback query handlers for inline buttons."""

import logging
from pyrogram import Client
from pyrogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from bot.utils.permissions import get_permission_level
from bot.core.queue import queue_manager
from bot.core.call import call_manager
from bot.utils.progress_tracker import progress_tracker
from bot.utils.cache import cache
from bot.core import bot as bot_module
from config import config
import asyncio

logger = logging.getLogger(__name__)


@Client.on_callback_query()
async def callback_handler(client: Client, callback: CallbackQuery):
    """Handle all callback queries."""
    user_id = callback.from_user.id
    chat_id = callback.message.chat.id
    data = callback.data

    # Handle play conflict resolution (new format "ps:N", legacy "play_select_N")
    if data.startswith("ps:") or data.startswith("play_select_"):
        await handle_play_select(client, callback, chat_id, user_id, data)
        return

    if data.startswith("pc:"):
        await handle_play_cancel(client, callback, chat_id, user_id, data)
        return

    if data == "play_cancel":  # legacy
        await handle_play_cancel(client, callback, chat_id, user_id, data)
        return

    # Check permissions
    level = await get_permission_level(user_id, chat_id)

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
        "brok_info": handle_brok_info,
        "help": handle_help_info,
        "help_menu": handle_help_info,
        "status_check": handle_status_check,
    }

    handler = handlers.get(data)
    if handler:
        # Match callback authority with command authority.
        admin_actions = {"skip", "stop", "shuffle", "clearqueue", "loop"}
        member_actions = {"pause", "resume", "queue"}

        if data in admin_actions and level < 3:
            await callback.answer("⛔ Admins only for this action.", show_alert=True)
            return

        if data in member_actions and level < 1:
            await callback.answer("⛔ You are banned from using this bot!", show_alert=True)
            return

        await handler(client, callback, chat_id)
    else:
        await callback.answer("Unknown action", show_alert=True)


async def handle_pause(client: Client, callback: CallbackQuery, chat_id: int):
    """Handle pause callback."""
    status = await queue_manager.get_status(chat_id)
    if status != "playing":
        await callback.answer("Nothing is playing!", show_alert=True)
        return

    await queue_manager.set_status(chat_id, "paused")
    await call_manager.pause(chat_id)
    progress_tracker.pause(chat_id)

    await callback.answer("⏸ Paused! The Soul King takes a breath... Yohoho!", show_alert=False)


async def handle_resume(client: Client, callback: CallbackQuery, chat_id: int):
    """Handle resume callback."""
    status = await queue_manager.get_status(chat_id)
    if status != "paused":
        await callback.answer("Not paused!", show_alert=True)
        return

    await queue_manager.set_status(chat_id, "playing")
    await call_manager.resume(chat_id)
    progress_tracker.resume(chat_id)

    await callback.answer("▶️ Resumed! YOHOHOHO! 🎸", show_alert=False)


async def handle_skip(client: Client, callback: CallbackQuery, chat_id: int):
    """Handle skip callback."""
    status = await queue_manager.get_status(chat_id)
    if status not in ["playing", "paused"]:
        await callback.answer("Nothing playing!", show_alert=True)
        return

    await callback.answer("⏭ Skipping to the next track! Yohohoho!", show_alert=False)

    # Trigger skip
    await call_manager.leave_call(chat_id)
    progress_tracker.stop(chat_id)

    from bot.plugins.play import start_playback
    await start_playback(chat_id)


async def handle_stop(client: Client, callback: CallbackQuery, chat_id: int):
    """Handle stop callback."""
    status = await queue_manager.get_status(chat_id)
    if status == "idle":
        await callback.answer("Already stopped!", show_alert=True)
        return

    await call_manager.leave_call(chat_id)
    await queue_manager.clear_queue(chat_id)
    progress_tracker.stop(chat_id)

    # Trigger NP card auto-clean
    np_msg_id = await cache.get_np_message(chat_id)
    if np_msg_id:
        async def _nuke_np():
            await asyncio.sleep(config.NP_AUTOCLEAN_DELAY)
            try:
                if bot_module.bot_client:
                    await bot_module.bot_client.delete_messages(chat_id, np_msg_id)
            except Exception:
                pass
            await cache.clear_np_message(chat_id)
        asyncio.create_task(_nuke_np())

    await callback.answer("⏹ Stopped! The Soul King bows down! Yohoho!", show_alert=False)
    try:
        await callback.message.edit(
            "⏹ <b>Playback stopped &amp; queue cleared.</b>\n<i>The concert has ended, Yohoho!</i>",
            parse_mode="html",
        )
    except Exception:
        pass


async def handle_queue(client: Client, callback: CallbackQuery, chat_id: int):
    """Handle queue refresh callback."""
    queue = await queue_manager.get_queue(chat_id)
    current = await queue_manager.get_current(chat_id)

    if not queue and not current:
        await callback.answer("Queue is empty", show_alert=True)
        return

    lines = []
    if current:
        now = current.get("title", "Unknown")
        duration = current.get("duration", 0)
        lines.append(f"▶️ Now: {now} ({duration}s)")

    if queue:
        lines.append("\n📜 Upcoming:")
        for i, track in enumerate(queue[:8], start=1):
            title = track.get("title", "Unknown")
            duration = track.get("duration", 0)
            lines.append(f"{i}. {title} ({duration}s)")
        if len(queue) > 8:
            lines.append(f"... plus {len(queue)-8} more")

    text = "\n".join(lines)
    try:
        await callback.message.edit(text, parse_mode="html")
    except Exception:
        pass
    await callback.answer("📋 Queue updated", show_alert=False)


async def handle_shuffle(client: Client, callback: CallbackQuery, chat_id: int):
    """Handle shuffle callback."""
    queue = await queue_manager.get_queue(chat_id)
    if len(queue) < 2:
        await callback.answer("Need 2+ songs to shuffle!", show_alert=True)
        return

    await queue_manager.shuffle(chat_id)
    await callback.answer("🔀 Shuffled the Soul King's setlist! Yohoho!")


async def handle_clearqueue(client: Client, callback: CallbackQuery, chat_id: int):
    """Handle clear queue callback."""
    queue_len = await queue_manager.get_queue_length(chat_id)
    if queue_len == 0:
        await callback.answer("Queue already empty!", show_alert=True)
        return

    await queue_manager.clear_queue(chat_id)

    await callback.answer(f"🗑️ Cleared {queue_len} songs from the setlist! Yohoho!", show_alert=False)


async def handle_loop(client: Client, callback: CallbackQuery, chat_id: int):
    """Handle loop toggle callback."""
    import bot.utils.database as app_db

    group = await app_db.db.get_group(chat_id)
    current_mode = group.get("settings", {}).get("loop_mode", "none")

    modes = {"none": "track", "track": "queue", "queue": "none"}
    new_mode = modes.get(current_mode, "none")

    await app_db.db.update_group(chat_id, {"settings.loop_mode": new_mode})

    mode_text = {
        "none": "🔄 Loop OFF",
        "track": "🔂 Looping Track! Yohoho!",
        "queue": "🔁 Looping Queue! Yohohoho!"
    }

    await callback.answer(mode_text[new_mode], show_alert=False)
    try:
        await callback.message.edit_reply_markup(reply_markup=callback.message.reply_markup)
    except Exception:
        pass


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
        "<b>👥 Members:</b> /play, /queue (/q), /pause, /resume, /seek, /replay, /now (/np), /volume\n"
        "<b>🛡 Admins:</b> /vplay, /clearqueue, /skip, /stop, /remove, /shuffle, /loop\n"
        "<b>👑 Owner/Sudo:</b> /addsudo, /delsudo, /sudolist, /gban, /ungban, /block, /unblock, /stats, /broadcast, /restart, /maintenance\n\n"
        "<i>Authority is strictly role-based.</i>"
    )
    from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    back_button = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="status_check")]])

    try:
        await callback.message.edit(text, reply_markup=back_button, parse_mode="html")
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


async def handle_vol_up(client: Client, callback: CallbackQuery, chat_id: int):
    """Handle volume up callback."""
    current = await queue_manager.get_current(chat_id)
    if not current:
        await callback.answer("Nothing is playing", show_alert=True)
        return

    now_vol = await call_manager._call_for(chat_id)
    # cannot reliably read current volume from pyrogram, just set 10% up from 100 (max 200)
    try:
        # fallback to 100 if not available
        new_vol = min(200, 100 + 10)
        await call_manager.set_volume(chat_id, new_vol)
        await callback.answer(f"🔊 Volume +10% ({new_vol}%)", show_alert=False)
    except Exception as e:
        logger.error(f"Volume up failed: {e}")
        await callback.answer("Failed to adjust volume", show_alert=True)


async def handle_vol_down(client: Client, callback: CallbackQuery, chat_id: int):
    """Handle volume down callback."""
    current = await queue_manager.get_current(chat_id)
    if not current:
        await callback.answer("Nothing is playing", show_alert=True)
        return

    try:
        new_vol = max(1, 100 - 10)
        await call_manager.set_volume(chat_id, new_vol)
        await callback.answer(f"🔉 Volume -10% ({new_vol}%)", show_alert=False)
    except Exception as e:
        logger.error(f"Volume down failed: {e}")
        await callback.answer("Failed to adjust volume", show_alert=True)


async def handle_more_options(client: Client, callback: CallbackQuery, chat_id: int):
    """Handle more options callback."""
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎶 Replay", callback_data="replay"), InlineKeyboardButton("↩️ Previous", callback_data="previous")],
        [InlineKeyboardButton("📤 Export Queue", callback_data="export_queue"), InlineKeyboardButton("🔁 Loop", callback_data="loop")],
    ])
    try:
        await callback.message.edit_reply_markup(reply_markup=keyboard)
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
    await call_manager.leave_call(chat_id)
    await start_playback(chat_id, seek=0)
    await callback.answer("🔁 Replay started", show_alert=False)


async def handle_previous(client: Client, callback: CallbackQuery, chat_id: int):
    """Play previously completed track if possible."""
    prev = await queue_manager.get_previous(chat_id)
    if not prev:
        await callback.answer("⏮️ No previous track in history yet.", show_alert=True)
        return

    await queue_manager.set_status(chat_id, "playing")
    await progress_tracker.stop(chat_id)
    await progress_tracker.start(chat_id, 0)

    is_video = prev.get("is_video", False)
    try:
        await call_manager.change_stream(chat_id, prev["url"], video=is_video, seek=0)
        await callback.answer(f"⏮️ Playing previous track: {prev.get('title','Unknown')[:40]}", show_alert=False)
    except Exception as e:
        logger.error(f"Previous track failed: {e}")
        await callback.answer("Failed to play previous track.", show_alert=True)


async def handle_export_queue(client: Client, callback: CallbackQuery, chat_id: int):
    """Export queue to a text file for sharing."""
    queue = await queue_manager.get_queue(chat_id)
    if not queue:
        await callback.answer("Queue is empty", show_alert=True)
        return

    lines = [f"{i+1}. {t.get('title', 'Unknown')} ({t.get('duration',0)}s)" for i,t in enumerate(queue)]
    text = "\n".join(lines[:200])
    if len(lines) > 200:
        text += f"\n... (+{len(lines)-200} more)"

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
        await callback.message.edit(
            "❌ <b>Selection cancelled.</b>\n<i>Use /play to search again, Yohoho!</i>",
            parse_mode="html",
        )
    except Exception:
        pass
