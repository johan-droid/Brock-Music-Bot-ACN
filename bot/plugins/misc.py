"""Utility commands: /help, /ping"""

import time
import platform
from pyrogram import Client, filters
from typing import Any, cast

Client = cast(Any, Client)
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from bot.utils.permissions import require_admin, rate_limit
from config import config
import time
import asyncio


@Client.on_message(filters.command("help") & (filters.private | filters.group))
@rate_limit
async def help_cmd(client: Client, message: Message):
    """Handle /help command - open to everyone."""
    text = (
        "💀 YOHOHOHO! Welcome to Brook's Songbook...\n\n"
        "\"A concert is best when every soul in the room feels it!\"\n"
        "— Brook, Musician of the Straw Hat Pirates\n\n"
        "⚔️ CAPTAIN'S DECK (Owner Only)\n"
        "👑 /addsudo — Promote to First Mate\n"
        "🚫 /delsudo — Walk the plank\n"
        "📢 /broadcast — Message all crews\n"
        "🔄 /restart — Restart the ship\n\n"
        "🦴 CREW REQUESTS (All Mates Welcome)\n"
        "🎵 /play [song] — Call for a performance\n"
        "⏸ /pause — Pause the concert\n"
        "▶️ /resume — Bring the music back\n"
        "📋 /queue — View tonight's setlist\n"
        "🎧 /now — See the current performance\n"
        "🎵 /vibe [mood] — Let Brook pick the feeling\n\n"
        "🧠 /moodsearch [description] — Search the seas by mood tags\n"
        "✨ /mooddiscovery — Browse Soul King-style suggestions\n\n"
        "🎶 STAGE CONTROL\n"
        "⏭ /skip — Jump to the next number\n"
        "⏹ /stop — End the performance\n"
        "🔊 /volume — Raise or lower the stage speakers\n"
        "🔀 /shuffle — Mix up the setlist\n"
        "🔁 /loop — Encore the track or queue\n"
        "🧹 /clearqueue — Clear the stage\n"
        "🎛 /effects — Color the performance with effects\n"
        "💤 /sleep — Tell Brook when to leave the stage\n"
        "⚔️ /setaggressive on|off — Let the show keep moving in this group\n\n"
        "🗂 CREW MIXTAPES\n"
        "🎼 /plcreate [name] — Create a new setlist archive\n"
        "➕ /pladd [playlist] [query] — Add a track from your external music server\n"
        "📚 /pllist — Review your saved setlists\n"
        "▶️ /plplay [playlist] — Perform a saved playlist\n"
        "🩺 /serverhealth — Check the condition of the music server\n\n"
        "💀 \"May your evenings be lively, your hearts be light, and your speakers never quiet. Yohohoho!\"\n\n"
        "⚠️ Aggressive play only works when enabled for this group.\n"
    )

    buttons = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎵 Start Playing", switch_inline_query_current_chat=""),
            InlineKeyboardButton("📢 Crew Support", url=f"https://t.me/{config.SUPPORT_CHAT_LINK.lstrip('@')}" if hasattr(config, 'SUPPORT_CHAT_LINK') else "https://t.me/"),
        ]
    ])

    await message.reply(text, reply_markup=buttons if hasattr(config, 'SUPPORT_CHAT_LINK') else None)


@Client.on_message(filters.command("ping") & (filters.private | filters.group))
@rate_limit
async def ping_cmd(client: Client, message: Message):
    """Check bot latency and connectivity."""
    await message.reply("💀 Yohohoho! Brook is on stage, violin tuned, and ready to play.")
