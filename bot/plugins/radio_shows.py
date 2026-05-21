"""
Radio Shows commands plugin
Commands:
  - /showcreate <name> <day> <time> <genre>
  - /showadd <show_id> <track_query>
  - /showlist
  - /showpreview <show_id>
  - /showcancel <show_id>
  - /showtalk
  - /showhistory
"""

import logging
from pyrogram import Client, filters
from pyrogram.types import Message

import bot.utils.database as app_db
from bot.utils.permissions import require_admin, require_member, rate_limit
from bot.platforms import search_tracks

logger = logging.getLogger(__name__)


def _db():
    if app_db.db is None:
        raise RuntimeError("Database is not initialized")
    return app_db.db

@Client.on_message(filters.command(["showcreate", "vshowcreate"]) & filters.group)
@require_admin
@rate_limit
async def show_create_cmd(client: Client, message: Message):
    """Create a new radio show slot."""
    if len(message.command) < 5:
        await message.reply_text(
            "**Usage:** `/showcreate <name> <day(0-6)> <time(HH:MM)> <genre>`\n"
            "Example: `/showcreate \"Morning Rock\" 1 09:00 Rock`\n"
            "Note: 0 = Monday, 6 = Sunday."
        )
        return

    # Extracting args - handling quotes for name
    args = message.text.split(maxsplit=1)[1]

    # Very basic parsing, assuming name might be quoted or just a single word if not quoted
    # A better parser would handle quotes properly, but this works for basic cases
    import shlex
    try:
        parsed_args = shlex.split(args)
        if len(parsed_args) < 4:
            raise ValueError("Not enough arguments")
    except Exception as e:
        await message.reply_text("Error parsing arguments. Try quoting the show name if it has spaces.")
        return

    name = parsed_args[0]
    try:
        day = int(parsed_args[1])
        if day < 0 or day > 6:
            raise ValueError("Day must be 0-6")
    except ValueError:
        await message.reply_text("Day must be a number between 0 (Monday) and 6 (Sunday).")
        return

    time = parsed_args[2]
    # Basic HH:MM validation
    import re
    if not re.match(r"^([01][0-9]|2[0-3]):[0-5][0-9]$", time):
        await message.reply_text("Time must be in HH:MM format (24-hour).")
        return

    genre = parsed_args[3]

    # Default duration 60 mins for now
    duration = 60

    show_id = await _db().create_radio_show(
        chat_id=message.chat.id,
        host_user_id=message.from_user.id,
        show_name=name,
        description=f"A {genre} show hosted by {message.from_user.first_name}",
        day=day,
        time=time,
        genre=genre,
        duration=duration
    )

    if show_id != -1:
        await message.reply_text(
            f"📻 **Radio Show Created!**\n\n"
            f"**Name:** {name}\n"
            f"**Host:** {message.from_user.mention}\n"
            f"**Schedule:** Day {day} at {time}\n"
            f"**Genre:** {genre}\n"
            f"**Show ID:** `{show_id}`\n\n"
            f"Use `/showadd {show_id} <track name>` to add songs to the lineup!"
        )
    else:
        await message.reply_text("❌ Failed to create the show. Please try again.")

@Client.on_message(filters.command(["showcancel", "vshowcancel"]) & filters.group)
@require_admin
@rate_limit
async def show_cancel_cmd(client: Client, message: Message):
    """Cancel and delete a radio show."""
    if len(message.command) < 2:
        await message.reply_text("**Usage:** `/showcancel <show_id>`")
        return

    try:
        show_id = int(message.command[1])
    except ValueError:
        await message.reply_text("Show ID must be a number.")
        return

    success = await _db().delete_show(show_id)
    if success:
        await message.reply_text(f"🗑️ Radio show `{show_id}` has been cancelled and deleted.")
    else:
        await message.reply_text(f"❌ Failed to delete show `{show_id}`.")

@Client.on_message(filters.command(["showadd", "vshowadd"]) & filters.group)
@require_admin
@rate_limit
async def show_add_cmd(client: Client, message: Message):
    """Add a track to a radio show's lineup."""
    if len(message.command) < 3:
        await message.reply_text("**Usage:** `/showadd <show_id> <track name/query>`")
        return

    try:
        show_id = int(message.command[1])
    except ValueError:
        await message.reply_text("Show ID must be a number.")
        return

    query = message.text.split(maxsplit=2)[2]

    msg = await message.reply_text(f"🔍 Searching for `{query}`...")

    # Search tracks
    results = await search_tracks(query, limit=1)
    if not results:
        await msg.edit_text("❌ No tracks found for your query.")
        return

    track = results[0]
    # We need an integer ID for jamendo_track_id as per schema, or we hash it if it's a string
    try:
        track_id_int = int(track.id)
    except (ValueError, TypeError):
        track_id_int = hash(track.id) % 2147483647 # Ensure fits in INTEGER

    success = await _db().add_track_to_show(show_id, track_id_int, message.from_user.id)

    if success:
        await msg.edit_text(f"✅ Added **{track.title}** by {track.artist} to Show `{show_id}`!")
    else:
        await msg.edit_text("❌ Failed to add track to the show.")

@Client.on_message(filters.command(["showlist", "vshowlist"]) & filters.group)
@require_member
@rate_limit
async def show_list_cmd(client: Client, message: Message):
    """List upcoming radio shows."""
    shows = await _db().get_upcoming_shows(message.chat.id)

    if not shows:
        await message.reply_text("📻 No upcoming radio shows scheduled for this chat.")
        return

    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    text = "📻 **Upcoming Radio Shows:**\n\n"
    for show in shows:
        day_name = days[show.get("schedule_day_of_week", 0) % 7]
        text += f"🎙️ **{show.get('show_name')}** (ID: `{show.get('id', show.get('show_id'))}`)\n"
        text += f"   📅 {day_name} at {show.get('schedule_time')} | 🏷️ {show.get('genre_tags')}\n\n"

    await message.reply_text(text)

