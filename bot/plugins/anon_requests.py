import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

from pyrogram import Client, filters
from typing import Any, cast

Client = cast(Any, Client)
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pyrogram.enums import ParseMode
from pyrogram.errors import MessageDeleteForbidden

import bot.utils.database as app_db
from bot.utils.permissions import rate_limit, require_admin, require_member, get_permission_level
from bot.core.music_backend import music_backend
from bot.core.queue import queue_manager
from bot.plugins.play import start_playback

logger = logging.getLogger(__name__)


def _db():
    if app_db.db is None:
        raise RuntimeError("Database is not initialized")
    return app_db.db

# In-memory storage for active vote sessions and rate limits
# Structure: {message_id: {"chat_id": int, "track": dict, "yes_users": set, "no_users": set, "expired": bool}}
active_votes: Dict[int, Dict[str, Any]] = {}

# Structure: {user_id: [datetime, datetime, ...]}
rate_limits: Dict[int, List[datetime]] = {}

RATE_LIMIT_MAX = 5
RATE_LIMIT_WINDOW = timedelta(hours=1)


@Client.on_message(filters.command(["votemode"]) & filters.group & ~filters.forwarded)
@require_admin
@rate_limit(limit=3, interval=10)
async def votemode_cmd(client: Client, message: Message):
    """Toggle voting mode for the group."""
    chat_id = message.chat.id

    if len(message.command) < 2:
        group_data = await _db().get_group(chat_id)
        settings = group_data.get("settings", {})
        current = settings.get("voting_mode", False)
        status = "ON" if current else "OFF"
        await message.reply_text(f"🗳️ Voting mode is currently **{status}**.\nUsage: `/votemode on` or `/votemode off`")
        return

    mode = message.command[1].lower()
    if mode not in ["on", "off"]:
        await message.reply_text("❌ Invalid mode. Use `on` or `off`.")
        return

    is_on = mode == "on"
    await _db().update_group(chat_id, {"settings": {"voting_mode": is_on}})
    status = "ON 🗳️\nAll new song requests will require a group vote." if is_on else "OFF 🚫\nSong requests will be added immediately."
    await message.reply_text(f"Voting mode turned **{status}**")


@Client.on_message(filters.command(["anonplay"]) & filters.group & ~filters.forwarded)
@require_member
@rate_limit(limit=5, interval=3600)
async def anonplay_cmd(client: Client, message: Message):
    """Anonymous song request."""
    chat_id = message.chat.id
    user_id = message.from_user.id if message.from_user else None

    # Immediately delete the command message for anonymity
    try:
        await message.delete()
    except MessageDeleteForbidden:
        pass
    except Exception as e:
        logger.warning(f"Failed to delete anonplay message: {e}")

    if not user_id:
        return

    # Check rate limit
    now = datetime.now()
    user_requests = rate_limits.get(user_id, [])
    user_requests = [t for t in user_requests if now - t < RATE_LIMIT_WINDOW]
    if len(user_requests) >= RATE_LIMIT_MAX:
        # PM the user if possible
        try:
            await client.send_message(user_id, "⏳ You have reached the limit of 5 anonymous requests per hour. Please wait.")
        except Exception:
            pass
        return

    if len(message.command) < 2:
        try:
            await client.send_message(user_id, "❌ Please provide a song name. Example: `/anonplay Believer`")
        except Exception:
            pass
        return

    query = " ".join(message.command[1:])
    user_requests.append(now)
    rate_limits[user_id] = user_requests


    # Send privacy notice once per user
    if len(user_requests) == 1:
        try:
            await client.send_message(user_id, "🔒 Your anonymous request has been received. Your username will not be shown in the group, but it is logged internally for spam prevention. (You will only see this message once)")
        except Exception:
            pass


    # Search for the track
    results = await music_backend.search(query, limit=1)
    if not results:
        # Try to send a generic anonymous failed message in the chat
        await client.send_message(chat_id, f"🎵 Anonymous requested: **{query}** but it couldn't be found.")
        return

    # Standardize to dict format matching the rest of the app
    track_obj = results[0]
    track = {
        "id": track_obj.track_id,
        "track_id": track_obj.track_id,
        "title": track_obj.title,
        "url": track_obj.stream_url or getattr(track_obj, 'url', ''),
        "duration": getattr(track_obj, 'duration', 0) or 0,
        "thumbnail": getattr(track_obj, 'thumbnail', ''),
        "artist": track_obj.artist,
        "source": track_obj.source
    }

    # Check voting mode
    group_data = await _db().get_group(chat_id)
    settings = group_data.get("settings", {})
    voting_mode = settings.get("voting_mode", False)

    if voting_mode:
        await start_vote_session(client, chat_id, track, is_anonymous=True)
    else:
        # Enqueue immediately
        await client.send_message(chat_id, f"🎵 Anonymous requested: **{track['title']}** by {track['artist']}")

        await queue_manager.add_to_queue(
            chat_id=chat_id,
            title=track.get("title", "Unknown"),
            url=track.get("url", ""),
            duration=track.get("duration", 0),
            thumb=track.get("thumbnail") or track.get("thumb"),
            requested_by="Anonymous",
            source=track.get("source", "unknown"),
            track_id=track.get("id") or track.get("track_id"),
            uploader=track.get("uploader") or track.get("artist"),
        )

        status = await queue_manager.get_status(chat_id)
        if status == "idle":
            await start_playback(chat_id)

    # Log the anonymous request to DB
    try:
        db = _db()
        if hasattr(db, "client"):
            db.client.table("anon_requests").insert({"track_id": track.get("id"), "requested_by": str(user_id) if user_id else None, "chat_id": chat_id}).execute()
        else:
            conn = getattr(db, "conn", None) or getattr(db, "_get_conn", lambda: None)()
            if conn:
                def _db_op1():
                    try:
                        with conn.cursor() as cur:
                            cur.execute("INSERT INTO anon_requests (track_id, requested_by, chat_id) VALUES (%s, %s, %s)", (track.get("id"), str(user_id) if user_id else None, chat_id))
                        conn.commit()
                    except Exception:
                        conn.execute("INSERT INTO anon_requests (track_id, requested_by, chat_id) VALUES (?, ?, ?)", (track.get("id"), str(user_id) if user_id else None, chat_id))
                        if hasattr(conn, "commit"):
                            conn.commit()
                await asyncio.to_thread(_db_op1)
    except Exception as e:
        logger.warning(f"Failed to log anon request to DB: {e}")



