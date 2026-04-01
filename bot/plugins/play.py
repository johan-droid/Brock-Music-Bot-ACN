"""
Play command — /play, /vplay
Brook/One Piece themed Now Playing card with:
  - Auto-cleaning (search msg deleted after N seconds, NP card deleted after track ends)
  - Live progress bar (updated every NP_UPDATE_INTERVAL seconds)
  - Inline playback controls open to all group members
  - Queue position display and auto-advance
"""

import re
import asyncio
import logging
from typing import Optional

from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.enums import ParseMode
from pyrogram.errors import MessageNotModified, MessageDeleteForbidden

from bot.utils.permissions import rate_limit, require_member, require_admin, get_permission_level
from bot.utils.formatters import format_duration, truncate_text
from bot.utils.thumbnails import generate_np_thumbnail
from bot.utils.title_detector import conflict_resolver, normalize_text
from bot.utils.progress_tracker import progress_tracker
from bot.utils.cache import cache
from bot.platforms import extract_audio
from bot.platforms import youtube as yt_module
from bot.core.queue import queue_manager
from bot.core.call import call_manager
from bot.core.bot import bot_client
from bot.core.music_backend import music_backend, Track
from config import config

logger = logging.getLogger(__name__)

# ── Brook quote bank ──────────────────────────────────────────────────────────
_BROOK_QUOTES = [
    "\"Music connects the living and the dead... good thing I'm both! Yohohoho!\"",
    "\"Even without a heart I can feel the rhythm! Yohohoho!\"",
    "\"A sword through the chest? Please, I don't even have a chest! Yohohoho!\"",
    "\"Music is the medicine of the soul — and I'm already dead, so double dose!\"",
    "\"Bink's Sake... the song that sails across the seas of time!\"",
    "\"I may be bones, but my music has flesh and blood! Yohohoho!\"",
    "\"May I see your panties? Yohoho— I mean, enjoy the music!\"",
    "\"I'm so happy to be alive! Even though I'm already dead! Yohohoho!\"",
    "\"The Soul King has arrived to grace your ears! Yohohoho!\"",
    "\"Loneliness is no longer my partner, for I have your music!\"",
]

_BROOK_QUOTE_IDX = [0]


def _next_quote() -> str:
    q = _BROOK_QUOTES[_BROOK_QUOTE_IDX[0] % len(_BROOK_QUOTES)]
    _BROOK_QUOTE_IDX[0] += 1
    return q


# Source badges
_SOURCE_BADGE = {
    "youtube": "▶️ YouTube",
    "spotify": "🟢 Spotify",
    "soundcloud": "☁️ SoundCloud",
    "jiosaavn": "🎵 JioSaavn",
    "ytmusic": "🎵 YT Music",
    "audiomack": "🎵 Audiomack",
    "telegram": "✈️ Telegram",
    "radio": "🔴 LIVE Radio",
}

# ── Background tasks ──────────────────────────────────────────────────────────
# chat_id → asyncio.Task for progress bar updates
_progress_tasks: dict = {}
# chat_id → asyncio.Task for NP card auto-deletion
_autoclean_tasks: dict = {}


def _cancel_task(task_dict: dict, chat_id: int) -> None:
    task = task_dict.pop(chat_id, None)
    if task and not task.done():
        task.cancel()


# ── /play ─────────────────────────────────────────────────────────────────────

