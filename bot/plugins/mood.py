"""Mood and discovery commands backed by the external track service."""

import json
import logging
import math
import re
from typing import Any, Dict, List, cast

from pyrogram import Client, filters

Client = cast(Any, Client)
from pyrogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.core.music_backend import music_backend
from bot.utils.cache import cache
from bot.utils.permissions import get_permission_level, rate_limit
from config import config

logger = logging.getLogger(__name__)


def _is_group_chat(chat) -> bool:
    return "group" in str(getattr(chat, "type", "")).lower()


async def _ensure_allowed_message(message: Message) -> bool:
    if not _is_group_chat(message.chat):
        return True

    chat_id = message.chat.id
    user_id = message.from_user.id if message.from_user else None
    if config.BOUND_GROUP_ID is not None and chat_id != config.BOUND_GROUP_ID:
        await message.reply("This bot is bound to a different group and cannot be used here.")
        return False
    if not user_id or await get_permission_level(user_id, chat_id) < 1:
        await message.reply("You are not allowed to use this bot.")
        return False
    return True


async def _ensure_allowed_callback(query: CallbackQuery) -> bool:
    if not query.message or not _is_group_chat(query.message.chat):
        return True

    chat_id = query.message.chat.id
    user_id = query.from_user.id if query.from_user else None
    if config.BOUND_GROUP_ID is not None and chat_id != config.BOUND_GROUP_ID:
        await query.answer("This bot is bound to a different group.", show_alert=True)
        return False
    if not user_id or await get_permission_level(user_id, chat_id) < 1:
        await query.answer("You are not allowed to use this bot.", show_alert=True)
        return False
    return True


DEFAULT_TAGS = [
    "happy",
    "upbeat",
    "energetic",
    "chill",
    "ambient",
    "calm",
    "rock",
    "pop",
    "jazz",
    "classical",
    "electronic",
    "dance",
    "acoustic",
    "piano",
    "guitar",
    "focus",
    "party",
    "romantic",
    "sad",
    "dark",
]


def map_keywords_to_tags(query: str, vocabulary: List[str]) -> List[str]:
    if not vocabulary:
        return [word.lower() for word in re.findall(r"\b\w+\b", query) if len(word) > 2][:3]

    words = [word.lower() for word in re.findall(r"\b\w+\b", query)]
    matched_tags = []

    for word in words:
        if len(word) < 3:
            continue
        if word in vocabulary:
            matched_tags.append(word)
            continue
        partials = [tag for tag in vocabulary if word in tag or tag in word]
        if partials:
            partials.sort(key=lambda tag: abs(len(tag) - len(word)))
            matched_tags.append(partials[0])

    return list(dict.fromkeys(matched_tags))[:3]


def _track_to_ui_item(track: Any) -> Dict[str, Any]:
    if hasattr(track, "to_dict"):
        raw = track.to_dict()
    elif isinstance(track, dict):
        raw = dict(track)
    else:
        raw = {}

    return {
        "id": str(raw.get("id") or raw.get("track_id") or raw.get("url") or ""),
        "name": raw.get("title") or raw.get("name") or "Unknown Title",
        "artist_name": raw.get("artist") or raw.get("uploader") or "Unknown Artist",
        "duration": int(raw.get("duration") or 0),
        "audio": raw.get("url") or raw.get("stream_url") or "",
        "image": raw.get("thumbnail") or raw.get("thumbnail_url") or "",
        "source": raw.get("source") or "unknown",
    }


async def search_tracks_by_tags(tags: List[str]) -> List[Dict[str, Any]]:
    if not tags:
        return []

    cache_key = f"mood_search_{'+'.join(tags)}"
    cached = await cache.get(cache_key)
    if cached:
        try:
            items = json.loads(cached)
            if isinstance(items, list):
                return items
        except Exception:
            pass

    query = " ".join(tags)
    try:
        results = await music_backend.search(query, limit=10)
    except Exception as exc:
        logger.error("Mood search failed for tags=%s: %s", tags, exc)
        return []

    items = [_track_to_ui_item(item) for item in results]
    await cache.set(cache_key, json.dumps(items), ex=600)
    return items


def build_results_keyboard(tracks: List[Dict[str, Any]], page: int, query_id: str, tags_str: str) -> InlineKeyboardMarkup:
    items_per_page = 5
    total_pages = max(1, math.ceil(len(tracks) / items_per_page))

    start_idx = (page - 1) * items_per_page
    end_idx = start_idx + items_per_page
    current_tracks = tracks[start_idx:end_idx]

    buttons = []
    for track in current_tracks:
        title = track.get("name", "Unknown")
        artist = track.get("artist_name", "Unknown")
        label = f"🎵 {title[:20]} - {artist[:15]}"
        buttons.append([InlineKeyboardButton(label, switch_inline_query_current_chat=f"{title} {artist}")])

    nav_buttons = []
    if page > 1:
        nav_buttons.append(InlineKeyboardButton("Prev", callback_data=f"moodpage:{query_id}:{page - 1}:{tags_str}"))
    if page < total_pages:
        nav_buttons.append(InlineKeyboardButton("More", callback_data=f"moodpage:{query_id}:{page + 1}:{tags_str}"))
    if nav_buttons:
        buttons.append(nav_buttons)

    return InlineKeyboardMarkup(buttons)