async def start_vote_session(client: Client, chat_id: int, track: Dict[str, Any], requester_id: int = None, is_anonymous: bool = False):
    """Start a voting session for a track."""

    requester_text = "Anonymous" if is_anonymous else f"<a href='tg://user?id={requester_id}'>User</a>"

    text = (
        f"🗳️ **VOTE REQUIRED**\n\n"
        f"🎵 **{track.get('title', 'Unknown')}**\n"
        f"👤 Requested by: {requester_text}\n\n"
        f"⏳ You have 30 seconds to vote!"
    )

    markup = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("👍 Yes (0)", callback_data="vote_yes"),
            InlineKeyboardButton("👎 No (0)", callback_data="vote_no")
        ]
    ])

    msg = await client.send_message(chat_id, text, reply_markup=markup, parse_mode=ParseMode.HTML)

    vote_key = f"{chat_id}_{msg.id}"
    active_votes[vote_key] = {
        "chat_id": chat_id,
        "track": track,
        "yes_users": set(),
        "no_users": set(),
        "expired": False,
        "requester_id": requester_id,
        "is_anonymous": is_anonymous
    }

    # Store in DB async (fire and forget wrapper since we don't strictly need to wait for it)

    try:
        db = _db()
        if hasattr(db, "client"):
            # Supabase
            db.client.table("vote_sessions").insert({"message_id": msg.id, "track_id": track.get("id"), "chat_id": chat_id, "yes_votes": 0, "no_votes": 0, "expired": False}).execute()
        else:
            # SQLite / Neon
            conn = getattr(db, "conn", None) or getattr(db, "_get_conn", lambda: None)()
            if conn:
                def _db_op2():
                    try:
                        # neon
                        with conn.cursor() as cur:
                            cur.execute("INSERT INTO vote_sessions (message_id, track_id, chat_id) VALUES (%s, %s, %s)", (msg.id, track.get("id"), chat_id))
                        conn.commit()
                    except Exception:
                        # sqlite
                        conn.execute("INSERT INTO vote_sessions (message_id, track_id, chat_id) VALUES (?, ?, ?)", (msg.id, track.get("id"), chat_id))
                        if hasattr(conn, "commit"):
                            conn.commit()
                await asyncio.to_thread(_db_op2)
    except Exception as e:
        logger.warning(f"Failed to insert vote session to DB: {e}")


    # Start timer
    asyncio.create_task(vote_timeout(client, vote_key, chat_id, track, msg.id))