@Client.on_message(filters.command(["play"]) & filters.group)
@require_member
@rate_limit
async def play_cmd(client: Client, message: Message):
    """Handle /play — open to all group members."""
    chat_id = message.chat.id
    user_id = message.from_user.id if message.from_user else None
    if not user_id:
        return

    query = " ".join(message.command[1:]) if len(message.command) > 1 else ""

    # Reply-to audio/voice/video
    if not query and message.reply_to_message:
        reply = message.reply_to_message
        if reply.audio or reply.voice or reply.video:
            from bot.platforms.telegram import TelegramAudioHandler
            track = await TelegramAudioHandler().extract_from_message(reply)
            if track:
                await add_track_and_play(message, chat_id, user_id, track)
                return

    if not query:
        await message.reply(
            "💀 **Yohohoho! No song name given!**\n\n"
            "Usage: <code>/play &lt;song name or URL&gt;</code>\n"
            "<i>\"Even a skeleton needs something to play!\"</i>",
            parse_mode=ParseMode.HTML,
        )
        return

    # URL detection
    _url_rx = re.compile(
        r"^(https?://)?(www\.)?(youtube\.com|youtu\.be|"
        r"open\.spotify\.com|soundcloud\.com|"
        r"www\.jiosaavn\.com|open\.jiosaavn\.com)/.+$",
        re.IGNORECASE,
    )

    search_msg = await message.reply(
        "💀 <i>The Soul King is scouting the seas for your song...</i>",
        parse_mode=ParseMode.HTML,
    )

    try:
        if _url_rx.match(query):
            # Direct URL
            track = await asyncio.wait_for(extract_audio(query, message), timeout=35)
            if not track:
                await search_msg.edit("❌ <b>Couldn't extract audio from that URL!</b>\n<i>\"Even I couldn't find treasure there! Yohohoho!\"</i>", parse_mode=ParseMode.HTML)
                return
            await add_track_and_play(message, chat_id, user_id, track, search_msg)

        else:
            # Text search with conflict detection using unified backend
            result = await conflict_resolver.search_with_conflicts(
                query,
                lambda q: music_backend.search(q, limit=5),
                max_results=5,
            )

            if result["status"] == "not_found":
                await search_msg.edit(
                    "💀 <b>No songs found!</b>\n"
                    "<i>\"The seas are empty of that melody... Yohohoho!\"</i>",
                    parse_mode=ParseMode.HTML,
                )
                return

            if result["status"] == "conflict":
                await _show_conflict_options(message, chat_id, user_id, result["conflicts"], search_msg)
                return

            # Single match
            raw = result["selected"]
            # Convert Track object to dict using the unified helper
            if isinstance(raw, Track):
                track = raw.to_dict()
            else:
                track = dict(raw)

            # For JioSaavn the stream_url/url is the encrypted URL — do NOT pre-resolve here.
            # start_playback will call music_backend.get_stream_url with the encrypted URL.
            # For YouTube/SoundCloud the url is already a real stream URL from search metadata.

            await add_track_and_play(message, chat_id, user_id, track, search_msg)

    except asyncio.TimeoutError:
        await search_msg.edit("⏱ <b>Search timed out!</b>\n<i>\"The seas were too vast this time! Try again, Yohoho!\"</i>", parse_mode=ParseMode.HTML)
    except Exception as exc:
        logger.exception("play_cmd failed")
        await search_msg.edit(f"❌ <b>Error:</b> <code>{str(exc)[:120]}</code>", parse_mode=ParseMode.HTML)


# ── /vplay ────────────────────────────────────────────────────────────────────

@Client.on_message(filters.command(["vplay"]) & filters.group)
@require_admin
@rate_limit
async def vplay_cmd(client: Client, message: Message):
    """Handle /vplay — video mode, admin only."""
    chat_id = message.chat.id
    user_id = message.from_user.id if message.from_user else None
    if not user_id:
        return

    query = " ".join(message.command[1:]) if len(message.command) > 1 else ""

    if not query and message.reply_to_message and message.reply_to_message.video:
        from bot.platforms.telegram import TelegramAudioHandler
        track = await TelegramAudioHandler().extract_from_message(message.reply_to_message)
        if track:
            track["is_video"] = True
            await add_track_and_play(message, chat_id, user_id, track)
            return

    if not query:
        await message.reply("❌ Usage: <code>/vplay &lt;YouTube URL or title&gt;</code>", parse_mode=ParseMode.HTML)
        return

    search_msg = await message.reply("🎬 <i>The Soul King is loading the video stage...</i>", parse_mode=ParseMode.HTML)

    try:
        track = await asyncio.wait_for(extract_audio(query, message), timeout=35)
        if not track:
            await search_msg.edit("❌ <b>Could not extract video!</b>", parse_mode=ParseMode.HTML)
            return
        track["is_video"] = True
        await add_track_and_play(message, chat_id, user_id, track, search_msg)
    except asyncio.TimeoutError:
        await search_msg.edit("⏱ <b>Search timed out!</b>", parse_mode=ParseMode.HTML)
    except Exception as exc:
        logger.exception("vplay_cmd failed")
        await search_msg.edit(f"❌ <b>Error:</b> <code>{str(exc)[:120]}</code>", parse_mode=ParseMode.HTML)


