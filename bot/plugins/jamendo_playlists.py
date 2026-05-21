"""Jamendo collaborative playlist management."""

import logging
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
import bot.utils.database as app_db
from bot.platforms.jamendo import jamendo_api
from bot.utils.permissions import require_member, rate_limit
from config import config

logger = logging.getLogger(__name__)


def _db():
    if app_db.db is None:
        raise RuntimeError("Database is not initialized")
    return app_db.db

@Client.on_message(filters.command("plcreate") & filters.group)
@require_member
@rate_limit
async def plcreate_cmd(client: Client, message: Message):
    """Create a new playlist."""
    if not message.text or len(message.text.split()) < 2:
        return await message.reply_text("Usage: /plcreate <playlist_name>")

    name = message.text.split(maxsplit=1)[1]
    user_id = message.from_user.id

    # Check if exists
    existing = await _db().get_playlist_by_name(name)
    if existing:
        return await message.reply_text(f"❌ Playlist '{name}' already exists.")

    playlist_id = await _db().create_playlist(name, user_id)
    if playlist_id != -1:
        await message.reply_text(
            f"✅ Playlist **{name}** created successfully!\n\n"
            f"ID: `{playlist_id}`\n"
            f"Add tracks with `/pladd <track_id>`."
        )
    else:
        await message.reply_text("❌ Failed to create playlist.")

@Client.on_message(filters.command("pllist"))
@rate_limit
async def pllist_cmd(client: Client, message: Message):
    """List user's playlists."""
    user_id = message.from_user.id
    playlists = await _db().get_user_playlists(user_id)

    if not playlists:
        return await message.reply_text("You don't have any playlists yet. Use `/plcreate <name>` to create one.")

    text = "🎵 **Your Playlists:**\n\n"
    for pl in playlists:
        tracks = await _db().get_playlist_tracks(pl['id'])
        collab_flag = "👥 Collab" if pl.get('is_collaborative') else "🔒 Private"
        text += f"▪️ **{pl['name']}** (ID: `{pl['id']}`)\n   Tracks: {len(tracks)} | {collab_flag}\n"

    await message.reply_text(text)

# Also handle the Jamendo Auth deep link from the start command if needed, but that's typically in start.py.
# We'll hook into it or assume start.py routes it, or we just handle it directly if we can't change start.py easily.
# Actually, we can intercept /start jamendo_auth_CODE.

@Client.on_message(filters.command("start") & filters.private)
async def handle_jamendo_auth(client: Client, message: Message):
    """Handle Jamendo OAuth deep link payload."""
    if len(message.command) > 1 and message.command[1].startswith("jamendo_auth_"):
        code = message.command[1].replace("jamendo_auth_", "")
        user_id = message.from_user.id

        msg = await message.reply_text("🔄 Authenticating with Jamendo...")
        token_data = await jamendo_api.exchange_auth_code(code)

        if token_data and "access_token" in token_data:
            success = await _db().save_jamendo_token(user_id, token_data)
            if success:
                await msg.edit_text("✅ Successfully connected your Jamendo account! You can now use `/plsync`.")
            else:
                await msg.edit_text("❌ Failed to save Jamendo credentials in the database.")
        else:
            await msg.edit_text("❌ Jamendo authentication failed. The code might be expired.")
        # Continue propagates so start.py still fires if it has lower priority, or we can use continue_propagation
        # But pyrogram handlers are evaluated in group order. By default group is 0.
        # If we return, we stop propagation. Let's just stop propagation for this specific deep link.
        return
    message.continue_propagation()

@Client.on_message(filters.command("pladd") & filters.group)
@require_member
@rate_limit
async def pladd_cmd(client: Client, message: Message):
    """Add a track to a playlist."""
    args = message.text.split()
    if len(args) < 3:
        return await message.reply_text("Usage: `/pladd <playlist_name> <jamendo_track_id>`")

    pl_name = args[1]
    track_id = args[2]
    user_id = message.from_user.id

    playlist = await _db().get_playlist_by_name(pl_name)
    if not playlist:
        return await message.reply_text(f"❌ Playlist '{pl_name}' not found.")

    # Permission check
    if playlist['creator_user_id'] != user_id and not playlist.get('is_collaborative'):
        # Allow sudo users too? Sure, but let's stick to simple rules
        is_sudo = await _db().is_sudo(user_id)
        if not is_sudo:
            return await message.reply_text("❌ You don't have permission to add tracks to this playlist. It is not collaborative.")

    success = await _db().add_track_to_playlist(playlist['id'], track_id, user_id)
    if success:
        await message.reply_text(f"✅ Track `{track_id}` added to **{pl_name}**.")
    else:
        await message.reply_text("❌ Failed to add track.")

@Client.on_message(filters.command("plremove") & filters.group)
@require_member
@rate_limit
async def plremove_cmd(client: Client, message: Message):
    """Remove a track from a playlist by position."""
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

    if playlist['creator_user_id'] != user_id and not playlist.get('is_collaborative'):
        is_sudo = await _db().is_sudo(user_id)
        if not is_sudo:
            return await message.reply_text("❌ You don't have permission to remove tracks from this playlist.")

    success = await _db().remove_track_from_playlist(playlist['id'], position)
    if success:
        await message.reply_text(f"✅ Track at position {position} removed from **{pl_name}**.")
    else:
        await message.reply_text("❌ Failed to remove track.")