@Client.on_message(filters.command(["showpreview", "vshowpreview"]) & filters.group)
@require_admin
@rate_limit
async def show_preview_cmd(client: Client, message: Message):
    """Preview a radio show (mock implementation for brevity)."""
    if len(message.command) < 2:
        await message.reply_text("**Usage:** `/showpreview <show_id>`")
        return

    try:
        show_id = int(message.command[1])
    except ValueError:
        await message.reply_text("Show ID must be a number.")
        return

    tracks = await _db().get_show_tracks(show_id)
    if not tracks:
        await message.reply_text(f"❌ Show `{show_id}` has no tracks in its lineup.")
        return

    msg = await message.reply_text(f"📻 **Previewing Show {show_id}...**\nLineup contains {len(tracks)} tracks. Loading first 3 tracks...")

    from bot.core.music_backend import music_backend
    from bot.core.queue import queue_manager
    from bot.core import call

    chat_id = message.chat.id
    added_count = 0

    # Just preview first 3 tracks
    for t in tracks[:3]:
        jamendo_id = t.get("jamendo_track_id")
        # In a real scenario we'd lookup the track by ID from backend
        # Here we just search by ID or mock it if not found
        results = await music_backend.search(str(jamendo_id), limit=1)
        if results:
            track = results[0]
            track_dict = track.to_dict()
            track_dict["requested_by"] = message.from_user.id
            track_dict["duration"] = min(track.duration, 30) if track.duration else 30 # Preview 30s

            await queue_manager.add_to_queue(chat_id, track_dict)
            added_count += 1

    if added_count > 0:
        # Start playback if not playing
        if call.call_manager:
            status = await queue_manager.get_status(chat_id)
            if status != "playing":
                next_track = await queue_manager.get_next(chat_id)
                if next_track:
                    await queue_manager.set_status(chat_id, "playing")
                    try:
                        await call.call_manager.play(
                            chat_id=chat_id,
                            stream_url=next_track["stream_url"],
                            video=next_track.get("video", False)
                        )
                        await msg.edit_text(f"📻 **Previewing Show {show_id}...**\nPlaying {added_count} tracks (30s previews).")
                    except Exception as e:
                        await queue_manager.set_status(chat_id, "idle")
                        logger.error(f"Failed to play preview: {e}")
                        await msg.edit_text("❌ Failed to start preview playback.")
    else:
        await msg.edit_text("❌ Could not resolve any tracks for preview.")

@Client.on_message(filters.command(["showhistory", "vshowhistory"]) & filters.group)
@require_member
@rate_limit
async def show_history_cmd(client: Client, message: Message):
    """List past radio shows."""
    shows = await _db().get_past_shows(message.chat.id)

    if not shows:
        await message.reply_text("📻 No past radio shows found for this chat.")
        return

    text = "📻 **Past Radio Shows:**\n\n"
    # Just show the latest 5
    for show in shows[:5]:
        show_id = show.get('id', show.get('show_id'))
        text += f"🎙️ **{show.get('show_name')}** (ID: `{show_id}`)\n"
        created_at = show.get('created_at', 'Unknown date')

        # Get tracks for the show
        tracks = await _db().get_show_tracks(show_id)
        track_count = len(tracks) if tracks else 0

        # We don't have attendance count in schema, so we omit or mock it
        text += f"   📅 {created_at} | 🏷️ {show.get('genre_tags')} | 🎵 {track_count} tracks played\n\n"

    await message.reply_text(text)

@Client.on_message(filters.command(["showtalk", "vshowtalk"]) & filters.group)
@require_admin
@rate_limit
async def show_talk_cmd(client: Client, message: Message):
    """Host talks during a show."""
    if not message.reply_to_message or not message.reply_to_message.voice:
        await message.reply_text("**Usage:** Reply to a voice note with `/showtalk` to play it in the voice chat.")
        return

    msg = await message.reply_text("🎙️ **Host Announcement!** Downloading voice note...")

    try:
        # Download the voice note
        file_path = await message.reply_to_message.download()
        if not file_path:
            await msg.edit_text("❌ Failed to download voice note.")
            return

        from bot.core.queue import queue_manager
        from bot.core import call

        chat_id = message.chat.id

        track_dict = {
            "id": f"voice_{message.reply_to_message.id}",
            "title": f"Host Announcement by {message.from_user.first_name}",
            "artist": "Radio Host",
            "duration": message.reply_to_message.voice.duration or 0,
            "source": "telegram",
            "stream_url": file_path,
            "requested_by": message.from_user.id
        }

        # Add to front of queue
        await queue_manager.add_to_front(chat_id, track_dict)

        # If playing, we might want to skip current or just let it play next
        # We'll just let it play next for simplicity, or start if idle
        if call.call_manager:
            status = await queue_manager.get_status(chat_id)
            if status == "playing":
                from bot.plugins.play import skip_current_track
                await skip_current_track(chat_id)
                await msg.edit_text("🎙️ **Host Announcement added!** Interrupting...")
            else:
                next_track = await queue_manager.get_next(chat_id)
                if next_track:
                    await queue_manager.set_status(chat_id, "playing")
                    await call.call_manager.play(
                        chat_id=chat_id,
                        stream_url=next_track["stream_url"],
                        video=False
                    )

        await msg.edit_text("🎙️ **Host Announcement added!**")
    except Exception as e:
        logger.error(f"Error in showtalk: {e}")
        await msg.edit_text("❌ Failed to process voice note.")