# ── Core playback pipeline ────────────────────────────────────────────────────

async def add_track_and_play(
    message: Message,
    chat_id: int,
    user_id: int,
    track: dict,
    search_msg: Optional[Message] = None,
) -> None:
    """Add track to queue and start if idle. Handle search_msg auto-clean."""
    status = await queue_manager.get_status(chat_id)
    is_playing = status in ("playing", "paused")

    # Pass track_id and uploader to queue_manager to ensure reliable stream resolution
    position = await queue_manager.add_to_queue(
        chat_id=chat_id,
        title=track.get("title", "Unknown"),
        url=track.get("url", ""),
        duration=track.get("duration", 0),
        thumb=track.get("thumbnail") or track.get("thumb"),
        requested_by=user_id,
        source=track.get("source", "youtube"),
        track_id=track.get("id") or track.get("track_id"),
        uploader=track.get("uploader") or track.get("artist"),
    )

    # Auto-delete search msg after SEARCH_MSG_AUTOCLEAN seconds
    async def _cleanup_search():
        await asyncio.sleep(config.SEARCH_MSG_AUTOCLEAN)
        try:
            if search_msg:
                await search_msg.delete()
        except Exception:
            pass

    if search_msg:
        asyncio.create_task(_cleanup_search())

    if is_playing:
        # Show queue-added card
        duration_str = format_duration(track.get("duration", 0))
        source = _SOURCE_BADGE.get(track.get("source", "youtube"), "🎵")
        requester = message.from_user.mention if message.from_user else "Someone"

        q_total = await queue_manager.get_queue_length(chat_id)

        text = (
            f"🎸 <b>Added to Queue!</b> <i>Yohohoho!</i>\n\n"
            f"📌 <b>Position:</b> #{position}\n"
            f"🎵 <b>Track:</b> {truncate_text(track.get('title','Unknown'), 52)}\n"
            f"⏱ <b>Duration:</b> <code>{duration_str}</code>\n"
            f"🔊 <b>Source:</b> {source}\n"
            f"👤 <b>Added by:</b> {requester}\n"
            f"📋 <b>Queue size:</b> {q_total} track(s)\n\n"
            f"<i>\"Even a skeleton needs a good setlist! Yohoho!\"</i>"
        )

        try:
            thumb = track.get("thumbnail") or track.get("thumb")
            if thumb:
                sent = await message.reply_photo(photo=thumb, caption=text, parse_mode=ParseMode.HTML)
            else:
                sent = await message.reply(text, parse_mode=ParseMode.HTML)
            # Auto-clean queue-added message after 30s
            asyncio.create_task(_autoclean_msg(sent, 30))
        except Exception as exc:
            logger.warning(f"Queue-added card failed: {exc}")

    else:
        # Start immediately
        await start_playback(chat_id)


