"""Queue commands: /queue, /clearqueue, /remove, /shuffle, /loop"""

import logging
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from bot.utils.permissions import require_admin, require_member, rate_limit, get_permission_level
from bot.utils.formatters import format_queue_list, format_duration, truncate_text
from bot.core.queue import queue_manager

logger = logging.getLogger(__name__)


@Client.on_message(filters.command(["queue", "q"]) & filters.group)
@require_member
@rate_limit
async def queue_cmd(client: Client, message: Message):
    """Show current queue."""
    chat_id = message.chat.id
    
    # Get queue
    queue = await queue_manager.get_queue(chat_id)
    current = await queue_manager.get_current(chat_id)
    
    if not queue and not current:
        await message.reply("📭 The queue is empty.\nUse /play to add songs.")
        return
    
    # Build display
    lines = ["💀 **Soul King's Setlist! Yohohoho!**\n"]
    
    # Currently playing
    if current:
        title = truncate_text(current.get("title", "Unknown"), 50)
        duration = format_duration(current.get("duration", 0))
        lines.append(f"🎧 **Now Playing:** {title} `({duration})`\n")
    
    # Queue
    if queue:
        for i, track in enumerate(queue[:20], 1):  # Show first 20
            title = truncate_text(track.get("title", "Unknown"), 45)
            duration = format_duration(track.get("duration", 0))
            lines.append(f"`{i:2d}.` {title} `({duration})`")
        
        if len(queue) > 20:
            lines.append(f"\n... and {len(queue) - 20} more songs")
        
        total_duration = sum(t.get("duration", 0) for t in queue)
        if current:
            total_duration += current.get("duration", 0)
        
        lines.append(f"\n**Total Duration:** {format_duration(total_duration)}")
    else:
        lines.append("📭 No more songs in queue.")
    
    # Add control buttons
    buttons = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔀 Shuffle", callback_data="shuffle"),
            InlineKeyboardButton("🗑 Clear", callback_data="clearqueue"),
        ],
        [
            InlineKeyboardButton("⏭ Skip", callback_data="skip"),
            InlineKeyboardButton("🔄 Refresh Format", callback_data="queue"),
        ]
    ])
    
    text = "\n".join(lines)
    await message.reply(text, reply_markup=buttons)


@Client.on_message(filters.command(["now", "np", "nowplaying"]) & filters.group)
@require_member
@rate_limit
async def now_cmd(client: Client, message: Message):
    """Show currently playing track."""
    chat_id = message.chat.id
    
    current = await queue_manager.get_current(chat_id)
    status = await queue_manager.get_status(chat_id)
    
    if not current or status == "idle":
        await message.reply("📭 Nothing is playing right now.\nUse /play to start playback.")
        return
    
    from bot.utils.thumbnails import generate_np_thumbnail
    from bot.utils.formatters import create_progress_bar
    
    # Get position
    position = await queue_manager.get_position(chat_id)
    duration = current.get("duration", 0)
    
    # Generate thumbnail
    thumb_data = await generate_np_thumbnail(
        title=current["title"],
        artist=current.get("uploader", ""),
        duration=duration,
        position=position,
        thumbnail_url=current.get("thumb"),
        source=current.get("source", "youtube")
    )
    
    # Build text
    bar = create_progress_bar(position, duration)
    current_str = format_duration(position)
    total_str = format_duration(duration)
    
    status_emoji = "⏸" if status == "paused" else "▶"
    
    text = f"""
💀 **YOHOHOHO! The Soul King is playing!**
{status_emoji} **Now Playing:** {truncate_text(current['title'], 55)}

{bar}
⏱ `{current_str}` / `{total_str}`

<i>"Music is your own experience... though I can't experience much without a brain! Yohohoho!"</i>
    """
    
    # Control buttons
    buttons = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⏯ Pause/Resume", 
                               callback_data="pause" if status == "playing" else "resume"),
            InlineKeyboardButton("⏭ Skip", callback_data="skip"),
        ],
        [
            InlineKeyboardButton("🔁 Loop", callback_data="loop"),
            InlineKeyboardButton("📋 View Queue", callback_data="queue"),
        ]
    ])
    
    if thumb_data:
        await message.reply_photo(photo=thumb_data, caption=text, reply_markup=buttons)
    else:
        await message.reply(text, reply_markup=buttons)


