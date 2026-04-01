"""Playback control commands: /pause, /resume, /skip, /stop, /seek, /volume, /replay"""

import logging
from pyrogram import Client, filters
from pyrogram.types import Message
from bot.utils.permissions import require_admin, require_member, rate_limit
from bot.utils.formatters import format_duration
from bot.utils.progress_tracker import progress_tracker
from bot.utils.cache import cache
import bot.utils.database as app_db
from bot.core.call import call_manager
from bot.core.queue import queue_manager
from bot.core import bot as bot_module
from config import config

logger = logging.getLogger(__name__)


@Client.on_message(filters.command("pause") & filters.group)
@require_member
@rate_limit
async def pause_cmd(client: Client, message: Message):
    """Pause current playback."""
    chat_id = message.chat.id
    
    status = await queue_manager.get_status(chat_id)
    if status != "playing":
        await message.reply(
            "💀 <b>Nothing is playing right now, Yohoho!</b>\n"
            "Use /play to start the music!",
            parse_mode="html"
        )
        return

    try:
        await queue_manager.set_status(chat_id, "paused")
        await call_manager.pause(chat_id)
        progress_tracker.pause(chat_id)
        await message.reply(
            "⏸ <b>Paused!</b> The Soul King takes a breath...\n"
            "<i>Use /resume to continue the concert, Yohoho!</i>",
            parse_mode="html"
        )
        logger.info(f"Paused playback in chat {chat_id}")
    except Exception as e:
        logger.error(f"Pause failed: {e}")
        await message.reply("💀 Even a skeleton can't pause right now! Try again.")


@Client.on_message(filters.command("resume") & filters.group)
@require_member
@rate_limit
async def resume_cmd(client: Client, message: Message):
    """Resume paused playback."""
    chat_id = message.chat.id
    
    status = await queue_manager.get_status(chat_id)
    if status != "paused":
        if status == "idle":
            from bot.plugins.play import start_playback
            await start_playback(chat_id)
            return
        await message.reply("💀 Nothing is paused right now, Yohoho!")
        return
    
    try:
        await queue_manager.set_status(chat_id, "playing")
        await call_manager.resume(chat_id)
        progress_tracker.resume(chat_id)
        await message.reply(
            "▶️ <b>Resumed!</b> The Soul King is back on stage!\n"
            "<i>YOHOHOHO! The concert continues! 🎸</i>",
            parse_mode="html"
        )
        logger.info(f"Resumed playback in chat {chat_id}")
    except Exception as e:
        logger.error(f"Resume failed: {e}")
        await message.reply("💀 Even Brook can't resume this one! Try again.")


@Client.on_message(filters.command("skip") & filters.group)
@require_admin
@rate_limit
async def skip_cmd(client: Client, message: Message):
    """Skip to next song (admin only)."""
    chat_id = message.chat.id
    
    status = await queue_manager.get_status(chat_id)
    if status not in ["playing", "paused"]:
        await message.reply("💀 Nothing is playing right now, Yohoho!")
        return
    
    queue_len = await queue_manager.get_queue_length(chat_id)
    if queue_len == 0:
        await message.reply("⏭ **Skipping!** No more songs in the setlist, Yohoho!")
    else:
        await message.reply(f"⏭ **Skipping!** {queue_len} song(s) remaining in the Soul King's setlist!")
    
    try:
        # Stop current stream
        await call_manager.leave_call(chat_id)
        
        # Trigger next playback
        from bot.plugins.play import start_playback
        await start_playback(chat_id)
        
        logger.info(f"Skipped track in chat {chat_id}")
        
    except Exception as e:
        logger.error(f"Skip failed: {e}")
        await message.reply("💀 Even a skeleton stumbles sometimes! Skip failed.")


@Client.on_message(filters.command(["stop", "end", "cleanup"]) & filters.group)
@require_admin
@rate_limit
async def stop_cmd(client: Client, message: Message):
    """Stop playback, clear queue, and cleanup session (admin only)."""
    chat_id = message.chat.id
    
    status = await queue_manager.get_status(chat_id)
    if status == "idle":
        # Just run cleanup if idle
        from bot.plugins.play import cleanup_vc_session
        await cleanup_vc_session(chat_id, send_message=False)
        await message.reply(
            "🧹 <b>Session cleaned!</b> All queues wiped and ready for a new concert! Yohoho! 🎸",
            parse_mode="html"
        )
        return
    
    try:
        # Full cleanup - stop everything and wipe queues
        from bot.plugins.play import cleanup_vc_session
        await cleanup_vc_session(chat_id, send_message=False)

        await message.reply(
            "⏹ <b>Stopped!</b> The Soul King bows and exits the stage! Yohoho!\n"
            "<i>🧹 All queues cleared - fresh session ready!</i>",
            parse_mode="html"
        )
        logger.info(f"Stopped and cleaned up playback in chat {chat_id}")
    except Exception as e:
        logger.error(f"Stop/cleanup failed: {e}")
        await message.reply("💀 Even Brook can't stop the music right now! Try again.")


