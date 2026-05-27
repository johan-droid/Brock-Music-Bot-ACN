import logging
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.enums import ParseMode

from bot.ai_search import vibe_search
from bot.utils.permissions import rate_limit, require_member
from bot.core.music_backend import music_backend
from bot.plugins.play import add_track_and_play, _show_conflict_options

logger = logging.getLogger(__name__)

@Client.on_message(filters.command(["vibe"]) & filters.group)
@require_member
@rate_limit(limit=3, period=10)
async def vibe_command(client: Client, message: Message):
    """Search music by mood/vibe using microservice-backed hints."""
    if len(message.command) < 2:
        return await message.reply("🎵 **Usage:** `/vibe <mood/activity>`\n*Example:* `/vibe something calm for reading`")

    query = " ".join(message.command[1:])
    chat_id = message.chat.id
    user_id = message.from_user.id if message.from_user else 0

    search_msg = await message.reply("🔍 *Analyzing vibe...*", parse_mode=ParseMode.MARKDOWN)

    # Extract tags
    tags = vibe_search.extract_tags(query)

    if not tags:
        # Fallback to normal search
        await search_msg.edit("🤔 *Couldn't match any specific vibes. Falling back to text search...*", parse_mode=ParseMode.MARKDOWN)
        results = await music_backend.search(query, limit=5)

        if not results:
            return await search_msg.edit("❌ **No results found for that vibe.**")

        return await _show_conflict_options(message, chat_id, user_id, results, search_msg)

    await search_msg.edit(f"🎧 *Searching vibe tracks:* `{', '.join(tags)}`...", parse_mode=ParseMode.MARKDOWN)

    results = await vibe_search.search_by_tags(tags, limit=5)

    if not results:
        # Fallback to normal search
        await search_msg.edit("🤔 *No vibe-specific tracks found. Falling back to regular search...*", parse_mode=ParseMode.MARKDOWN)
        results = await music_backend.search(query, limit=5)

        if not results:
            return await search_msg.edit("❌ **No results found.**")

    # Show selection menu
    await _show_conflict_options(message, chat_id, user_id, results, search_msg)
