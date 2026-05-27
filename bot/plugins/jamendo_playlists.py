"""Collaborative playlist commands (microservice-backed)."""

import logging

import bot.utils.database as app_db
from pyrogram import Client, filters
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
        return await message.reply_text(f"❌ Playlist '{name}' already exists.")

    playlist_id = await _db().create_playlist(name, user_id)
    if playlist_id != -1:
        await message.reply_text(
            f"✅ Playlist **{name}** created successfully!\n\n"
            f"ID: `{playlist_id}`\n"
            "Add tracks with `/pladd <playlist_name> <track query or URL>`."
        )
    else:
        await message.reply_text("❌ Failed to create playlist.")


@Client.on_message(filters.command("pllist"))
@rate_limit
async def pllist_cmd(client: Client, message: Message):
    user_id = message.from_user.id
    playlists = await _db().get_user_playlists(user_id)
    if not playlists:
        return await message.reply_text("You don't have any playlists yet. Use `/plcreate <name>`.")

    text = "🎵 **Your Playlists:**\n\n"
    for pl in playlists:
        tracks = await _db().get_playlist_tracks(pl["id"])
        collab_flag = "👥 Collab" if pl.get("is_collaborative") else "🔒 Private"
        text += f"▪️ **{pl['name']}** (ID: `{pl['id']}`)\n   Tracks: {len(tracks)} | {collab_flag}\n"

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

    pl_name = parts[1]
    query = parts[2].strip()
    user_id = message.from_user.id

    playlist = await _db().get_playlist_by_name(pl_name)
    if not playlist:
        return await message.reply_text(f"❌ Playlist '{pl_name}' not found.")

    if playlist["creator_user_id"] != user_id and not playlist.get("is_collaborative"):
        is_sudo = await _db().is_sudo(user_id)
        if not is_sudo:
            return await message.reply_text("❌ You don't have permission to edit this private playlist.")

    searching = await message.reply_text("🔍 Resolving track...")
    try:
        results = await music_backend.search(query, limit=1)
    except Exception as exc:
        logger.error("Playlist add search failed for %r: %s", query, exc)
        return await searching.edit_text("❌ Failed to search for this track right now.")

    if not results:
        return await searching.edit_text("❌ No matching track found for this query.")

    track = results[0]
    track_ref = track.track_id or track.stream_url or f"{track.title} {track.artist}"
    success = await _db().add_track_to_playlist(playlist["id"], str(track_ref), user_id)
    if success:
        await searching.edit_text(f"✅ Added **{track.title}** by {track.artist} to **{pl_name}**.")
    else:
        await searching.edit_text("❌ Failed to add track.")


@Client.on_message(filters.command("plremove") & filters.group)
@require_member
@rate_limit
async def plremove_cmd(client: Client, message: Message):
    args = message.text.split()
    if len(args) < 3:
        return await message.reply_text("Usage: `/plremove <playlist_name> <position>`")

    pl_name = args[1]
    try:
        position = int(args[2])
    except ValueError:
        return await message.reply_text("❌ Position must be a number.")

    user_id = message.from_user.id
    playlist = await _db().get_playlist_by_name(pl_name)
    if not playlist:
        return await message.reply_text(f"❌ Playlist '{pl_name}' not found.")

    if playlist["creator_user_id"] != user_id and not playlist.get("is_collaborative"):
        is_sudo = await _db().is_sudo(user_id)
        if not is_sudo:
            return await message.reply_text("❌ You don't have permission to remove tracks from this playlist.")

    success = await _db().remove_track_from_playlist(playlist["id"], position)
    if success:
        await message.reply_text(f"✅ Track at position {position} removed from **{pl_name}**.")
    else:
        await message.reply_text("❌ Failed to remove track.")


@Client.on_message(filters.command("plcollab") & filters.group)
@require_member
@rate_limit
async def plcollab_cmd(client: Client, message: Message):
    args = message.text.split()
    if len(args) < 3 or args[2].lower() not in ["on", "off"]:
        return await message.reply_text("Usage: `/plcollab <playlist_name> <on|off>`")

    pl_name = args[1]
    mode = args[2].lower() == "on"
    user_id = message.from_user.id

    playlist = await _db().get_playlist_by_name(pl_name)
    if not playlist:
        return await message.reply_text(f"❌ Playlist '{pl_name}' not found.")
    if playlist["creator_user_id"] != user_id:
        return await message.reply_text("❌ Only the creator can toggle collaborative mode.")

    success = await _db().toggle_playlist_collab(playlist["id"], mode)
    if success:
        state = "Collaborative (anyone can add/remove)" if mode else "Private (only you can edit)"
        await message.reply_text(f"✅ Playlist **{pl_name}** is now {state}.")
    else:
        await message.reply_text("❌ Failed to update playlist mode.")


