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
        "🍁 Commands & Authority List\n\n"
        "👥 Members Command\n"
        "🎸 /play [song/URL] — Play a song or add to queue\n"
        "🎬 /vplay [video/URL] — Play a YouTube video (Admin)\n"
        "📋 /queue or /q — View the current setlist\n"
        "⏯ /pause — Pause the Soul King's performance\n"
        "▶️ /resume — Resume the performance\n"
        "⏩ /seek [seconds] — Jump to a position in the track\n"
        "🔁 /replay — Restart the current song from scratch\n"
        "🎧 /now or /np — See what's playing right now\n"
        "🔊 /volume [1-200] — Adjust volume (default: 100%)\n\n"
        "🛡 Admins Command\n"
        "🗑️ /clearqueue — Clear all upcoming songs\n"
        "⏭ /skip — Skip to the next track\n"
        "⏹ /stop — Stop everything & clear the setlist\n"
        "❌ /remove [pos] — Remove a song from the setlist\n"
        "🔀 /shuffle — Shuffle the setlist randomly\n"
        "🔂 /loop [track/queue/none] — Set loop mode\n\n"
        "👑 Owner/Sudo Commands\n"
        "👑 /addsudo [user] — Grant sudo access\n"
        "🚫 /delsudo [user] — Revoke sudo access\n"
        "📜 /sudolist — List all sudo users\n"
        "📛 /gban [user] — Global ban a user\n"
        "✅ /ungban [user] — Remove a global ban\n"
        "🔒 /block [user] — Block user from using the bot in this group\n"
        "🔓 /unblock [user] — Unblock user in this group\n"
        "📊 /stats — Full bot statistics\n"
        "📢 /broadcast [msg] — Broadcast to all groups\n"
        "🔄 /restart — Restart the bot\n"
        "🛠️ /maintenance [on/off] — Toggle maintenance mode\n\n"
        "💀 Authority is strictly enforced by role."
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
