"""
Admin commands — deeply integrated, group + private, with proper access warnings.
Commands:
    Owner/Sudo: /addsudo, /delsudo, /sudolist, /broadcast, /restart, /maintenance,
                            /gban, /ungban, /block, /unblock, /stats
"""

import logging
import asyncio
import platform
import sys

from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.errors import FloodWait, UserNotParticipant, PeerIdInvalid, BadRequest

from config import config
from bot.utils.permissions import (
    require_sudo, get_permission_level,
    is_owner, is_sudo, is_gbanned,
)
from bot.utils.cache import cache
import bot.utils.database as app_db
from bot.core.bot import bot_client

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

_OWNER_WARN = (
    "⛔ **Access Denied!**\n\n"
    "💀 *\"Yohohoho! Only the Captain can use this command!\"*\n"
    "This command is reserved for the **bot owner** only."
)

_SUDO_WARN = (
    "⛔ **Access Denied!**\n\n"
    "💀 *\"Yohohoho! You're not part of the Soul King's trusted crew!\"*\n"
    "This command requires **sudo/owner** privileges."
)

_ADMIN_WARN = (
    "⛔ **Access Denied!**\n\n"
    "💀 *\"Yohohoho! Only group admins may wield this power!\"*\n"
    "This command is for **group admins** only."
)


async def _resolve_target(message: Message, client: Client) -> tuple[int | None, str]:
    """
    Resolve target user_id and name from:
      - a reply, OR
      - command arg (user_id or @username)
    Returns (user_id, name) or (None, "") on failure.
    """
    if message.reply_to_message and message.reply_to_message.from_user:
        u = message.reply_to_message.from_user
        return u.id, u.first_name

    if len(message.command) >= 2:
        arg = message.command[1]
        try:
            user = await client.get_users(int(arg) if arg.lstrip("-").isdigit() else arg)
            return user.id, user.first_name
        except (PeerIdInvalid, BadRequest, KeyError):
            await message.reply("❌ User not found. Provide a valid user ID or @username.")
        except Exception as e:
            await message.reply(f"❌ Error resolving user: `{e}`")

    return None, ""


# ─────────────────────────────────────────────
# /addsudo — Owner/Sudo, group + private
# ─────────────────────────────────────────────

@Client.on_message(filters.command("addsudo") & (filters.group | filters.private))
@require_sudo
async def addsudo_cmd(client: Client, message: Message):
    """Grant sudo privileges to a user (owner/sudo)."""
    caller = message.from_user.id if message.from_user else None
    if not caller:
        return

    if not await is_sudo(caller):
        await message.reply(_SUDO_WARN)
        return

    if len(message.command) < 2 and not message.reply_to_message:
        await message.reply(
            "📖 **Usage:** `/addsudo [user_id/@username]`\nor reply to a user's message."
        )
        return

    user_id, name = await _resolve_target(message, client)
    if not user_id:
        return

    if user_id == config.OWNER_ID:
        await message.reply("💀 Owner is already the supreme commander, Yohoho!")
        return

    if app_db.db and await app_db.db.is_sudo(user_id):
        await message.reply(f"ℹ️ `{name}` (`{user_id}`) is already in the crew!")
        return

    try:
        await app_db.db.add_sudo(user_id, name, caller)
        await message.reply(
            f"💀 **YOHOHOHO!** [`{name}`](tg://user?id={user_id}) (`{user_id}`) has joined the "
            f"Soul King's trusted crew as a **sudo user**! ⚔️"
        )
        logger.info(f"Sudo added: {user_id} by {caller}")
    except Exception as e:
        logger.error(f"addsudo failed: {e}")
        await message.reply(f"❌ Failed to add sudo: `{e}`")


# ─────────────────────────────────────────────
# /delsudo — Owner/Sudo, group + private
# ─────────────────────────────────────────────

@Client.on_message(filters.command("delsudo") & (filters.group | filters.private))
@require_sudo
async def delsudo_cmd(client: Client, message: Message):
    """Revoke sudo privileges (owner/sudo)."""
    caller = message.from_user.id if message.from_user else None
    if not caller:
        return

    if not await is_sudo(caller):
        await message.reply(_SUDO_WARN)
        return

    if len(message.command) < 2 and not message.reply_to_message:
        await message.reply("📖 **Usage:** `/delsudo [user_id/@username]`\nor reply to a user's message.")
        return

    user_id, name = await _resolve_target(message, client)
    if not user_id:
        return

    if user_id == config.OWNER_ID:
        await message.reply("❌ Cannot remove the bot owner from the crew!")
        return

    if app_db.db and not await app_db.db.is_sudo(user_id):
        await message.reply(f"ℹ️ User `{user_id}` is not in the sudo list.")
        return

    try:
        await app_db.db.remove_sudo(user_id)
        await message.reply(
            f"💀 User `{user_id}` has walked the plank and been removed from the crew! Yohoho!"
        )
        logger.info(f"Sudo removed: {user_id} by {caller}")
    except Exception as e:
        logger.error(f"delsudo failed: {e}")
        await message.reply(f"❌ Failed to remove sudo: `{e}`")


