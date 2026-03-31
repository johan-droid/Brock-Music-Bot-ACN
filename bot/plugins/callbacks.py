"""Callback query handlers for inline buttons."""

import logging
from pyrogram import Client
from pyrogram.types import CallbackQuery
from bot.utils.permissions import get_permission_level
from bot.core.queue import queue_manager
from bot.core.call import call_manager
from bot.utils.progress_tracker import progress_tracker
from bot.utils.cache import cache
from bot.core.bot import bot_client
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

    if data == "play_cancel":
        await handle_play_cancel(client, callback, chat_id, user_id)
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
        "brok_info": handle_brok_info,
        "help": handle_help_info,
        "help_menu": handle_help_info,
        "status_check": handle_status_check,
    }

    handler = handlers.get(data)
    if handler:
        # Playback callbacks — open to all non-banned members (level >= 1)
        if data in ["pause", "resume", "skip", "stop", "shuffle", "clearqueue", "loop"]:
            if level < 1:
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
                await bot_client.delete_messages(chat_id, np_msg_id)
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

    await callback.answer("📋 Queue refreshed")


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

    # Only clear queue, keep playing current
    key = f"vc:queue:{chat_id}"
    from bot.utils.cache import redis_client
    await redis_client.delete(key)

    await callback.answer(f"🗑️ Cleared {queue_len} songs from the setlist! Yohoho!")


async def handle_loop(client: Client, callback: CallbackQuery, chat_id: int):
    """Handle loop toggle callback."""
    import bot.utils.database as app_db

    group = await app_db.db.get_group(chat_id)
    current_mode = group.get("settings", {}).get("loop_mode", "none")

    modes = {"none": "track", "track": "queue", "queue": "none"}
    new_mode = modes.get(current_mode, "none")

    await app_db.db.update_group(chat_id, {"settings.loop_mode": new_mode})

    mode_text = {"none": "🔄 Loop OFF", "track": "🔂 Looping Track! Yohoho!", "queue": "🔁 Looping Queue! Yohohoho!"}
    await callback.answer(mode_text[new_mode])


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
        "💀 <b>Soul King's Guide to the Grand Line</b> 🎸\n\n"
        "📜 <b>Commands:</b>\n"
        "• <code>/play &lt;query&gt;</code> - Start the music\n"
        "• <code>/pause</code> / <code>/resume</code> - Control the flow\n"
        "• <code>/skip</code> - Next island's melody\n"
        "• <code>/stop</code> - End the concert\n"
        "• <code>/queue</code> - See the setlist\n\n"
        "<i>\"Music connects us all, Yohohoho!\"</i>"
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

    await callback.answer(text, show_alert=True)


async def handle_play_select(client: Client, callback: CallbackQuery, chat_id: int, user_id: int, data: str):
    """Handle song selection from conflict resolution (supports ps:N and legacy play_select_N)."""
    # Parse index from either "ps:N" or "play_select_N"
    try:
        if data.startswith("ps:"):
            idx = int(data[3:])
        else:
            idx = int(data.split("_")[-1])
    except (IndexError, ValueError):
        await callback.answer("Invalid selection", show_alert=True)
        return

    from bot.plugins.play import _pending_conflicts, resolve_conflict

    chat_conflicts = _pending_conflicts.get(chat_id, {})
    if user_id not in chat_conflicts:
        await callback.answer("⚠️ Selection expired — please search again.", show_alert=True)
        return

    tracks = chat_conflicts[user_id].get("tracks", [])
    if idx < 0 or idx >= len(tracks):
        await callback.answer("Invalid selection", show_alert=True)
        return

    selected = tracks[idx]
    title = selected.title if hasattr(selected, "title") else selected.get("title", "?")
    await callback.answer(f"🎵 {title[:40]}", show_alert=False)

    # Delegate to resolve_conflict which handles dict/Track normalisation and enqueuing
    message = callback.message
    message.from_user = callback.from_user
    await resolve_conflict(chat_id, user_id, idx, message)


async def handle_play_cancel(client: Client, callback: CallbackQuery, chat_id: int, user_id: int):
    """Handle cancel from conflict resolution."""
    from bot.plugins.play import _pending_conflicts

    chat_conflicts = _pending_conflicts.get(chat_id, {})
    if user_id in chat_conflicts:
        del chat_conflicts[user_id]
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