async def start_playback(chat_id: int) -> None:
    """Dequeue next track and start streaming."""
    try:
        track = await queue_manager.get_next(chat_id)
        if not track:
            await queue_manager.set_status(chat_id, "idle")
            # If no more tracks are queued, auto-leave VC to keep the call assistant clean.
            try:
                await call_manager.leave_call(chat_id)
                logger.info(f"Auto-left VC for chat {chat_id} after queue drained")
            except Exception as exc:
                logger.debug(f"Auto-leave VC failed for chat {chat_id}: {exc}")
            return

        await queue_manager.set_status(chat_id, "playing")

        url = track.get("url", "")
        # Always try to resolve/refresh stream URL for stability
        stream_payload = await music_backend.get_stream_payload(Track(
            title=track.get("title", ""),
            artist=track.get("uploader", ""),
            duration=track.get("duration", 0),
            stream_url=url,
            source=track.get("source", "youtube"),
            track_id=track.get("id")
        ))

        if stream_payload and stream_payload.get("url"):
            url = stream_payload["url"]
            effective_source = stream_payload.get("source", track.get("source", "youtube"))
            track["source"] = effective_source
        else:
            effective_source = track.get("source", "youtube")
            
        if not url:
            logger.error(f"Track has no URL and resolution failed in chat {chat_id}: {track}")
            await queue_manager.set_status(chat_id, "idle")
            return

        is_video = track.get("is_video", False)
        
        # Prepare source-specific headers (e.g. JioSaavn CDN referer requirement)
        headers = (stream_payload or {}).get("headers") if stream_payload else None
        if headers is None:
            headers = music_backend.get_source_headers(effective_source)

        # Use consolidated play method
        try:
            await call_manager.play(chat_id, url, video=is_video, headers=headers)
        except Exception as exc:
            logger.warning(f"Playback failed on initial URL for '{track.get('title', 'unknown')}' in {chat_id}: {exc}")

            # Retry with fallback resolver pipeline (try to re-resolve track URL to a fresh stream URL)
            fallback_payload = await music_backend._resolve_fallback_payload(Track(
                title=track.get("title", ""),
                artist=track.get("uploader", ""),
                duration=track.get("duration", 0),
                stream_url=track.get("url", ""),
                source=track.get("source", "youtube"),
                track_id=track.get("id")
            ))

            if fallback_payload and fallback_payload.get("url"):
                fallback_url = fallback_payload["url"]
                fallback_headers = fallback_payload.get("headers")
                fallback_source = fallback_payload.get("source")
                if fallback_source:
                    track["source"] = fallback_source

                try:
                    await call_manager.play(chat_id, fallback_url, video=is_video, headers=fallback_headers)
                    logger.info(f"Fallback playback succeeded for '{track.get('title','unknown')}' in {chat_id}")
                    # Update URL for tracking if needed
                    url = fallback_url
                    headers = fallback_headers
                except Exception as exc2:
                    logger.error(f"Fallback playback failed for '{track.get('title','unknown')}' in {chat_id}: {exc2}")
                    raise
            else:
                logger.error(f"No fallback URL resolved for '{track.get('title','unknown')}' in {chat_id}")
                raise

        # Start progress tracking
        progress_tracker.start(chat_id, seek=int(track.get("position", 0)))

        # Send Now Playing card
        await _send_now_playing(chat_id, track)

        logger.info(f"Playback started in {chat_id}: {track.get('title', '?')[:50]}")

    except RuntimeError as exc:
        # User-friendly VC errors
        await queue_manager.set_status(chat_id, "idle")
        try:
            await bot_client.send_message(chat_id, f"💀 <b>{exc}</b>", parse_mode=ParseMode.HTML)
        except Exception:
            pass

    except Exception as exc:
        logger.exception(f"start_playback failed in {chat_id}")
        await queue_manager.set_status(chat_id, "idle")


