"""Utility commands: /help, /ping"""

import time
import platform
from pyrogram import Client, filters
from typing import Any, cast

Client = cast(Any, Client)
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.enums import ParseMode
from app.utils.permissions import require_admin, rate_limit
from app.config_loader import config
import asyncio


# ── Help text blocks (HTML) ──────────────────────────────────────────────────

_HELP_HEADER = (
    "💀 <b>YOHOHOHO! Welcome to Brook's Songbook!</b>\n\n"
    "<i>\"A concert is best when every soul in the room feels it!\"</i>\n"
    "— Brook, Musician of the Straw Hat Pirates\n"
)

_HELP_PLAYBACK = (
    "\n<b>🎵 PLAYBACK</b>\n"
    "  /play <code>[song name or URL]</code> — Search and play a track\n"
    "  /vplay <code>[query]</code> — Play audio from VK / Deezer sources\n"
    "  /pause — Pause the current performance\n"
    "  /resume — Resume paused playback\n"
    "  /forceresume — Force-resume (admin, clears stuck state)\n"
    "  /stop — Stop playback and leave the voice chat\n"
    "       <i>Aliases: /end, /cleanup, /off</i>\n"
    "  /replay — Restart the current track from the beginning\n"
    "  /seek <code>[time]</code> — Jump to a position (e.g. <code>/seek 1:30</code>)\n"
    "  /volume <code>[0-200]</code> — Set playback volume\n"
)

_HELP_QUEUE = (
    "\n<b>📋 QUEUE MANAGEMENT</b>\n"
    "  /queue — View tonight's setlist <i>(alias: /q)</i>\n"
    "  /now — Show the currently playing track <i>(aliases: /np, /nowplaying)</i>\n"
    "  /skip — Skip to the next track <i>(alias: /next)</i>\n"
    "  /prev — Play the previous track <i>(alias: /previous)</i>\n"
    "  /shuffle — Randomize the queue order\n"
    "  /loop <code>[off|track|queue]</code> — Toggle loop mode\n"
    "  /remove <code>[position]</code> — Remove a track by queue number <i>(alias: /rm)</i>\n"
    "  /move <code>[from] [to]</code> — Move a track to a new position\n"
    "  /clearqueue — Clear all queued tracks (admin)\n"
)

_HELP_DISCOVERY = (
    "\n<b>🔍 MUSIC DISCOVERY</b>\n"
    "  /vibe <code>[mood/activity]</code> — Let Brook pick tracks by feeling\n"
    "  /moodsearch <code>[description]</code> — Search by mood tags\n"
    "  /mooddiscovery — Browse Soul King-curated mood suggestions\n"
)

_HELP_PLAYLISTS = (
    "\n<b>🗂 SETLISTS (Playlists)</b>\n"
    "  /plcreate <code>[name]</code> — Create a new setlist archive\n"
    "  /pladd <code>[playlist] [query]</code> — Add a track to a setlist\n"
    "  /plremove <code>[playlist] [position]</code> — Remove a track from a setlist\n"
    "  /pllist — List your saved setlists\n"
    "  /plplay <code>[playlist]</code> — Perform a saved setlist\n"
    "  /plcollab <code>[playlist]</code> — Toggle collaborative mode\n"
    "  /plshare <code>[playlist]</code> — Share a setlist with the group\n"
    "  /plsync <code>[playlist]</code> — Sync setlist changes across devices\n"
)

_HELP_RADIO = (
    "\n<b>📻 RADIO SHOWS</b>\n"
    "  /showcreate <code>[name] [day] [time] [genre]</code> — Create a radio show slot (admin)\n"
    "  /showadd <code>[show_id] [track query]</code> — Add a track to a show\n"
    "  /showlist — List all scheduled shows\n"
    "  /showpreview <code>[show_id]</code> — Preview a show's tracklist\n"
    "  /showcancel <code>[show_id]</code> — Cancel a scheduled show (admin)\n"
    "  /showhistory — View past show broadcasts\n"
    "  /showtalk — Open the show talk/live chat segment\n"
)

_HELP_GAMES = (
    "\n<b>🎮 SONG HUNTER (Music Game)</b>\n"
    "  /starthunter — Start a song-guessing game <i>(alias: /sh)</i>\n"
    "  /stophunter — End the current game <i>(alias: /stopsh)</i>\n"
    "  /hunterboard — View the leaderboard <i>(alias: /shboard)</i>\n"
)

