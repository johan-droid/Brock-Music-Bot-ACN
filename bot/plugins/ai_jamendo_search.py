import re
import math
import json
import httpx
import asyncio
import logging
from typing import List, Dict, Any, Optional

from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pyrogram.enums import ParseMode

from bot.utils.cache import cache
from config import config
from bot.utils.permissions import rate_limit, get_permission_level
from bot.platforms.jamendo_embedded import DEFAULT_JAMENDO_CLIENT_ID, JamendoEmbedded

logger = logging.getLogger(__name__)


def _is_group_chat(chat) -> bool:
    return "group" in str(getattr(chat, "type", "")).lower()


async def _ensure_allowed_message(message: Message) -> bool:
    if not _is_group_chat(message.chat):
        return True

    chat_id = message.chat.id
    user_id = message.from_user.id if message.from_user else None
    if config.BOUND_GROUP_ID is not None and chat_id != config.BOUND_GROUP_ID:
        await message.reply("⛔ This bot is bound to a different group and cannot be used here.")
        return False
    if not user_id or await get_permission_level(user_id, chat_id) < 1:
        await message.reply("⛔ You are not allowed to use this bot.")
        return False
    return True


async def _ensure_allowed_callback(query: CallbackQuery) -> bool:
    if not query.message or not _is_group_chat(query.message.chat):
        return True

    chat_id = query.message.chat.id
    user_id = query.from_user.id if query.from_user else None
    if config.BOUND_GROUP_ID is not None and chat_id != config.BOUND_GROUP_ID:
        await query.answer("⛔ This bot is bound to a different group.", show_alert=True)
        return False
    if not user_id or await get_permission_level(user_id, chat_id) < 1:
        await query.answer("⛔ You are not allowed to use this bot.", show_alert=True)
        return False
    return True

# Try config first, then use the embedded no-env Jamendo client ID.
JAMENDO_CLIENT_ID = getattr(config, "JAMENDO_CLIENT_ID", None) or DEFAULT_JAMENDO_CLIENT_ID
JAMENDO_API_BASE = "https://api.jamendo.com/v3.0"
jamendo_embedded = JamendoEmbedded(client_id=JAMENDO_CLIENT_ID)

DEFAULT_TAGS = [
    "happy", "upbeat", "energetic", "chill", "ambient", "calm", "rock",
    "pop", "jazz", "classical", "electronic", "dance", "acoustic", "piano",
    "guitar", "focus", "party", "romantic", "sad", "dark",
]

# --- Vocabulary & Search ---

async def fetch_jamendo_tags() -> List[str]:
    """Fetch Jamendo tag vocabulary and cache for 7 days."""
    cache_key = "jamendo_tags_vocabulary"
    cached = await cache.get(cache_key)
    if cached:
        try:
            return json.loads(cached)
        except Exception:
            pass

    tags = []
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{JAMENDO_API_BASE}/tags/", params={
                "client_id": JAMENDO_CLIENT_ID,
                "limit": 200,
                "order": "weight_desc"
            })
            if resp.status_code == 200:
                data = resp.json()
                if "results" in data:
                    tags = [t.get("name") for t in data["results"] if t.get("name")]

        if tags:
            # Cache for 7 days (7 * 24 * 3600 = 604800)
            await cache.set(cache_key, json.dumps(tags), ex=604800)
    except Exception as e:
        logger.error(f"Failed to fetch Jamendo tags: {e}")

    return tags or DEFAULT_TAGS


def _embedded_to_api_track(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": str(item.get("id", "")),
        "name": item.get("title", "Unknown Title"),
        "artist_name": item.get("artist", "Unknown Artist"),
        "duration": int(item.get("duration", 0)),
        "audio": item.get("audio_url", ""),
        "image": item.get("thumbnail_url", ""),
        "source": "jamendo",
    }

def map_keywords_to_tags(query: str, vocabulary: List[str]) -> List[str]:
    """Map natural language input to Jamendo tags using a simple scoring algorithm."""
    if not vocabulary:
        # Fallback to simple splitting if vocabulary fails to load
        return [word.lower() for word in re.findall(r'\b\w+\b', query) if len(word) > 2][:3]

    words = [w.lower() for w in re.findall(r'\b\w+\b', query)]

    matched_tags = []
    for word in words:
        if len(word) < 3:
            continue

        # Exact match
        if word in vocabulary:
            matched_tags.append(word)
            continue

        # Partial match
        partials = [t for t in vocabulary if word in t or t in word]
        if partials:
            # Sort by length difference to find the closest match
            partials.sort(key=lambda t: abs(len(t) - len(word)))
            matched_tags.append(partials[0])

    # Return unique top 3 tags to avoid overly restrictive queries
    return list(dict.fromkeys(matched_tags))[:3]

