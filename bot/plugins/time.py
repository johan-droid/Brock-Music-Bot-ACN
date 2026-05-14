"""Time management commands — /sleep, /timer, /scheduled"""

import logging
from datetime import datetime
from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.enums import ParseMode

from bot.utils.permissions import require_member, require_admin, rate_limit
from bot.utils.formatters import format_duration
from bot.utils.time_manager import time_manager

logger = logging.getLogger(__name__)


@Client.on_message(filters.command(["sleep", "sleeptimer"]) & filters.group)
@require_member
@rate_limit
async def sleep_cmd(client: Client, message: Message):
    """Set a sleep timer for the current chat."""
    chat_id = message.chat.id
    
    if len(message.command) < 2:
        # Show status if already set
        next_run = time_manager.get_sleep_timer(chat_id)
        if next_run:
            diff = next_run - datetime.now()
            remaining = format_duration(int(diff.total_seconds()))
            await message.reply(
                f"💤 **Sleep timer is active!**\n"
                f"Playback will stop in `{remaining}`.\n\n"
                f"<i>Use `/cancel_sleep` to stay awake! Yohoho!</i>",
                parse_mode=ParseMode.HTML
            )
        else:
            await message.reply(
                "💤 **Set a sleep timer to stop playback automatically.**\n\n"
                "Usage: `/sleep <duration>`\n"
                "Example: `/sleep 30m`, `/sleep 1h`, `/sleep 45s`\n\n"
                "<i>\"Even a skeleton needs his beauty sleep! Yohoho!\"</i>",
                parse_mode=ParseMode.HTML
            )
        return

    duration_str = message.command[1]
    seconds = await time_manager.set_sleep_timer(chat_id, duration_str)
    
    if not seconds:
        await message.reply(
            "❌ **Invalid duration format!**\n"
            "Use formats like `30m`, `1h`, or `45s`."
        )
        return

    readable = format_duration(seconds)
    await message.reply(
        f"💤 **Sleep timer set for {readable}!**\n"
        f"The Soul King will exit the stage after this duration.\n\n"
        f"<i>\"Sweet dreams of panties... I mean, melodies! Yohohoho!\"</i>",
        parse_mode=ParseMode.HTML
    )


@Client.on_message(filters.command(["cancelsleep", "unsleep"]) & filters.group)
@require_member
@rate_limit
async def cancel_sleep_cmd(client: Client, message: Message):
    """Cancel the active sleep timer."""
    chat_id = message.chat.id
    
    if time_manager.cancel_sleep_timer(chat_id):
        await message.reply(
            "⏰ **Sleep timer cancelled!**\n"
            "The Soul King will stay awake for the concert! YOHOHOHO! 🎸",
            parse_mode=ParseMode.HTML
        )
    else:
        await message.reply("💀 No active sleep timer found for this chat!")


@Client.on_message(filters.command(["uptime"]) & filters.group)
@require_member
@rate_limit
async def uptime_cmd(client: Client, message: Message):
    """Show bot uptime and scheduler status."""
    # This would ideally come from a central metrics collector
    from bot.utils.metrics import metrics_collector
    
    stats = metrics_collector.get_summary()
    uptime = stats.get("uptime_str", "Unknown")
    
    text = (
        f"⏱ **The Soul King's Voyage Duration:**\n"
        f"• **Uptime:** `{uptime}`\n"
        f"• **Active Timers:** `{len(time_manager._sleep_timers)}`\n"
        f"• **Scheduled Jobs:** `{len(time_manager.scheduler.get_jobs())}`\n\n"
        f"<i>\"Time flies when you're already dead! Yohohoho!\"</i>"
    )
    
    await message.reply(text, parse_mode=ParseMode.HTML)
