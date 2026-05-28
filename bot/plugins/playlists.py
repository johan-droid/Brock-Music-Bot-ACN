"""Collaborative playlist commands backed by the external track service."""

import logging
from typing import Any, cast

import bot.utils.database as app_db
from pyrogram import Client, filters

Client = cast(Any, Client)
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.core.music_backend import music_backend
from bot.core.queue import queue_manager
from bot.plugins.play import start_playback
from bot.utils.permissions import rate_limit, require_member

logger = logging.getLogger(__name__)


def _db():
    if app_db.db is None:
        raise RuntimeError("Database is not initialized")
    return app_db.db


def _playlist_item_ref(item: dict) -> str:
    return str(
        item.get("track_id")
        or item.get("id")
        or item.get("jamendo_track_id")
        or item.get("url")
        or ""
    ).strip()


@Client.on_message(filters.command("plcreate") & filters.group)
@require_member
@rate_limit
async def plcreate_cmd(client: Client, message: Message):
    if not message.text or len(message.text.split()) < 2:
        return await message.reply_text("Usage: /plcreate <playlist_name>")

    name = message.text.split(maxsplit=1)[1].strip()
    user_id = message.from_user.id
    existing = await _db().get_playlist_by_name(name)
    if existing:
        return await message.reply_text(f"💀 A setlist named '{name}' already exists. Brook does not like duplicate posters, yohoho!")

    playlist_id = await _db().create_playlist(name, user_id)
    if playlist_id != -1:
        await message.reply_text(
            f"🎼 Created Brook's setlist **{name}**.\n\n"
            f"Archive ID: `{playlist_id}`\n"
            "Add tracks with `/pladd <playlist_name> <track query or URL>`."
        )
    else:
        await message.reply_text("💀 Brook dropped the sheet music. Failed to create that setlist.")


@Client.on_message(filters.command("pllist"))
@rate_limit
async def pllist_cmd(client: Client, message: Message):
    user_id = message.from_user.id
    playlists = await _db().get_user_playlists(user_id)
    if not playlists:
        return await message.reply_text("🎻 No saved setlists yet. Use `/plcreate <name>` and Brook will start a new archive.")

    text = "🎼 Brook's saved setlists:\n\n"
    for playlist in playlists:
        tracks = await _db().get_playlist_tracks(playlist["id"])
        collab_flag = "crew-open" if playlist.get("is_collaborative") else "captain-only"
        text += f"- **{playlist['name']}** (`{playlist['id']}`) - {len(tracks)} tracks - {collab_flag}\n"

    await message.reply_text(text)


@Client.on_message(filters.command("pladd") & filters.group)
@require_member
@rate_limit
async def pladd_cmd(client: Client, message: Message):
    if not message.text:
        return await message.reply_text("Usage: `/pladd <playlist_name> <track query or URL>`")

    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        return await message.reply_text("Usage: `/pladd <playlist_name> <track query or URL>`")

    playlist_name = parts[1]
    query = parts[2].strip()
    user_id = message.from_user.id

    playlist = await _db().get_playlist_by_name(playlist_name)
    if not playlist:
        return await message.reply_text(f"💀 No setlist named '{playlist_name}' was found in Brook's archive.")

    if playlist["creator_user_id"] != user_id and not playlist.get("is_collaborative"):
        is_sudo = await _db().is_sudo(user_id)
        if not is_sudo:
            return await message.reply_text("💀 That setlist is private to its captain. Brook cannot rewrite another musician's sheet music.")

    searching = await message.reply_text("🎻 Brook is searching the external music library for that tune...")
    try:
        results = await music_backend.search(query, limit=1)
    except Exception as exc:
        logger.error("Playlist add search failed for %r: %s", query, exc)
        return await searching.edit_text("💀 The music library is being stubborn. Brook could not fetch that tune right now.")

    if not results:
        return await searching.edit_text("💀 No matching tune answered Brook's call.")

    track = results[0]
    track_ref = track.track_id or track.stream_url or f"{track.title} {track.artist}"
    success = await _db().add_track_to_playlist(playlist["id"], str(track_ref), user_id)
    if success:
        await searching.edit_text(f"🎼 Added **{track.title}** by {track.artist} to **{playlist_name}**. A fine addition to tonight's setlist!")
    else:
        await searching.edit_text("💀 Brook fumbled the page turn. Failed to add that track.")


@Client.on_message(filters.command("plremove") & filters.group)
@require_member
@rate_limit
async def plremove_cmd(client: Client, message: Message):
    args = message.text.split()
    if len(args) < 3:
        return await message.reply_text("Usage: `/plremove <playlist_name> <position>`")

    playlist_name = args[1]
    try:
        position = int(args[2])
    except ValueError:
        return await message.reply_text("💀 Brook needs a numbered slot in the setlist, not a mystery.")

    user_id = message.from_user.id
    playlist = await _db().get_playlist_by_name(playlist_name)
    if not playlist:
        return await message.reply_text(f"💀 No setlist named '{playlist_name}' was found.")

    if playlist["creator_user_id"] != user_id and not playlist.get("is_collaborative"):
        is_sudo = await _db().is_sudo(user_id)
        if not is_sudo:
            return await message.reply_text("💀 Brook cannot remove tracks from another captain's private setlist.")

    success = await _db().remove_track_from_playlist(playlist["id"], position)
    if success:
        await message.reply_text(f"🎻 Removed the song at position {position} from **{playlist_name}**.")
    else:
        await message.reply_text("💀 That page would not budge. Failed to remove the track.")