async def search_jamendo_tracks(tags: List[str]) -> List[Dict[str, Any]]:
    """Search Jamendo tracks by tags, caching results for 10 minutes."""
    if not tags:
        return []

    tag_str = "+".join(tags)
    cache_key = f"jamendo_search_{tag_str}"

    cached = await cache.get(cache_key)
    if cached:
        try:
            return json.loads(cached)
        except Exception:
            pass

    results = []
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(f"{JAMENDO_API_BASE}/tracks/", params={
                "client_id": JAMENDO_CLIENT_ID,
                "tags": tag_str,
                "limit": 10,
                "include": "musicinfo",
                "imagesize": "200"
            })
            if resp.status_code == 200:
                data = resp.json()
                if "results" in data:
                    results = data["results"]

        if results:
            # Cache for 10 minutes (600 seconds)
            await cache.set(cache_key, json.dumps(results), ex=600)
    except Exception as e:
        logger.error(f"Jamendo search failed: {e}")

    if not results:
        fallback = await jamendo_embedded.search_by_genre(tags[0], limit=10)
        results = [_embedded_to_api_track(item) for item in fallback]
        if results:
            await cache.set(cache_key, json.dumps(results), ex=600)

    return results

# --- UI Helpers ---

def build_results_keyboard(tracks: List[Dict[str, Any]], page: int, query_id: str, tags_str: str) -> InlineKeyboardMarkup:
    """Build paginated keyboard for search results (5 per page)."""
    items_per_page = 5
    total_pages = math.ceil(len(tracks) / items_per_page)

    start_idx = (page - 1) * items_per_page
    end_idx = start_idx + items_per_page
    current_tracks = tracks[start_idx:end_idx]

    buttons = []
    for t in current_tracks:
        title = t.get('name', 'Unknown')
        artist = t.get('artist_name', 'Unknown')
        # We can't put full URLs or complex data in callback_data due to 64 bytes limit,
        # so we will use a switch_inline_query or just a play command insertion.
        # But for this requirement, we just present results. Let's make the button play the song via play command
        display = f"🎵 {title[:20]} - {artist[:15]}"
        buttons.append([InlineKeyboardButton(display, switch_inline_query_current_chat=f"{title} {artist}")])

    nav_buttons = []
    if page > 1:
        nav_buttons.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"jpage:{query_id}:{page-1}:{tags_str}"))
    if page < total_pages:
        nav_buttons.append(InlineKeyboardButton("More ➡️", callback_data=f"jpage:{query_id}:{page+1}:{tags_str}"))

    if nav_buttons:
        buttons.append(nav_buttons)

    return InlineKeyboardMarkup(buttons)

# --- Commands ---

@Client.on_message(filters.command("moodsearch") & (filters.private | filters.group))
@rate_limit
async def moodsearch_cmd(client: Client, message: Message):
    """Semantic search for music based on natural language input."""
    if not await _ensure_allowed_message(message):
        return

    if len(message.command) < 2:
        await message.reply(
            "🧠 **Jamendo AI Mood Search**\n\n"
            "Search for music by describing mood, tempo, or instruments!\n"
            "**Usage:** `/moodsearch <description>`\n"
            "**Example:** `/moodsearch upbeat acoustic guitar for sunny morning`"
        )
        return

    query = message.text.split(maxsplit=1)[1]
    msg = await message.reply("🔍 *Analyzing mood and searching Jamendo...*")

    vocabulary = await fetch_jamendo_tags()
    tags = map_keywords_to_tags(query, vocabulary)

    if not tags:
        await msg.edit("❌ Could not identify meaningful tags from your query. Try different words!")
        return

    tracks = await search_jamendo_tracks(tags)

    if not tracks:
        await msg.edit(f"❌ No tracks found for the identified mood tags: `{', '.join(tags)}`.\nTry something else!")
        return

    tags_str = "_".join(tags)[:20] # truncate to avoid callback_data limits

    text = (
        f"🎧 **Mood Search Results**\n"
        f"**Interpreted Tags:** `{', '.join(tags)}`\n"
        f"**Found:** `{len(tracks)} tracks`\n\n"
        "Tap a track to play it!"
    )

    keyboard = build_results_keyboard(tracks, page=1, query_id="ms", tags_str=tags_str)

    # Store full results temporarily in cache if needed for pagination
    await cache.set(f"jresults_ms_{tags_str}", json.dumps(tracks), ex=1800)

    await msg.edit(text, reply_markup=keyboard)