# ─────────────────────────────────────────────
# /sudolist — Owner/Sudo, group + private
# ─────────────────────────────────────────────

@Client.on_message(filters.command("sudolist") & (filters.group | filters.private))
@require_sudo
async def sudolist_cmd(client: Client, message: Message):
    """List all sudo users (owner/sudo)."""
    caller = message.from_user.id if message.from_user else None
    if not caller:
        return

    if not await is_sudo(caller):
        await message.reply(_SUDO_WARN)
        return

    try:
        sudos = await app_db.db.get_sudo_users() if app_db.db else []
    except Exception:
        sudos = []

    if not sudos:
        await message.reply("📭 No sudo users in the crew yet, Yohoho!")
        return

    lines = ["💀⚔️ **The Soul King's Trusted Crew (Sudo Users):**\n"]
    for sudo in sudos:
        uid = sudo.get("_id", sudo.get("id", "?"))
        uname = sudo.get("name", "Unknown")
        lines.append(f"• `{uid}` — {uname}")

    await message.reply("\n".join(lines))


# ─────────────────────────────────────────────
# /gban — Sudo+, group + private
# ─────────────────────────────────────────────

@Client.on_message(filters.command("gban") & (filters.group | filters.private))
@require_sudo
async def gban_cmd(client: Client, message: Message):
    """Globally ban a user (sudo+)."""
    caller = message.from_user.id if message.from_user else None
    if not caller:
        return

    if not await is_sudo(caller):
        await message.reply(_SUDO_WARN)
        return

    if len(message.command) < 2 and not message.reply_to_message:
        await message.reply("📖 **Usage:** `/gban [user_id/@username] [reason]`\nor reply to a user's message.")
        return

    user_id, name = await _resolve_target(message, client)
    if not user_id:
        return

    # Protection checks
    if user_id == config.OWNER_ID:
        await message.reply("❌ Cannot ban the bot owner! Yohoho!")
        return
    if app_db.db and await app_db.db.is_sudo(user_id):
        await message.reply("❌ Cannot ban a sudo crew member!")
        return

    # Extract reason (everything after the first arg)
    reason = "No reason provided"
    if len(message.command) > 2:
        reason = " ".join(message.command[2:])
    elif message.reply_to_message and len(message.command) > 1:
        reason = " ".join(message.command[1:])

    try:
        await app_db.db.gban_user(user_id, reason, caller)
        await cache.cache_gban(user_id, True)

        await message.reply(
            f"🚫 **Globally Banned** `{name or user_id}` (`{user_id}`) from the Soul King's seas!\n"
            f"📝 **Reason:** {reason}\n\n"
            f"<i>Yohoho! This scoundrel shall never play music again!</i>",
            parse_mode="html"
        )
        logger.warning(f"GBan: {user_id} by {caller} reason='{reason}'")
    except Exception as e:
        logger.error(f"gban failed: {e}")
        await message.reply(f"❌ Failed to gban: `{e}`")


# ─────────────────────────────────────────────
# /ungban — Sudo+, group + private
# ─────────────────────────────────────────────

@Client.on_message(filters.command("ungban") & (filters.group | filters.private))
@require_sudo
async def ungban_cmd(client: Client, message: Message):
    """Remove global ban (sudo+)."""
    caller = message.from_user.id if message.from_user else None
    if not caller:
        return

    if not await is_sudo(caller):
        await message.reply(_SUDO_WARN)
        return

    if len(message.command) < 2 and not message.reply_to_message:
        await message.reply("📖 **Usage:** `/ungban [user_id/@username]`\nor reply to a user's message.")
        return

    user_id, name = await _resolve_target(message, client)
    if not user_id:
        return

    try:
        if app_db.db and not await app_db.db.is_gbanned(user_id):
            await message.reply(f"ℹ️ User `{user_id}` is not globally banned.")
            return

        await app_db.db.ungban_user(user_id)
        await cache.cache_gban(user_id, False)

        await message.reply(
            f"✅ Freed! `{name or user_id}` (`{user_id}`) can sail the Soul King's seas once more!\n"
            f"<i>Yohohoho! Welcome back to the music!</i>",
            parse_mode="html"
        )
        logger.info(f"UnGBan: {user_id} by {caller}")
    except Exception as e:
        logger.error(f"ungban failed: {e}")
        await message.reply(f"❌ Failed to ungban: `{e}`")