@Client.on_message(filters.command("moodsearch") & (filters.private | filters.group))
@rate_limit
async def moodsearch_cmd(client: Client, message: Message):
    if not await _ensure_allowed_message(message):
        return

    if len(message.command) < 2:
        await message.reply(
            "🎻 Describe a mood, tempo, instrument, or late-night feeling and Brook will search the external music sea for it.\n"
            "Usage: `/moodsearch <description>`\n"
            "Example: `/moodsearch upbeat acoustic guitar for a sunny morning`"
        )
        return

    query = message.text.split(maxsplit=1)[1]
    msg = await message.reply("💀 Brook is listening for the shape of that feeling... Yohohoho!")

    tags = map_keywords_to_tags(query, DEFAULT_TAGS)
    if not tags:
        await msg.edit("💀 Brook could not hear a clear mood in that request. Try different wording.")
        return

    tracks = await search_tracks_by_tags(tags)
    if not tracks:
        await msg.edit(f"💀 No songs answered Brook's call for: `{', '.join(tags)}`")
        return

    tags_str = "_".join(tags)[:20]
    text = (
        "🎧 Brook's mood search results\n"
        f"Felt like: `{', '.join(tags)}`\n"
        f"Found: `{len(tracks)} tracks`\n\n"
        "Tap a result to drop it into chat and let the Soul King perform it."
    )
    keyboard = build_results_keyboard(tracks, page=1, query_id="ms", tags_str=tags_str)
    await cache.set(f"mood_results_ms_{tags_str}", json.dumps(tracks), ex=1800)
    await msg.edit(text, reply_markup=keyboard)


MOOD_CATEGORIES = {
    "Happy": ["happy", "playful", "upbeat", "cheerful"],
    "Sad": ["sad", "melancholic", "nostalgic", "emotional"],
    "Energetic": ["energetic", "powerful", "fast", "epic"],
    "Calm": ["calm", "relaxing", "peaceful", "ambient"],
    "Dark": ["dark", "tense", "mysterious", "suspense"],
    "Romantic": ["romantic", "love", "sweet", "passionate"],
}


@Client.on_message(filters.command("mooddiscovery") & (filters.private | filters.group))
@rate_limit
async def mooddiscovery_cmd(client: Client, message: Message):
    if not await _ensure_allowed_message(message):
        return

    buttons = []
    row = []
    for mood in MOOD_CATEGORIES.keys():
        row.append(InlineKeyboardButton(mood, callback_data=f"mood:{mood}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    await message.reply(
        "✨ Brook's mood parlor is open. Choose the feeling for tonight's performance:",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


@Client.on_callback_query(filters.regex(r"^mood:(.+)$"))
async def mood_callback(client: Client, query: CallbackQuery):
    if not await _ensure_allowed_callback(query):
        return

    mood = query.matches[0].group(1)
    if mood not in MOOD_CATEGORIES:
        await query.answer("Unknown mood category.", show_alert=True)
        return

    tags = MOOD_CATEGORIES[mood]
    buttons = []
    row = []
    for tag in tags:
        row.append(InlineKeyboardButton(tag.capitalize(), callback_data=f"moodtag:{tag}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton("Back", callback_data="mood_back")])

    await query.message.edit_text(
        f"🎻 {mood} vibes\n\nChoose the flavor Brook should chase:",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


@Client.on_callback_query(filters.regex(r"^mood_back$"))
async def mood_back_callback(client: Client, query: CallbackQuery):
    if not await _ensure_allowed_callback(query):
        return

    buttons = []
    row = []
    for mood in MOOD_CATEGORIES.keys():
        row.append(InlineKeyboardButton(mood, callback_data=f"mood:{mood}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    await query.message.edit_text(
        "✨ Brook's mood parlor is open. Choose the feeling for tonight's performance:",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


@Client.on_callback_query(filters.regex(r"^moodtag:(.+)$"))
async def tag_callback(client: Client, query: CallbackQuery):
    if not await _ensure_allowed_callback(query):
        return

    tag = query.matches[0].group(1)
    await query.answer(f"Searching for {tag}...")
    tracks = await search_tracks_by_tags([tag])

    if not tracks:
        await query.message.edit_text(
            f"💀 Brook could not find any songs for `{tag}`.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="mood_back")]]),
        )
        return

    text = (
        f"🎧 Brook's {tag.capitalize()} selection\n"
        f"Found: `{len(tracks)} tracks`\n\n"
        "Tap a result to drop it into chat and let Brook take the stage."
    )

    await cache.set(f"mood_results_md_{tag}", json.dumps(tracks), ex=1800)
    keyboard = build_results_keyboard(tracks, page=1, query_id="md", tags_str=tag)
    kb_list = list(keyboard.inline_keyboard)
    kb_list.append([InlineKeyboardButton("Back", callback_data="mood_back")])

    await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(kb_list))


@Client.on_callback_query(filters.regex(r"^moodpage:(.+):(\d+):(.+)$"))
async def page_callback(client: Client, query: CallbackQuery):
    if not await _ensure_allowed_callback(query):
        return

    query_id = query.matches[0].group(1)
    page = int(query.matches[0].group(2))
    tags_str = query.matches[0].group(3)

    cached = await cache.get(f"mood_results_{query_id}_{tags_str}")
    if not cached:
        await query.answer("Search results expired. Please search again.", show_alert=True)
        return

    try:
        tracks = json.loads(cached)
    except Exception:
        await query.answer("Error loading results.", show_alert=True)
        return

    text = (
        f"🎼 Brook's search ledger (page {page})\n"
        f"Tags: `{tags_str.replace('_', ', ')}`\n"
        f"Total: `{len(tracks)} tracks`"
    )
    keyboard = build_results_keyboard(tracks, page=page, query_id=query_id, tags_str=tags_str)

    if query_id == "md":
        kb_list = list(keyboard.inline_keyboard)
        kb_list.append([InlineKeyboardButton("Back", callback_data="mood_back")])
        keyboard = InlineKeyboardMarkup(kb_list)

    await query.message.edit_text(text, reply_markup=keyboard)