@Client.on_message(filters.command("plcollab") & filters.group)
@require_member
@rate_limit
async def plcollab_cmd(client: Client, message: Message):
    """Toggle collaborative mode for a playlist."""
    args = message.text.split()
    if len(args) < 3 or args[2].lower() not in ['on', 'off']:
        return await message.reply_text("Usage: `/plcollab <playlist_name> <on|off>`")

    pl_name = args[1]
    mode = args[2].lower() == 'on'
    user_id = message.from_user.id

    playlist = await _db().get_playlist_by_name(pl_name)
    if not playlist:
        return await message.reply_text(f"❌ Playlist '{pl_name}' not found.")

    if playlist['creator_user_id'] != user_id:
        return await message.reply_text("❌ Only the creator can toggle collaborative mode.")

    success = await _db().toggle_playlist_collab(playlist['id'], mode)
    if success:
        state = "Collaborative (anyone can add/remove)" if mode else "Private (only you can add/remove)"
        await message.reply_text(f"✅ Playlist **{pl_name}** is now {state}.")
    else:
        await message.reply_text("❌ Failed to update playlist mode.")

@Client.on_message(filters.command("plshare") & filters.group)
@require_member
@rate_limit
async def plshare_cmd(client: Client, message: Message):
    """Generate a shareable inline button to share a playlist."""
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
    await message.reply_text(f"🔗 **Share Playlist:** {pl_name}\n\nAnyone with this link can start playing your playlist!", reply_markup=markup)

@Client.on_message(filters.command("plsync") & filters.group)
@require_member
@rate_limit
async def plsync_cmd(client: Client, message: Message):
    """Sync a local playlist to Jamendo API."""
    args = message.text.split()
    if len(args) < 2:
        return await message.reply_text("Usage: `/plsync <playlist_name>`")

    pl_name = args[1]
    user_id = message.from_user.id

    playlist = await _db().get_playlist_by_name(pl_name)
    if not playlist:
        return await message.reply_text(f"❌ Playlist '{pl_name}' not found.")

    if playlist['creator_user_id'] != user_id:
        return await message.reply_text("❌ Only the creator can sync the playlist.")

    token = await _db().get_jamendo_token(user_id)
    if not token or 'access_token' not in token:
        # User not authenticated with Jamendo
        auth_url = jamendo_api.generate_oauth_url(user_id)
        if not auth_url:
            return await message.reply_text("❌ Jamendo integration is not configured by the bot owner.")

        markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔗 Connect Jamendo", url=auth_url)]])
        return await message.reply_text(
            "⚠️ You need to connect your Jamendo account to sync playlists.",
            reply_markup=markup
        )

    msg = await message.reply_text("🔄 Syncing playlist to Jamendo...")

    # 1. Create remote playlist
    jamendo_pl_id = await jamendo_api.create_jamendo_playlist(token['access_token'], pl_name)
    if not jamendo_pl_id:
        return await msg.edit_text("❌ Failed to create playlist on Jamendo API.")

    # 2. Add tracks
    tracks = await _db().get_playlist_tracks(playlist['id'])
    track_ids = [t['jamendo_track_id'] for t in tracks if t.get('jamendo_track_id')]

    if track_ids:
        success = await jamendo_api.add_tracks_to_jamendo_playlist(token['access_token'], jamendo_pl_id, track_ids)
        if not success:
            return await msg.edit_text("❌ Created playlist, but failed to add tracks via Jamendo API.")

    await msg.edit_text(f"✅ Successfully synced **{pl_name}** to Jamendo! ({len(track_ids)} tracks)")


@Client.on_message(filters.command("plplay") & filters.group)
@require_member
@rate_limit
async def plplay_cmd(client: Client, message: Message):
    """Play a playlist by name."""
    args = message.text.split()
    if len(args) < 2:
        return await message.reply_text("Usage: `/plplay <playlist_name>`")

    pl_name = args[1]
    playlist = await _db().get_playlist_by_name(pl_name)
    if not playlist:
        return await message.reply_text(f"❌ Playlist '{pl_name}' not found.")

    tracks = await _db().get_playlist_tracks(playlist['id'])
    if not tracks:
        return await message.reply_text("❌ Playlist is empty.")

    # The actual queuing mechanism would interface with `queue.py` and `play.py`
    # Since we have the track_ids, we can enqueue them via the music backend or queue manager.
    # We will just print a success message for now, as integrating with the specific queue
    # requires deeper knowledge of the bot's queue manager functions.
    # Assuming `music_backend.get_track` or similar exists.
    from bot.core.queue import queue_manager
    from bot.core.music_backend import music_backend

    chat_id = message.chat.id
    added_count = 0

    msg = await message.reply_text("🔄 Loading playlist tracks...")
    for t in tracks:
        # Search track by ID on Jamendo using the music_backend
        # For simplicity, we just assume we enqueue a search query if we only have the ID,
        # or if the bot has a direct ID lookup.
        try:
            # We construct a query that the play.py uses, or call get_tracks directly
            results = await music_backend.search(t['jamendo_track_id'])
            if results:
                await queue_manager.add(chat_id, results[0])
                added_count += 1
        except Exception as e:
            logger.error(f"Error adding track {t['jamendo_track_id']} to queue: {e}")

    if added_count > 0:
        await msg.edit_text(f"✅ Added {added_count} tracks from **{pl_name}** to the queue.")
    else:
        await msg.edit_text("❌ Failed to load any tracks from the playlist.")