# ─────────────────────────────────────────────
# /block — Admin+ in group, Sudo+ in private
# ─────────────────────────────────────────────

@Client.on_message(filters.command("block") & (filters.group | filters.private))
@require_sudo
async def block_cmd(client: Client, message: Message):
    """Block user (sudo+)."""
    caller = message.from_user.id if message.from_user else None
    chat_id = message.chat.id if message.chat else None
    if not caller or not chat_id:
        return

    level = await get_permission_level(caller, chat_id)

    # In groups require admin; in PM require sudo
    if message.chat.type in ("group", "supergroup"):
        if level < 3:
            await message.reply(_ADMIN_WARN)
            return
    else:
        if level < 4:
            await message.reply(_SUDO_WARN)
            return

    if len(message.command) < 2 and not message.reply_to_message:
        await message.reply("📖 **Usage:** `/block [user_id/@username]`\nor reply to a user's message.")
        return

    user_id, name = await _resolve_target(message, client)
    if not user_id:
        return

    if user_id == config.OWNER_ID or (app_db.db and await app_db.db.is_sudo(user_id)):
        await message.reply("❌ Cannot block a privileged user!")
        return

    try:
        await app_db.db.ban_user(chat_id, user_id)
        await message.reply(
            f"🚫 `{name or user_id}` (`{user_id}`) has been **blocked** from the music den in this group!\n"
            f"<i>Yohoho! No music for you!</i>",
            parse_mode="html"
        )
        logger.info(f"Blocked {user_id} in {chat_id} by {caller}")
    except Exception as e:
        logger.error(f"block failed: {e}")
        await message.reply(f"❌ Failed to block: `{e}`")


# ─────────────────────────────────────────────
# /unblock — Admin+ in group, Sudo+ in private
# ─────────────────────────────────────────────

@Client.on_message(filters.command("unblock") & (filters.group | filters.private))
@require_sudo
async def unblock_cmd(client: Client, message: Message):
    """Unblock user (sudo+)."""
    caller = message.from_user.id if message.from_user else None
    chat_id = message.chat.id if message.chat else None
    if not caller or not chat_id:
        return

    level = await get_permission_level(caller, chat_id)

    if message.chat.type in ("group", "supergroup"):
        if level < 3:
            await message.reply(_ADMIN_WARN)
            return
    else:
        if level < 4:
            await message.reply(_SUDO_WARN)
            return

    if len(message.command) < 2 and not message.reply_to_message:
        await message.reply("📖 **Usage:** `/unblock [user_id/@username]`\nor reply to a user's message.")
        return

    user_id, name = await _resolve_target(message, client)
    if not user_id:
        return

    try:
        await app_db.db.unban_user(chat_id, user_id)
        await message.reply(
            f"✅ `{name or user_id}` (`{user_id}`) is **welcome back** in the music den!\n"
            f"<i>YOHOHOHO! Come listen to the Soul King!</i>",
            parse_mode="html"
        )
        logger.info(f"Unblocked {user_id} in {chat_id} by {caller}")
    except Exception as e:
        logger.error(f"unblock failed: {e}")
        await message.reply(f"❌ Failed to unblock: `{e}`")


# ─────────────────────────────────────────────
# /stats — Sudo+, group + private
# ─────────────────────────────────────────────

@Client.on_message(filters.command("stats") & (filters.group | filters.private))
@require_sudo
async def stats_cmd(client: Client, message: Message):
    """Show bot statistics (sudo+)."""
    caller = message.from_user.id if message.from_user else None
    if not caller:
        return

    if not await is_sudo(caller):
        await message.reply(_SUDO_WARN)
        return

    try:
        stats = await app_db.db.get_stats() if app_db.db else {}
    except Exception:
        stats = {}

    # Count active voice chats
    try:
        from bot.core.call import call_manager
        active_vc = len(call_manager.active_chats)
    except Exception:
        active_vc = 0

    text = (
        "📊 **SOUL KING BOT — STATISTICS**\n\n"
        "👥 **Groups:**\n"
        f"• Total: `{stats.get('total_groups', 'N/A')}`\n"
        f"• Active: `{stats.get('active_groups', 'N/A')}`\n"
        f"• Live VCs: `{active_vc}`\n\n"
        "👑 **Permissions:**\n"
        f"• Sudo Users: `{stats.get('sudo_users', 'N/A')}`\n"
        f"• Globally Banned: `{stats.get('gbanned_users', 'N/A')}`\n\n"
        "⚙️ **System:**\n"
        f"• Python: `{platform.python_version()}`\n"
        f"• Platform: `{sys.platform}`\n"
        f"• Bot Version: `2.0 — Pro Mode`\n\n"
        "<i>\"I may be a skeleton, but these stats are very much alive! YOHOHOHO!\"</i>"
    )

    await message.reply(text, parse_mode="html")