@Client.on_message(filters.command("clearqueue") & filters.group)
@require_admin
@rate_limit
async def clearqueue_cmd(client: Client, message: Message):
    """Clear all songs from queue (admin only)."""
    chat_id = message.chat.id
    
    await queue_manager.clear_queue(chat_id)
    await message.reply("🗑 Queue cleared.")
    logger.info(f"Queue cleared in chat {chat_id}")


@Client.on_message(filters.command(["remove", "rm"]) & filters.group)
@require_admin
@rate_limit
async def remove_cmd(client: Client, message: Message):
    """Remove specific song by position (admin only)."""
    chat_id = message.chat.id
    
    if len(message.command) < 2:
        await message.reply("❌ Usage: `/remove [position]`\nExample: `/remove 2`")
        return
    
    try:
        position = int(message.command[1])
        if position < 1:
            await message.reply("❌ Position must be 1 or higher.")
            return
    except ValueError:
        await message.reply("❌ Please provide a valid position number.")
        return
    
    # Remove from queue
    removed = await queue_manager.remove_at(chat_id, position)
    
    if removed:
        title = truncate_text(removed.get("title", "Unknown"), 50)
        await message.reply(f"✅ Removed from queue:\n**{title}**")
        logger.info(f"Removed track at pos {position} from chat {chat_id}")
    else:
        await message.reply(f"❌ No song found at position {position}.")


@Client.on_message(filters.command("shuffle") & filters.group)
@require_admin
@rate_limit
async def shuffle_cmd(client: Client, message: Message):
    """Shuffle queue randomly (admin only)."""
    chat_id = message.chat.id
    
    queue = await queue_manager.get_queue(chat_id)
    if len(queue) < 2:
        await message.reply("❌ Need at least 2 songs in queue to shuffle.")
        return
    
    await queue_manager.shuffle(chat_id)
    await message.reply(f"🔀 Queue shuffled! ({len(queue)} songs)")
    logger.info(f"Shuffled queue in chat {chat_id}")


@Client.on_message(filters.command("loop") & filters.group)
@require_admin
@rate_limit
async def loop_cmd(client: Client, message: Message):
    """Toggle loop mode (admin only)."""
    chat_id = message.chat.id
    
    # Get current loop mode
    import bot.utils.database as app_db
    group = await app_db.db.get_group(chat_id)
    current_mode = group.get("settings", {}).get("loop_mode", "none")
    
    # Toggle: none -> track -> queue -> none
    modes = {"none": "track", "track": "queue", "queue": "none"}
    new_mode = modes.get(current_mode, "none")
    
    # Update settings
    await app_db.db.update_group(chat_id, {"settings.loop_mode": new_mode})
    
    mode_text = {
        "none": "❌ Loop disabled",
        "track": "🔁 Looping current track",
        "queue": "🔂 Looping entire queue"
    }
    
    await message.reply(mode_text[new_mode])
    logger.info(f"Set loop mode to {new_mode} in chat {chat_id}")


@Client.on_message(filters.command("move") & filters.group)
@require_admin
@rate_limit
async def move_cmd(client: Client, message: Message):
    """Move a song (admin only)."""
    chat_id = message.chat.id
    
    if len(message.command) < 3:
        await message.reply("❌ Usage: `/move [from] [to]`\nExample: `/move 3 1`")
        return
    
    try:
        from_pos = int(message.command[1])
        to_pos = int(message.command[2])
        
        if from_pos < 1 or to_pos < 1:
            await message.reply("❌ Positions must be 1 or higher.")
            return
    except ValueError:
        await message.reply("❌ Please provide valid position numbers.")
        return
    
    # Move the track
    await queue_manager.move(chat_id, from_pos, to_pos)
    await message.reply(f"✅ Moved song from position {from_pos} to {to_pos}.")
    logger.info(f"Moved track from {from_pos} to {to_pos} in chat {chat_id}")