_HELP_VOTING = (
    "\n<b>🗳 ANONYMOUS & VOTING</b>\n"
    "  /votemode <code>[on|off]</code> — Toggle voting mode for the group (admin)\n"
    "  /anonplay <code>[song]</code> — Request a song anonymously\n"
)

_HELP_EFFECTS = (
    "\n<b>🎛 EFFECTS & TIMERS</b>\n"
    "  /effects — Open the audio effects menu (admin)\n"
    "       <i>Options: 8D Audio, Slowed+Reverb, Nightcore, Bass Boost, Vocal Isolation</i>\n"
    "  /sleep <code>[duration]</code> — Set a sleep timer (e.g. <code>/sleep 30m</code>) (admin)\n"
    "  /cancelsleep — Cancel the active sleep timer (admin)\n"
    "  /setaggressive <code>[on|off]</code> — Toggle aggressive play mode (admin)\n"
    "  /uptime — Show bot uptime and scheduler status\n"
)

_HELP_ADMIN = (
    "\n<b>⚔️ ADMINISTRATION</b>\n"
    "  /addsudo <code>[user]</code> — Promote a user to sudo (owner)\n"
    "  /delsudo <code>[user]</code> — Revoke sudo access (owner)\n"
    "  /sudolist — List all sudo users (sudo)\n"
    "  /block <code>[user]</code> — Block a user in this group (admin)\n"
    "  /unblock <code>[user]</code> — Unblock a user (admin)\n"
    "  /gban <code>[user]</code> — Globally ban a user across all groups (sudo)\n"
    "  /ungban <code>[user]</code> — Remove a global ban (sudo)\n"
    "  /broadcast <code>[message]</code> — Broadcast to all groups (owner)\n"
    "  /stats — Show bot statistics (sudo)\n"
    "  /maintenance <code>[on|off]</code> — Toggle maintenance mode (sudo)\n"
    "  /restart — Restart the bot process (owner)\n"
    "  /prunedb — Clean stale database entries (sudo)\n"
    "  /health — System health report (owner DM)\n"
    "  /lasterrors — View recent error log (owner DM)\n"
)

_HELP_UTILITY = (
    "\n<b>🔧 UTILITY</b>\n"
    "  /ping — Check bot latency\n"
    "  /serverhealth — Check external music server status\n"
    "  /userbotjoin — Force the assistant to join/create voice chat (admin)\n"
    "  /vcdebug — Inspect voice chat connection state (admin)\n"
    "  /metrics — View callback performance metrics (DM)\n"
)

_HELP_FOOTER = (
    "\n<i>💀 \"May your evenings be lively, your hearts be light, "
    "and your speakers never quiet. Yohohoho!\"</i>\n\n"
    "<b>Permission Key:</b> "
    "(owner) = bot owner only · "
    "(sudo) = sudo users · "
    "(admin) = group admins · "
    "unmarked = all group members"
)


@Client.on_message(filters.command("help") & (filters.private | filters.group))
@rate_limit
async def help_cmd(client: Client, message: Message):
    """Handle /help command - open to everyone."""
    text = (
        _HELP_HEADER
        + _HELP_PLAYBACK
        + _HELP_QUEUE
        + _HELP_DISCOVERY
        + _HELP_PLAYLISTS
        + _HELP_RADIO
        + _HELP_GAMES
        + _HELP_VOTING
        + _HELP_EFFECTS
        + _HELP_ADMIN
        + _HELP_UTILITY
        + _HELP_FOOTER
    )

    buttons = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎵 Start Playing", switch_inline_query_current_chat=""),
            InlineKeyboardButton(
                "📢 Crew Support",
                url=f"https://t.me/{config.SUPPORT_CHAT_LINK.lstrip('@')}"
            ) if hasattr(config, 'SUPPORT_CHAT_LINK') and config.SUPPORT_CHAT_LINK else
            InlineKeyboardButton("📢 Crew Support", url="https://t.me/SoulKingSupport"),
        ]
    ])

    await message.reply(text, reply_markup=buttons, parse_mode=ParseMode.HTML)


@Client.on_message(filters.command("ping") & (filters.private | filters.group))
@rate_limit
async def ping_cmd(client: Client, message: Message):
    """Check bot latency and connectivity."""
    start = time.perf_counter()
    sent = await message.reply("🏓 Measuring...")
    elapsed_ms = (time.perf_counter() - start) * 1000
    await sent.edit_text(
        f"🏓 <b>Pong!</b> Latency: <code>{elapsed_ms:.0f}ms</code>\n"
        f"💀 <i>Yohohoho! Brook is on stage and ready to play!</i>",
        parse_mode=ParseMode.HTML,
    )