@Client.on_callback_query(filters.regex(r"^vote_(yes|no)$"))
async def on_vote_callback(client: Client, callback_query: CallbackQuery):
    """Handle vote button clicks."""
    msg_id = callback_query.message.id
    chat_id = callback_query.message.chat.id
    vote_key = f"{chat_id}_{msg_id}"
    user_id = callback_query.from_user.id
    if await get_permission_level(user_id, chat_id) < 1:
        await callback_query.answer("You are not allowed to vote.", show_alert=True)
        return

    if vote_key not in active_votes:
        await callback_query.answer("Voting session has expired.", show_alert=True)
        return

    session = active_votes[vote_key]
    if session["expired"]:
        await callback_query.answer("Voting session has ended.", show_alert=True)
        return

    vote_type = callback_query.data.split("_")[1]

    # Check if user already voted this way
    if vote_type == "yes":
        if user_id in session["yes_users"]:
            await callback_query.answer("You already voted Yes.", show_alert=True)
            return
        session["yes_users"].add(user_id)
        if user_id in session["no_users"]:
            session["no_users"].remove(user_id)
    else:
        if user_id in session["no_users"]:
            await callback_query.answer("You already voted No.", show_alert=True)
            return
        session["no_users"].add(user_id)
        if user_id in session["yes_users"]:
            session["yes_users"].remove(user_id)

    # Update buttons
    yes_count = len(session["yes_users"])
    no_count = len(session["no_users"])

    markup = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(f"👍 Yes ({yes_count})", callback_data="vote_yes"),
            InlineKeyboardButton(f"👎 No ({no_count})", callback_data="vote_no")
        ]
    ])

    try:
        await callback_query.message.edit_reply_markup(reply_markup=markup)
        await callback_query.answer(f"Voted {vote_type.title()}!")
    except Exception:
        await callback_query.answer("Vote registered.", show_alert=False)

    try:
        db = _db()
        if hasattr(db, "client"):
            db.client.table("vote_sessions").update({"yes_votes": yes_count, "no_votes": no_count}).eq("message_id", msg_id).execute()
        else:
            conn = getattr(db, "conn", None) or getattr(db, "_get_conn", lambda: None)()
            if conn:
                def _db_op3():
                    try:
                        with conn.cursor() as cur:
                            cur.execute("UPDATE vote_sessions SET yes_votes=%s, no_votes=%s WHERE message_id=%s", (yes_count, no_count, msg_id))
                        conn.commit()
                    except Exception:
                        conn.execute("UPDATE vote_sessions SET yes_votes=?, no_votes=? WHERE message_id=?", (yes_count, no_count, msg_id))
                        if hasattr(conn, "commit"):
                            conn.commit()
                await asyncio.to_thread(_db_op3)
    except Exception:
        pass


async def vote_timeout(client: Client, vote_key: str, chat_id: int, track: Dict[str, Any], msg_id: int):
    """Process voting result after timeout."""
    await asyncio.sleep(30)

    if vote_key not in active_votes:
        return

    session = active_votes[vote_key]
    session["expired"] = True
    try:
        db = _db()
        if hasattr(db, "client"):
            db.client.table("vote_sessions").update({"expired": True}).eq("message_id", msg_id).execute()
        else:
            conn = getattr(db, "conn", None) or getattr(db, "_get_conn", lambda: None)()
            if conn:
                def _db_op4():
                    try:
                        with conn.cursor() as cur:
                            cur.execute("UPDATE vote_sessions SET expired=TRUE WHERE message_id=%s", (msg_id,))
                        conn.commit()
                    except Exception:
                        conn.execute("UPDATE vote_sessions SET expired=1 WHERE message_id=?", (msg_id,))
                        if hasattr(conn, "commit"):
                            conn.commit()
                await asyncio.to_thread(_db_op4)
    except Exception:
        pass


    yes_count = len(session["yes_users"])
    no_count = len(session["no_users"])

    track_title = track.get("title", "Unknown")

    if yes_count > no_count and yes_count >= 3:
        # Accepted
        text = f"✅ **Added by popular demand!**\n🎵 **{track_title}**\n👍 {yes_count} | 👎 {no_count}"

        # Add to queue
        requester = "Anonymous" if session["is_anonymous"] else session["requester_id"]

        await queue_manager.add_to_queue(
            chat_id=chat_id,
            title=track.get("title", "Unknown"),
            url=track.get("url", ""),
            duration=track.get("duration", 0),
            thumb=track.get("thumbnail") or track.get("thumb"),
            requested_by=requester,
            source=track.get("source", "unknown"),
            track_id=track.get("id") or track.get("track_id"),
            uploader=track.get("uploader") or track.get("artist"),
        )

        status = await queue_manager.get_status(chat_id)
        if status == "idle":
            try:
                await start_playback(chat_id)
            except Exception as e:
                logger.error(f"Failed to start playback after vote: {e}")
    else:
        # Rejected
        text = f"❌ **Song rejected by vote.**\n🎵 **{track_title}**\n👍 {yes_count} | 👎 {no_count}"
        if yes_count < 3 and yes_count > no_count:
            text += "\n*(Not enough Yes votes, need at least 3)*"

    try:
        # Edit the original message to remove buttons
        await client.edit_message_text(chat_id=chat_id, message_id=msg_id, text=text, parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.warning(f"Failed to update vote message: {e}")

    # Clean up memory
    if vote_key in active_votes:
        del active_votes[vote_key]