# ─────────────────────────────────────────────
# /broadcast — Owner/Sudo, group + private
# ─────────────────────────────────────────────

@Client.on_message(filters.command("broadcast") & (filters.group | filters.private))
@require_sudo
async def broadcast_cmd(client: Client, message: Message):
    """Broadcast a message (owner/sudo)."""
    caller = message.from_user.id if message.from_user else None
    if not caller:
        return

    if not await is_sudo(caller):
        await message.reply(_SUDO_WARN)
        return

    if len(message.command) < 2 and not message.reply_to_message:
        await message.reply(
            "📖 **Usage:** `/broadcast [message]`\nor reply to any message to forward it."
        )
        return

    broadcast_msg = message.reply_to_message if message.reply_to_message else None
    broadcast_text = " ".join(message.command[1:]) if not broadcast_msg else None

    try:
        groups = await app_db.db.get_all_groups() if app_db.db else []
    except Exception:
        groups = []

    if not groups:
        await message.reply("📭 No active groups to broadcast to.")
        return

    status_msg = await message.reply(f"📢 Broadcasting to **{len(groups)}** groups...")

    success = 0
    failed = 0

    for group in groups:
        gid = group.get("_id") or group.get("id")
        if not gid:
            continue
        try:
            if broadcast_msg:
                await broadcast_msg.copy(gid)
            else:
                await bot_client.send_message(gid, broadcast_text)
            success += 1
            await asyncio.sleep(0.08)  # Respect Telegram rate limits
        except FloodWait as e:
            await asyncio.sleep(e.value + 1)
            success += 1  # Retry not implemented, count as failed
        except Exception as e:
            failed += 1
            logger.warning(f"Broadcast failed for {gid}: {e}")

    try:
        await status_msg.edit(
            f"<b>📢 Broadcast complete! Yohohoho!</b>\n\n"
            f"✅ Delivered: <code>{success}</code> groups\n"
            f"❌ Failed: <code>{failed}</code> groups",
            parse_mode="html"
        )
    except Exception:
        pass


# ─────────────────────────────────────────────
# /restart — Owner/Sudo, group + private
# ─────────────────────────────────────────────

@Client.on_message(filters.command("restart") & (filters.group | filters.private))
@require_sudo
async def restart_cmd(client: Client, message: Message):
    """Restart bot (owner/sudo)."""
    caller = message.from_user.id if message.from_user else None
    if not caller:
        return

    if not await is_sudo(caller):
        await message.reply(_SUDO_WARN)
        return

    await message.reply(
        "🔄 **Restarting the Soul King's ship!**\n"
        "<i>BRB... adjusting my violin strings! Yohoho!</i>",
        parse_mode="html"
    )
    logger.info(f"Restart requested by {caller}")

    await asyncio.sleep(1)  # Let the reply send before exiting
    sys.exit(0)  # Supervisor/Docker will restart the process


# ─────────────────────────────────────────────
# /maintenance — Owner/Sudo, group + private
# ─────────────────────────────────────────────

@Client.on_message(filters.command("maintenance") & (filters.group | filters.private))
@require_sudo
async def maintenance_cmd(client: Client, message: Message):
    """Toggle maintenance mode (owner/sudo)."""
    caller = message.from_user.id if message.from_user else None
    if not caller:
        return

    if not await is_sudo(caller):
        await message.reply(_SUDO_WARN)
        return

    # No argument — show current status
    if len(message.command) < 2:
        current = await cache.is_maintenance()
        status_str = "🔧 **ON**" if current else "✅ **OFF**"
        await message.reply(
            f"🛠 **Maintenance Mode:** {status_str}\n\n"
            f"📖 **Usage:** `/maintenance [on/off]`"
        )
        return

    arg = message.command[1].lower()

    if arg in ("on", "true", "1", "yes"):
        await cache.set_maintenance(True)
        await message.reply(
            "🔧 **Maintenance mode ON!**\n"
            "<i>The Soul King is taking a break to polish his violin...\n"
            "Only sudo users may command the bot for now.</i>",
            parse_mode="html"
        )
        logger.warning(f"Maintenance mode ENABLED by {caller}")

    elif arg in ("off", "false", "0", "no"):
        await cache.set_maintenance(False)
        await message.reply(
            "✅ **Maintenance mode OFF!**\n"
            "<i>The Soul King is back on stage — YOHOHOHO! 🎸🎵</i>",
            parse_mode="html"
        )
        logger.info(f"Maintenance mode DISABLED by {caller}")

    else:
        await message.reply("❌ Invalid argument. Use `on` or `off`.")