@Client.on_message(filters.command("seek") & filters.group)
@require_member
@rate_limit
async def seek_cmd(client: Client, message: Message):
    """Seek to position in track."""
    chat_id = message.chat.id
    
    if len(message.command) < 2:
        await message.reply("❌ Usage: `/seek [seconds]`\nExample: `/seek 120` (seek to 2 minutes)")
        return
    
    try:
        seconds = int(message.command[1])
    except ValueError:
        await message.reply("❌ Please provide a valid number of seconds.")
        return
    
    status = await queue_manager.get_status(chat_id)
    if status not in ["playing", "paused"]:
        await message.reply("❌ Nothing is playing right now.")
        return
    
    try:
        # Get current track
        current = await queue_manager.get_current(chat_id)
        if not current:
            await message.reply("❌ No track information available.")
            return
        
        # Validate seek position
        duration = current.get("duration", 0)
        if seconds < 0 or seconds >= duration:
            await message.reply(f"❌ Invalid seek position. Track duration is {format_duration(duration)}.")
            return
        
        # Use optimized audio config instead of hardcoded AudioPiped
        from bot.utils.audio_config import get_audio_optimizer
        optimizer = get_audio_optimizer()
        
        # In ping/test or replay, we just need to re-stream it with the seek offset
        is_video = current.get("is_video", False)
        
        # Change stream (py-tgcalls handles the transition)
        # change_stream may be absent on some builds; call_manager handles compatibility
        await call_manager.change_stream(chat_id, current["url"], video=is_video, seek=seconds)
        
        # Update position
        await queue_manager.update_position(chat_id, seconds)
        
        await message.reply(f"⏩ **Seeked to `{format_duration(seconds)}`!** Yohohoho! Jumping through time like a soul!")
        logger.info(f"Seeked to {seconds}s in chat {chat_id}")
        
    except Exception as e:
        logger.error(f"Seek failed: {e}")
        await message.reply("💀 Even skeletons can't time-travel right now! Seek failed.")


@Client.on_message(filters.command("replay") & filters.group)
@require_member
@rate_limit
async def replay_cmd(client: Client, message: Message):
    """Restart current track."""
    chat_id = message.chat.id
    
    status = await queue_manager.get_status(chat_id)
    if status not in ["playing", "paused"]:
        await message.reply("❌ Nothing is playing right now.")
        return
    
    try:
        # Get current track
        current = await queue_manager.get_current(chat_id)
        if not current:
            await message.reply("❌ No track information available.")
            return
        
        # Restart from beginning
        current = await queue_manager.get_current(chat_id)
        if not current:
            await message.reply("❌ No track information available.")
            return
        
        # Replay is just seeking to 0
        is_video = current.get("is_video", False)
        # change_stream may be absent on some builds; call_manager handles compatibility
        await call_manager.change_stream(chat_id, current["url"], video=is_video, seek=0)
        
        # Reset position
        await queue_manager.update_position(chat_id, 0)
        
        await message.reply("🔁 **Replaying from the beginning!** The Soul King never tires of a good song, YOHOHOHO!")
        logger.info(f"Replaying track in chat {chat_id}")
        
    except Exception as e:
        logger.error(f"Replay failed: {e}")
        await message.reply("💀 Even Brook can't rewind time on this one! Replay failed.")