async def on_track_end(chat_id: int) -> None:
    """Called when a track finishes. Handles loop mode and auto-advance."""
    logger.info(f"Track ended in {chat_id}")

    # Cancel progress updater
    _cancel_task(_progress_tasks, chat_id)

    # Schedule NP card auto-deletion
    old_msg_id = await cache.get_np_message(chat_id)
    if old_msg_id:
        asyncio.create_task(_autoclean_np(chat_id, int(old_msg_id), config.NP_AUTOCLEAN_DELAY))

    # Check loop mode
    import bot.utils.database as app_db
    try:
        group = await app_db.db.get_group(chat_id)
        loop_mode = (group or {}).get("settings", {}).get("loop_mode", "none")
    except Exception:
        loop_mode = "none"

    if loop_mode == "track":
        current = await queue_manager.get_current(chat_id)
        if current:
            await queue_manager.add_to_queue(
                chat_id=chat_id,
                title=current["title"],
                url=current["url"],
                duration=current["duration"],
                thumb=current.get("thumb"),
                requested_by=current.get("requested_by"),
                source=current.get("source", "youtube"),
                track_id=current.get("id"),
                uploader=current.get("uploader"),
            )

    await start_playback(chat_id)


# ── Now Playing card ──────────────────────────────────────────────────────────

def _np_buttons() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⏸ Pause", callback_data="pause"),
            InlineKeyboardButton("⏭ Skip", callback_data="skip"),
            InlineKeyboardButton("⏹ Stop", callback_data="stop"),
        ],
        [
            InlineKeyboardButton("🔁 Loop", callback_data="loop"),
            InlineKeyboardButton("🔀 Shuffle", callback_data="shuffle"),
            InlineKeyboardButton("📋 Queue", callback_data="queue"),
        ],
    ])


async def _send_now_playing(chat_id: int, track: dict) -> None:
    """Send the Brook-themed Now Playing card and start the progress updater."""
    # Cancel any existing progress task for this chat
    _cancel_task(_progress_tasks, chat_id)
    _cancel_task(_autoclean_tasks, chat_id)

    duration = int(track.get("duration") or 0)
    title = truncate_text(track.get("title", "Unknown"), 52)
    uploader = track.get("uploader", track.get("artist", "Unknown Artist"))
    source = _SOURCE_BADGE.get(track.get("source", "youtube"), "🎵")
    bar = progress_tracker.progress_bar(chat_id, duration)
    quote = _next_quote()

    q_size = await queue_manager.get_queue_length(chat_id)

    text = _build_np_text(title, uploader, source, bar, duration, q_size, quote)
    buttons = _np_buttons()

    try:
        # Try thumbnail first
        thumb = track.get("thumbnail") or track.get("thumb")
        thumb_data = None
        if thumb:
            try:
                thumb_data = await generate_np_thumbnail(
                    title=track.get("title", "Unknown"),
                    artist=uploader,
                    duration=duration,
                    position=0,
                    thumbnail_url=thumb,
                    source=track.get("source", "youtube"),
                )
            except Exception:
                pass

        if thumb_data:
            msg = await bot_client.send_photo(
                chat_id=chat_id,
                photo=thumb_data,
                caption=text,
                reply_markup=buttons,
                parse_mode=ParseMode.HTML,
            )
        else:
            msg = await bot_client.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=buttons,
                parse_mode=ParseMode.HTML,
            )

        # Store message ID for progress updates and auto-clean
        await cache.set_np_message(chat_id, msg.id)

        # Start background progress updater
        task = asyncio.create_task(_progress_updater(chat_id, msg, track))
        _progress_tasks[chat_id] = task

    except Exception as exc:
        logger.error(f"send_now_playing failed in {chat_id}: {exc}")


def _build_np_text(title, uploader, source, bar, duration, q_remaining, quote) -> str:
    dur_str = format_duration(duration) if duration > 0 else "LIVE"
    queue_info = f"📋 <b>Up next:</b> {q_remaining} track(s) in queue" if q_remaining > 0 else "📋 <b>Queue:</b> This is the last track"

    return (
        "💀 <b>YOHOHOHO! The Soul King is performing!</b>\n\n"
        f"🎸 <b>{title}</b>\n"
        f"👤 {uploader}  ·  {source}\n\n"
        f"<code>{bar}</code>\n\n"
        f"{queue_info}\n\n"
        f"<i>{quote}</i>"
    )