@Client.on_message(filters.command("plcollab") & filters.group)
@require_member
@rate_limit
async def plcollab_cmd(client: Client, message: Message):
    args = message.text.split()
    if len(args) < 3 or args[2].lower() not in ["on", "off"]:
        return await message.reply_text("Usage: `/plcollab <playlist_name> <on|off>`")

    playlist_name = args[1]
    mode = args[2].lower() == "on"
    user_id = message.from_user.id

    playlist = await _db().get_playlist_by_name(playlist_name)
    if not playlist:
        return await message.reply_text(f"💀 No setlist named '{playlist_name}' was found.")
    if playlist["creator_user_id"] != user_id:
        return await message.reply_text("💀 Only the captain who wrote this setlist can decide whether the whole crew may edit it.")

    success = await _db().toggle_playlist_collab(playlist["id"], mode)
    if success:
        state = "crew-open" if mode else "captain-only"
        await message.reply_text(f"🎼 Setlist **{playlist_name}** is now {state}.")
    else:
        await message.reply_text("💀 Brook could not rewrite the setlist rules just now.")


@Client.on_message(filters.command("plshare") & filters.group)
@require_member
@rate_limit
async def plshare_cmd(client: Client, message: Message):
    args = message.text.split()
    if len(args) < 2:
        return await message.reply_text("Usage: `/plshare <playlist_name>`")

    playlist_name = args[1]
    playlist = await _db().get_playlist_by_name(playlist_name)
    if not playlist:
        return await message.reply_text(f"💀 No setlist named '{playlist_name}' was found.")

    bot = await client.get_me()
    share_url = f"https://t.me/{bot.username}?start=play_pl_{playlist['id']}"
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("Play Playlist", url=share_url)]])
    await message.reply_text(
        f"🔗 Share setlist: **{playlist_name}**\n\nSend this to the crew and Brook will open the archive on cue.",
        reply_markup=markup,
    )


@Client.on_message(filters.command("plsync") & filters.group)
@require_member
@rate_limit
async def plsync_cmd(client: Client, message: Message):
    """Validate playlist references against the configured external track service."""
    args = message.text.split()
    if len(args) < 2:
        return await message.reply_text("Usage: `/plsync <playlist_name>`")

    playlist_name = args[1]
    playlist = await _db().get_playlist_by_name(playlist_name)
    if not playlist:
        return await message.reply_text(f"💀 No setlist named '{playlist_name}' was found.")

    msg = await message.reply_text("🎻 Brook is tuning every saved reference against the external music server...")
    tracks = await _db().get_playlist_tracks(playlist["id"])
    if not tracks:
        return await msg.edit_text("💀 This setlist is empty.")

    valid_count = 0
    for item in tracks:
        ref = _playlist_item_ref(item)
        if not ref:
            continue
        try:
            resolved = await music_backend.resolve(ref)
            if resolved and (resolved.get("url") or resolved.get("stream_url")):
                valid_count += 1
        except Exception:
            continue

    await msg.edit_text(
        f"🎼 Setlist check complete.\n"
        f"Playable references: `{valid_count}` / `{len(tracks)}`\n"
        "Use `/plplay` to enqueue the valid items."
    )


@Client.on_message(filters.command("plplay") & filters.group)
@require_member
@rate_limit
async def plplay_cmd(client: Client, message: Message):
    args = message.text.split()
    if len(args) < 2:
        return await message.reply_text("Usage: `/plplay <playlist_name>`")

    playlist_name = args[1]
    playlist = await _db().get_playlist_by_name(playlist_name)
    if not playlist:
        return await message.reply_text(f"💀 No setlist named '{playlist_name}' was found.")

    tracks = await _db().get_playlist_tracks(playlist["id"])
    if not tracks:
        return await message.reply_text("💀 This setlist is empty.")

    chat_id = message.chat.id
    added_count = 0
    failed_count = 0
    msg = await message.reply_text("🎶 Brook is loading this setlist from the external music server...")

    for item in tracks:
        ref = _playlist_item_ref(item)
        if not ref:
            failed_count += 1
            continue

        try:
            resolved = await music_backend.resolve(ref)
            if not resolved:
                failed_count += 1
                continue

            await queue_manager.add_to_queue(
                chat_id=chat_id,
                title=resolved.get("title", "Unknown"),
                url=resolved.get("url") or resolved.get("stream_url") or "",
                duration=resolved.get("duration", 0),
                thumb=resolved.get("thumbnail") or resolved.get("thumb"),
                requested_by=message.from_user.id,
                source=resolved.get("source", "unknown"),
                track_id=resolved.get("id") or resolved.get("track_id"),
                uploader=resolved.get("uploader") or resolved.get("artist"),
            )
            added_count += 1
        except Exception as exc:
            logger.error("Failed to add playlist ref=%r: %s", ref, exc)
            failed_count += 1

    if added_count == 0:
        await msg.edit_text("💀 None of the songs in this setlist answered the call.")
        return

    status = await queue_manager.get_status(chat_id)
    if status == "idle":
        await start_playback(chat_id)

    await msg.edit_text(
        f"🎻 Added `{added_count}` track(s) from **{playlist_name}** to the Soul King's setlist.\n"
        f"Skipped/failed: `{failed_count}`."
    )