@Client.on_message(filters.command("volume") & filters.group)
@require_member
@rate_limit
async def volume_cmd(client: Client, message: Message):
    """Adjust playback volume."""
    chat_id = message.chat.id
    
    if len(message.command) < 2:
        # Show current volume from settings
        group = await app_db.db.get_group(chat_id)
        vol = group.get("settings", {}).get("vol_default", 100)
        await message.reply(f"🔊 **Current Volume:** `{vol}%`\n\n💀 *The Soul King sings at full blast!*\nUsage: `/volume [1-200]`")
        return
    
    try:
        volume = int(message.command[1])
        if volume < 1 or volume > 200:
            await message.reply("❌ Volume must be between 1 and 200.")
            return
    except ValueError:
        await message.reply("❌ Please provide a valid number.")
        return
    
    try:
        # Note: In py-tgcalls 2.0 volume is managed differently, or we can use the bot_client or CallManager directly.
        # Let's add set_volume in call.py
        await call_manager.set_volume(chat_id, volume)
        
        # We store it for future streams and settings
        await app_db.db.update_group(chat_id, {"settings.vol_default": volume})

        bar = '🟩' * (volume // 20) + '⬜' * (10 - volume // 20)
        await message.reply(f"🔊 **Volume set to `{volume}%`!**\n{bar}\n\n💀 *Yohohoho! The Soul King cranks it up!*")
        logger.info(f"Set volume to {volume}% in chat {chat_id}")
        
    except Exception as e:
        logger.error(f"Volume change failed: {e}")
        await message.reply("💀 Brook can't adjust the volume right now! Try again.")


@Client.on_message(filters.command("userbotjoin") & filters.group)
@require_admin
@rate_limit
async def userbotjoin_cmd(client: Client, message: Message):
    """Prompt the userbot to join/create a voice chat and provide promotion hints."""
    chat_id = message.chat.id

    if chat_id in call_manager.active_chats:
        await message.reply(
            "✅ Userbot is already in the voice chat for this group. "
            "If no audio is playing, use /play <song> now."
        )
        return

    success = False
    try:
        success = await call_manager._start_voice_chat(chat_id, 0)
    except Exception as exc:
        logger.warning(f"userbotjoin failed: {exc}")

    if success:
        await message.reply(
            "✅ Userbot join request sent. Voice chat should now be active or already active.\n\n"
            "💡 Next step: Promote the userbot as **Administrator** with at least **Manage Voice Chats / Manage Video Chats** privileges, "
            "then run `/play <song>` to start streaming."
        )
    else:
        await message.reply(
            "❌ Could not auto-start voice chat. Please check:\n"
            "1) userbot is a group member.\n"
            "2) userbot has Admin role with Manage Voice Chats permissions.\n"
            "3) Group voice chat is allowed for this group.\n"
            "Then retry `/userbotjoin` and `/play <song>`."
        )


@Client.on_message(filters.command("vcdebug") & filters.group)
@require_admin
@rate_limit
async def vcdebug_cmd(client: Client, message: Message):
    """Inspect voice chat state to help debug join/play issues."""
    chat_id = message.chat.id

    active = chat_id in call_manager.active_chats
    activeChatLists = [f"{c} (userbot #{i+1})" for c, i in call_manager.active_chats.items()]
    queue_status = await queue_manager.get_status(chat_id)
    current = await queue_manager.get_current(chat_id)
    qlen = await queue_manager.get_queue_length(chat_id)
    # using existing helper for userbot permissions
    from bot.utils.permissions import check_bot_admin, check_userbot_admin

    bot_admin_state = await check_bot_admin(chat_id)
    userbot_admin_state = await check_userbot_admin(chat_id)
    balancer = call_manager.get_balancer_snapshot() if call_manager else {"loads": {}}
    loads = balancer.get("loads", {})
    load_text = ", ".join([f"#{int(idx) + 1}:{count}" for idx, count in loads.items()]) if loads else "n/a"

    text = (
        f"🔍 <b>VC Debug Status</b>\n"
        f"• Active for this group: {'✅' if active else '❌'}\n"
        f"• Active chats tracked: {len(call_manager.active_chats)}\n"
        f"• Active chat IDs: {', '.join(activeChatLists) if activeChatLists else 'None'}\n"
        f"• Queue status: {queue_status}\n"
        f"• Queue length: {qlen}\n"
        f"• Current track: {current.get('title','None') if current else 'None'}\n"
        f"• Bot admin: {'✅' if bot_admin_state else '❌'}\n"
        f"• Userbot admin: {'✅' if userbot_admin_state else '❌'}\n"
        f"• Assistant loads: {load_text}\n"
        "\n💡 Tip: Ensure both the bot and userbot are admins with **Manage Video Chats / Voice Chats**.\n"
        "If userbot is not admin, run /userbotjoin after promotion."
    )

    await message.reply(text, parse_mode="html")