async def _progress_updater(chat_id: int, msg: Message, track: dict) -> None:
    """Background task: edit NP card every NP_UPDATE_INTERVAL seconds."""
    duration = int(track.get("duration") or 0)
    title = truncate_text(track.get("title", "Unknown"), 52)
    uploader = track.get("uploader", track.get("artist", "Unknown Artist"))
    source = _SOURCE_BADGE.get(track.get("source", "youtube"), "🎵")
    quote = _next_quote()

    interval = max(10, config.NP_UPDATE_INTERVAL)

    try:
        while True:
            await asyncio.sleep(interval)

            # Stop if track ended or status changed
            status = await queue_manager.get_status(chat_id)
            if status not in ("playing", "paused"):
                break

            bar = progress_tracker.progress_bar(chat_id, duration)
            q_size = await queue_manager.get_queue_length(chat_id)
            text = _build_np_text(title, uploader, source, bar, duration, q_size, quote)

            try:
                await msg.edit_caption(text, reply_markup=_np_buttons(), parse_mode=ParseMode.HTML)
            except MessageNotModified:
                pass
            except Exception:
                # Try editing as text (photo messages use edit_caption, text messages use edit_text)
                try:
                    await msg.edit_text(text, reply_markup=_np_buttons(), parse_mode=ParseMode.HTML)
                except Exception:
                    break  # Message probably deleted

    except asyncio.CancelledError:
        pass
    except Exception as exc:
        logger.debug(f"Progress updater ended for {chat_id}: {exc}")


async def _autoclean_msg(msg: Message, delay: int) -> None:
    """Delete a message after `delay` seconds."""
    await asyncio.sleep(delay)
    try:
        await msg.delete()
    except Exception:
        pass


async def _autoclean_np(chat_id: int, msg_id: int, delay: int) -> None:
    """Delete the NP card after `delay` seconds, then clear cache."""
    await asyncio.sleep(delay)
    try:
        await bot_client.delete_messages(chat_id, msg_id)
    except Exception:
        pass
    await cache.clear_np_message(chat_id)


# ── Conflict resolution UI ────────────────────────────────────────────────────

_pending_conflicts: dict = {}  # chat_id → {user_id → {tracks, original_msg}}

# Source number emojis for a clean numbered list
_NUM_EMOJI = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]
_SOURCE_ICON = {
    "youtube":    "▶️",
    "jiosaavn":   "🎵",
    "soundcloud": "☁️",
    "spotify":    "🟢",
    "telegram":   "✈️",
}


async def _safe_edit(
    msg: Message,
    text: str,
    reply_markup=None,
    max_len: int = 4000,
) -> None:
    """
    Edit a message, handling:
    - Telegram 4096-char message limit (truncated gracefully)
    - MessageNotModified (silently ignored)
    - FloodWait (back-off once then retry)
    - Any other error (logged, not raised)
    """
    from pyrogram.errors import MessageNotModified, FloodWait
    if len(text) > max_len:
        text = text[: max_len - 4] + "\n…"

    kwargs = {"parse_mode": ParseMode.HTML}
    if reply_markup is not None:
        kwargs["reply_markup"] = reply_markup

    for attempt in range(2):
        try:
            await msg.edit(text, **kwargs)
            return
        except MessageNotModified:
            return
        except FloodWait as fw:
            if attempt == 0:
                await asyncio.sleep(min(fw.value, 10))
            else:
                logger.warning(f"FloodWait on edit: {fw.value}s — giving up")
                return
        except Exception as e:
            logger.warning(f"Message edit failed: {e}")
            return


def _get_track_fields(t) -> dict:
    """Normalise a Track object or dict into a flat dict of display fields."""
    if hasattr(t, "title"):
        return {
            "title":   t.title,
            "dur":     t.duration,
            "sim":     getattr(t, "_similarity", 0.0),
            "artist":  getattr(t, "artist", getattr(t, "uploader", "Unknown")),
            "source":  getattr(t, "source", "youtube"),
        }
    return {
        "title":  t.get("title", "?"),
        "dur":    t.get("duration", 0),
        "sim":    t.get("_similarity", 0.0),
        "artist": t.get("uploader") or t.get("artist") or t.get("primary_artists") or "Unknown",
        "source": t.get("source", "youtube"),
    }