MOOD_CATEGORIES = {
    "Happy": ["euphoric", "cheerful", "playful", "happy", "upbeat"],
    "Sad": ["melancholic", "nostalgic", "sad", "depressing", "emotional"],
    "Energetic": ["energetic", "powerful", "epic", "dynamic", "fast"],
    "Calm": ["calm", "relaxing", "peaceful", "chill", "ambient"],
    "Dark": ["dark", "creepy", "tense", "mysterious", "suspense"],
    "Romantic": ["romantic", "love", "sweet", "passionate", "sensual"]
}

@Client.on_message(filters.command("mooddiscovery") & (filters.private | filters.group))
@rate_limit
async def mooddiscovery_cmd(client: Client, message: Message):
    """Interactive mood discovery."""
    if not await _ensure_allowed_message(message):
        return

    buttons = []
    row = []
    for mood in MOOD_CATEGORIES.keys():
        row.append(InlineKeyboardButton(mood, callback_data=f"jmood:{mood}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    await message.reply(
        "✨ **Discover Music by Mood** ✨\n\n"
        "Select a primary mood to explore Jamendo's curated vibes:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

@Client.on_callback_query(filters.regex(r"^jmood:(.+)$"))
async def mood_callback(client: Client, query: CallbackQuery):
    """Handle primary mood selection."""
    if not await _ensure_allowed_callback(query):
        return

    mood = query.matches[0].group(1)

    if mood not in MOOD_CATEGORIES:
        await query.answer("Unknown mood category.", show_alert=True)
        return

    subtags = MOOD_CATEGORIES[mood]

    buttons = []
    row = []
    for tag in subtags:
        row.append(InlineKeyboardButton(tag.capitalize(), callback_data=f"jtag:{tag}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    buttons.append([InlineKeyboardButton("🔙 Back to Moods", callback_data="jmood_back")])

    await query.message.edit_text(
        f"✨ **{mood} Vibes** ✨\n\nSelect a specific flavor:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

@Client.on_callback_query(filters.regex(r"^jmood_back$"))
async def mood_back_callback(client: Client, query: CallbackQuery):
    """Handle back to primary moods."""
    if not await _ensure_allowed_callback(query):
        return

    buttons = []
    row = []
    for mood in MOOD_CATEGORIES.keys():
        row.append(InlineKeyboardButton(mood, callback_data=f"jmood:{mood}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    await query.message.edit_text(
        "✨ **Discover Music by Mood** ✨\n\n"
        "Select a primary mood to explore Jamendo's curated vibes:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

@Client.on_callback_query(filters.regex(r"^jtag:(.+)$"))
async def tag_callback(client: Client, query: CallbackQuery):
    """Handle specific tag selection."""
    if not await _ensure_allowed_callback(query):
        return

    tag = query.matches[0].group(1)
    await query.answer(f"Searching for {tag} tracks...")

    tracks = await search_jamendo_tracks([tag])

    if not tracks:
        await query.message.edit_text(
            f"❌ No tracks found for `{tag}`.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="jmood_back")]])
        )
        return

    text = (
        f"🎧 **Mood Discovery: {tag.capitalize()}**\n"
        f"**Found:** `{len(tracks)} tracks`\n\n"
        "Tap a track to play it!"
    )

    # Cache results for pagination
    await cache.set(f"jresults_md_{tag}", json.dumps(tracks), ex=1800)

    keyboard = build_results_keyboard(tracks, page=1, query_id="md", tags_str=tag)
    # Add back button to the bottom
    kb_list = list(keyboard.inline_keyboard)
    kb_list.append([InlineKeyboardButton("🔙 Back to Moods", callback_data="jmood_back")])

    await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(kb_list))

@Client.on_callback_query(filters.regex(r"^jpage:(.+):(\d+):(.+)$"))
async def page_callback(client: Client, query: CallbackQuery):
    """Handle pagination for search results."""
    if not await _ensure_allowed_callback(query):
        return

    query_id = query.matches[0].group(1)
    page = int(query.matches[0].group(2))
    tags_str = query.matches[0].group(3)

    cached = await cache.get(f"jresults_{query_id}_{tags_str}")
    if not cached:
        await query.answer("Search results expired. Please search again.", show_alert=True)
        return

    try:
        tracks = json.loads(cached)
    except Exception:
        await query.answer("Error loading results.", show_alert=True)
        return

    text = (
        f"🎧 **Search Results** (Page {page})\n"
        f"**Tags:** `{tags_str.replace('_', ', ')}`\n"
        f"**Total Found:** `{len(tracks)} tracks`"
    )

    keyboard = build_results_keyboard(tracks, page=page, query_id=query_id, tags_str=tags_str)

    if query_id == "md":
        kb_list = list(keyboard.inline_keyboard)
        kb_list.append([InlineKeyboardButton("🔙 Back to Moods", callback_data="jmood_back")])
        keyboard = InlineKeyboardMarkup(kb_list)

    await query.message.edit_text(text, reply_markup=keyboard)