@Client.on_message(filters.command("plshare") & filters.group)
@require_member
@rate_limit
async def plshare_cmd(client: Client, message: Message):
    args = message.text.split()
    if len(args) < 2:
        return await message.reply_text("Usage: `/plshare <playlist_name>`")

    pl_name = args[1]
    playlist = await _db().get_playlist_by_name(pl_name)
    if not playlist:
        return await message.reply_text(f"❌ Playlist '{pl_name}' not found.")

    bot = await client.get_me()
    share_url = f"https://t.me/{bot.username}?start=play_pl_{playlist['id']}"
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("🎵 Play Playlist", url=share_url)]])
    await message.reply_text(
        f"🔗 **Share Playlist:** {pl_name}\n\nAnyone with this link can open this playlist.",
        reply_markup=markup,
    )


@Client.on_message(filters.command("plsync") & filters.group)
@require_member
@rate_limit
async def plsync_cmd(client: Client, message: Message):
    """Validate playlist references against configured music microservices."""
    args = message.text.split()
    if len(args) < 2:
        return await message.reply_text("Usage: `/plsync <playlist_name>`")

    pl_name = args[1]
    playlist = await _db().get_playlist_by_name(pl_name)
    if not playlist:
        return await message.reply_text(f"❌ Playlist '{pl_name}' not found.")

    msg = await message.reply_text("🔄 Validating playlist against music microservices...")
    tracks = await _db().get_playlist_tracks(playlist["id"])
    if not tracks:
        return await msg.edit_text("❌ Playlist is empty.")

    valid_count = 0
    for item in tracks:
        ref = item.get("jamendo_track_id")
        if not ref:
            continue
        try:
            results = await music_backend.search(str(ref), limit=1)
            if results:
                valid_count += 1
        except Exception:
            continue

    await msg.edit_text(
        f"✅ Playlist validation complete.\n"
        f"Valid references: `{valid_count}` / `{len(tracks)}`\n"
        "Use `/plplay` to enqueue the valid items."
    )


@Client.on_message(filters.command("plplay") & filters.group)
@require_member
@rate_limit
async def plplay_cmd(client: Client, message: Message):
    args = message.text.split()
    if len(args) < 2:
        return await message.reply_text("Usage: `/plplay <playlist_name>`")

    pl_name = args[1]
    playlist = await _db().get_playlist_by_name(pl_name)
    if not playlist:
        return await message.reply_text(f"❌ Playlist '{pl_name}' not found.")

    tracks = await _db().get_playlist_tracks(playlist["id"])
    if not tracks:
        return await message.reply_text("❌ Playlist is empty.")

    chat_id = message.chat.id
    added_count = 0
    failed_count = 0
    msg = await message.reply_text("🔄 Loading playlist tracks...")

    for item in tracks:
        ref = item.get("jamendo_track_id")
        if not ref:
            failed_count += 1
            continue

        try:
            results = await music_backend.search(str(ref), limit=1)
            if not results:
                failed_count += 1
                continue

            track = results[0].to_dict()
            await queue_manager.add_to_queue(
                chat_id=chat_id,
                title=track.get("title", "Unknown"),
                url=track.get("url") or track.get("stream_url") or "",
                duration=track.get("duration", 0),
                thumb=track.get("thumbnail") or track.get("thumb"),
                requested_by=message.from_user.id,
                source=track.get("source", "unknown"),
                track_id=track.get("id") or track.get("track_id"),
                uploader=track.get("uploader") or track.get("artist"),
            )
            added_count += 1
        except Exception as exc:
            logger.error("Failed to add playlist ref=%r: %s", ref, exc)
            failed_count += 1

    if added_count == 0:
        await msg.edit_text("❌ Could not load any playlist tracks.")
        return

    status = await queue_manager.get_status(chat_id)
    if status == "idle":
        await start_playback(chat_id)

    await msg.edit_text(
        f"✅ Added `{added_count}` track(s) from **{pl_name}** to queue.\n"
        f"Skipped/failed: `{failed_count}`."
    )