async def _show_conflict_options(
    message: Message,
    chat_id: int,
    user_id: int,
    conflicts: list,
    search_msg: Message,
) -> None:
    """Display a modern, info-rich track-selection menu."""
    tracks = conflicts[:5]

    # ── Buttons (one per row for legibility) ───────────────────────────────
    # callback_data: "ps:N" (play-select index N) — always < 64 bytes
    button_rows = []
    for i, t in enumerate(tracks):
        f = _get_track_fields(t)
        icon  = _SOURCE_ICON.get(f["source"], "🎵")
        label = truncate_text(f["title"], 28)
        num   = _NUM_EMOJI[i]
        button_rows.append(
            [InlineKeyboardButton(f"{num} {icon} {label}", callback_data=f"ps:{i}")]
        )
    button_rows.append([InlineKeyboardButton("❌  Cancel", callback_data="play_cancel")])

    # ── Message body ────────────────────────────────────────────────────────
    requester = message.from_user.first_name if message.from_user else "Someone"
    header = (
        f"🎼 <b>Found {len(tracks)} matches!</b>  <i>Pick wisely, {requester}!</i>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    )

    lines = []
    for i, t in enumerate(tracks):
        f = _get_track_fields(t)
        dur_str = format_duration(f["dur"]) if f["dur"] > 0 else "—"
        src_badge = _SOURCE_BADGE.get(f["source"], "🎵")
        star = " ⭐" if f["sim"] > 0.85 else ""
        num  = _NUM_EMOJI[i]

        artist_str = truncate_text(f["artist"], 28)
        title_str  = truncate_text(f["title"],  42)

        lines.append(
            f"{num} <b>{title_str}</b>{star}\n"
            f"    ┣ 👤 {artist_str}\n"
            f"    ┗ ⏱ {dur_str}  {src_badge}\n"
        )

    text = header + "\n".join(lines)

    # ── Store pending state ─────────────────────────────────────────────────
    _pending_conflicts[chat_id] = {
        user_id: {
            "tracks": tracks,
            "original_msg": search_msg,
            "user_mention": message.from_user.mention if message.from_user else "User",
        }
    }

    await _safe_edit(search_msg, text, InlineKeyboardMarkup(button_rows))


# ── Export helpers for callbacks.py ──────────────────────────────────────────

async def get_pending_conflict(chat_id: int, user_id: int) -> Optional[dict]:
    return (_pending_conflicts.get(chat_id) or {}).get(user_id)


async def resolve_conflict(chat_id: int, user_id: int, index: int, message: Message) -> None:
    """Called from callbacks.py when user picks a track from the conflict list."""
    conflict = (_pending_conflicts.get(chat_id) or {}).get(user_id)
    if not conflict:
        return

    tracks = conflict.get("tracks", [])
    if index >= len(tracks):
        return

    raw = tracks[index]
    orig_msg = conflict.get("original_msg")

    # Convert Track object to standard dict (preserves encrypted_url in 'url' field)
    if isinstance(raw, Track):
        track = raw.to_dict()
    else:
        track = dict(raw)

    # For non-JioSaavn sources, try to fill in missing metadata via extract_audio
    if track.get("source", "youtube") != "jiosaavn" and track.get("duration", 0) == 0:
        track_input = track.get("url") or track.get("id") or track.get("track_id")
        if track_input:
            try:
                new_data = await asyncio.wait_for(
                    extract_audio(track_input, None),
                    timeout=35,
                )
                if new_data:
                    track.update(new_data)
            except Exception:
                pass  # Non-critical — playback still works without pre-resolved metadata

    # Clean up pending conflict
    _pending_conflicts.get(chat_id, {}).pop(user_id, None)

    await add_track_and_play(message, chat_id, user_id, track, orig_msg)
