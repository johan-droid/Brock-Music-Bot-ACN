"""Utility commands: /help, /ping"""

import time
import platform
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from bot.utils.permissions import require_admin, rate_limit
from config import config


@Client.on_message(filters.command("help") & (filters.private | filters.group))
@rate_limit
async def help_cmd(client: Client, message: Message):
    """Handle /help command - open to everyone."""
    text = (
        "💀 YOHOHOHO! The Soul King Presents...\n\n"
        "\"Even without flesh, my music has SOUL!\"\n"
        "— Brook, Living Skeleton & Gentleman\n\n"
        "⚔️ CAPTAIN'S ORDERS (Owner Only)\n"
        "👑 /addsudo — Promote to First Mate\n"
        "🚫 /delsudo — Walk the plank\n"
        "📢 /broadcast — Message all crews\n"
        "🔄 /restart — Restart the ship\n\n"
        "🦴 CREW COMMANDS (All Mates Welcome)\n"
        "🎵 /play [song] — Request a tune, Yohoho!\n"
        "⏸ /pause — Pause the soul\n"
        "▶️ /resume — Resume the rhythm\n"
        "⏭ /skip — Next melody\n"
        "⏹ /stop — Silence the violin\n"
        "🔊 /volume — Crank it to 11!\n\n"
        "🎶 THE SETLIST (Queue Control)\n"
        "📋 /queue — View the playlist\n"
        "🔀 /shuffle — Mix the tracks\n"
        "🔁 /loop — Repeat the magic\n"
        "🧹 /clearqueue — Clear the stage\n"
        "⚔️ /setaggressive on|off — Toggle aggressive play mode for this group\n\n"
        "💀 \"May your soul always find good music!\"\n\n"
        "⚠️ Note: Aggressive play only works when enabled for this group.\n"
    )

    buttons = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎵 Start Playing", switch_inline_query_current_chat=""),
            InlineKeyboardButton("📢 Support", url=f"https://t.me/{config.SUPPORT_CHAT_LINK.lstrip('@')}" if hasattr(config, 'SUPPORT_CHAT_LINK') else "https://t.me/"),
        ]
    ])

    await message.reply(text, reply_markup=buttons if hasattr(config, 'SUPPORT_CHAT_LINK') else None)


@Client.on_message(filters.command("ping") & (filters.private | filters.group))
@rate_limit
async def ping_cmd(client: Client, message: Message):
    """Check bot latency with a Brook-themed response."""
    import os
    import asyncio

    start = time.monotonic()
    reply = await message.reply("💀 *Pinging... even a skeleton can feel the beat!*")
    latency = (time.monotonic() - start) * 1000

    # Emoji quality indicator
    if latency < 100:
        quality = "🟢 Excellent"
        brook_quote = "Fast as the rhythm of my violin! YOHOHOHO!"
    elif latency < 300:
        quality = "🟡 Good"
        brook_quote = "Steady, like a soulful ballad!"
    else:
        quality = "🔴 High"
        brook_quote = "A bit slow... even my bones react faster! Yohoho!"

    # Build a mini visual bar for latency
    bar_len = min(int(latency / 30), 10)
    bar = "▰" * bar_len + "▱" * (10 - bar_len)

    text = f"""
💀 **PONG! The Soul King responds!**

⚡ **Latency:** `{latency:.1f}ms`
📊 **Signal:** `{bar}` {quality}
🐍 **Python:** `{platform.python_version()}`

💬 *\"{brook_quote}\"*
    """

    await reply.edit(text)
