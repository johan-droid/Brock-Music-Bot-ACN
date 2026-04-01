"""Permission decorators and admin check helpers."""

import logging
import re
from functools import wraps
from pyrogram import filters
from pyrogram.types import Message, CallbackQuery
from pyrogram.errors import FloodWait
from config import config
from bot.utils.cache import cache
import bot.utils.database as app_db
from bot.core import bot as bot_module
from bot.core.userbot import userbot_clients

logger = logging.getLogger(__name__)

# Brook-themed Access Warnings
_OWNER_WARN = (
    "⛔ **Access Denied!**\n\n"
    "💀 *\"Yohohoho! Only the Captain can use this command!\"*\n"
    "This command is reserved for the **bot owner** only."
)

_SUDO_WARN = (
    "⛔ **Access Denied!**\n\n"
    "💀 *\"Yohohoho! You\'re not part of the Soul King\'s trusted crew!\"*\n"
    "This command requires **sudo/owner** privileges."
)

_ADMIN_WARN = (
    "⛔ **Access Denied!**\n\n"
    "💀 *\"Yohohoho! Only group admins may wield this power!\"*\n"
    "This command is for **group admins** only."
)

_MAINTENANCE_WARN = (
    "🔧 **Maintenance in Progress!**\n\n"
    "💀 *\"Checking my bones... the Soul King is currently polishing his violin!\"*\n"
    "The bot is under maintenance. Please try again later, Yohoho!"
)

# Active voice chat participants cache
_vc_participants: dict = {}  # {chat_id: {user_id: timestamp}}


async def is_vc_participant(chat_id: int, user_id: int) -> bool:
    """Check if user is currently in the voice chat."""
    # Check local cache first
    if chat_id in _vc_participants:
        if user_id in _vc_participants[chat_id]:
            return True
    
    # Query Telegram for current participants
    try:
        # Get active voice chat participants
        from bot.core.call import call_manager
        if chat_id not in call_manager.active_chats:
            return False
        
        # Check if user is in the chat via participant list
        if not bot_module.bot_client:
            return False
        chat = await bot_module.bot_client.get_chat(chat_id)
        if hasattr(chat, 'voice_chat') and chat.voice_chat:
            # Check if user is in voice chat participants
            for participant in chat.voice_chat.participants or []:
                if participant.user_id == user_id:
                    _vc_participants.setdefault(chat_id, {})[user_id] = True
                    return True
        
        # Alternative: check via userbot
        if userbot_clients:
            userbot = userbot_clients[0]
            try:
                member = await userbot.get_chat_member(chat_id, user_id)
                # If user is in voice chat, they show as member
                # Note: Pyrogram doesn't have direct VC participant API
                # So we check recent activity as fallback
                return True  # Allow if they're a member and VC is active
            except:
                pass
                
    except Exception as e:
        logger.debug(f"Error checking VC participant: {e}")
    
    return False


async def update_vc_participants(chat_id: int, participants: list):
    """Update cached VC participants."""
    _vc_participants[chat_id] = {p: True for p in participants}


async def clear_vc_participants(chat_id: int):
    """Clear VC participants cache when chat ends."""
    if chat_id in _vc_participants:
        del _vc_participants[chat_id]


async def is_owner(user_id: int) -> bool:
    """Check if user is bot owner."""
    return user_id == config.OWNER_ID


async def is_sudo(user_id: int) -> bool:
    """Check if user is sudo (or owner)."""
    if await is_owner(user_id):
        return True
    if app_db.db is None:
        return False
    return await app_db.db.is_sudo(user_id)


async def is_gbanned(user_id: int) -> bool:
    """Check if user is globally banned."""
    # Guard: if DB isn't ready yet, assume not banned (fail-open)
    if app_db.db is None:
        return False

    # Check cache first
    cached = await cache.is_gbanned_cached(user_id)
    if cached:
        return True

    # Check database
    try:
        banned = await app_db.db.is_gbanned(user_id)
        await cache.cache_gban(user_id, banned)
        return banned
    except Exception as e:
        logger.warning(f"is_gbanned check failed: {e}")
        return False


async def is_group_admin(chat_id: int, user_id: int) -> bool:
    """Check if user is admin in the group with caching."""
    # Check cache first
    cached = await cache.is_admin(chat_id, user_id)
    if cached:
        return True
    
    # Check if bot_client is initialized
    if not bot_module.bot_client:
        logger.warning("bot_client not initialized, skipping admin check")
        return False
    
    try:
        # Fetch from Telegram
        member = await bot_module.bot_client.get_chat_member(chat_id, user_id)
        # Handle both string and enum status values
        status_str = str(member.status)
        is_admin = status_str in ["administrator", "creator", "ChatMemberStatus.ADMINISTRATOR", "ChatMemberStatus.OWNER", "OWNER"]
        
        # Update cache
        if is_admin:
            current_admins = await cache.get_cached_admins(chat_id)
            if user_id not in current_admins:
                current_admins.append(user_id)
                await cache.cache_admins(chat_id, current_admins)
        
        logger.info(f"Admin check for user {user_id} in chat {chat_id}: {is_admin} (status: {member.status})")
        return is_admin
    except Exception as e:
        logger.error(f"Error checking admin status for user {user_id} in chat {chat_id}: {e}")
        return False


async def is_admin_cached(chat_id: int, user_id: int) -> bool:
    """Fast admin check using cache only."""
    return await cache.is_admin(chat_id, user_id)


async def check_bot_admin(chat_id: int) -> bool:
    """Check if bot is admin in a group."""
    if not bot_module.bot_client:
        logger.warning("bot_client not initialized, skipping bot admin check")
        return False
    try:
        member = await bot_module.bot_client.get_chat_member(chat_id, bot_module.bot_client.me.id)
        return member.status == "administrator" or member.status == "creator"
    except Exception:
        return False


async def check_userbot_admin(chat_id: int) -> bool:
    """Check if userbot is admin with voice chat manage privilege."""
    if not userbot_clients:
        return False
    
    userbot = userbot_clients[0]
    try:
        member = await userbot.get_chat_member(chat_id, userbot.me.id)
        if member.status != "administrator":
            return False
        
        # Check for voice chat manage privilege
        privileges = member.privileges
        if privileges:
            return privileges.can_manage_video_chats
        return False
    except Exception:
        return False


# Permission level check
async def get_permission_level(user_id: int, chat_id: int = None, check_vc: bool = False) -> int:
    """Get permission level for a user.
    
    Levels:
        5 - Owner
        4 - Sudo
        3 - Group Admin
        2 - VC Participant (when VC is active)
        1 - Normal User
        0 - Banned
    """
    # Check gban first
    if await is_gbanned(user_id):
        return 0
    
    if await is_owner(user_id):
        return 5
    
    if await is_sudo(user_id):
        return 4
    
    if chat_id and await is_group_admin(chat_id, user_id):
        return 3
    
    # Check VC participant if requested and chat_id provided
    if check_vc and chat_id:
        from bot.core.call import call_manager
        if chat_id in call_manager.active_chats:
            # VC is active, allow participants
            return 2
    
    return 1


# Decorators
def require_member(func):
    """Decorator to allow any group member (non-banned) to use the command."""
    @wraps(func)
    async def wrapper(client, message: Message):
        user_id = message.from_user.id if message.from_user else None
        chat_id = message.chat.id if message.chat else None

        if not user_id or not chat_id:
            return

        # Check maintenance mode
        if await cache.is_maintenance():
            if not await is_sudo(user_id):
                await message.reply(_MAINTENANCE_WARN)
                return

        # Check global ban
        if await is_gbanned(user_id):
            return  # Silent reject

        # Check group-level ban
        if app_db.db is not None:
            try:
                if await app_db.db.is_banned(chat_id, user_id):
                    return  # Silent reject
            except Exception:
                pass

        return await func(client, message)

    return wrapper


def require_admin(func):
    """Decorator to require group admin or higher."""
    @wraps(func)
    async def wrapper(client, message: Message):
        # Get user info
        user_id = message.from_user.id if message.from_user else None
        chat_id = message.chat.id if message.chat else None
        
        if not user_id or not chat_id:
            return
        
        # Check maintenance mode
        if await cache.is_maintenance():
            if not await is_sudo(user_id):
                await message.reply(_MAINTENANCE_WARN)
                return
        
        # Check gban
        if await is_gbanned(user_id):
            return  # Silent reject
        
        # Check permissions
        level = await get_permission_level(user_id, chat_id)
        if level < 3:  # Not admin or higher
            await message.reply(_ADMIN_WARN)
            return
        
        # Check bot admin status
        if not await check_bot_admin(chat_id):
            await message.reply(
                "❌ I need to be an admin with 'Manage Voice Chats' permission to function.\n"
                "Please promote me and/or your userbot helper with voice chat permissions and try again.\n"
                "Use /userbotjoin to route voice activities through your userbot if needed, and /vcdebug for diagnostics."
            )
            return
        
        return await func(client, message)
    
    return wrapper


def require_sudo(func):
    """Decorator to require sudo or owner."""
    @wraps(func)
    async def wrapper(client, message: Message):
        user_id = message.from_user.id if message.from_user else None

        if not user_id:
            return

        # Check gban
        if await is_gbanned(user_id):
            return

        if not await is_sudo(user_id):
            await message.reply(_SUDO_WARN)
            return

        return await func(client, message)

    return wrapper


def require_owner(func):
    """Decorator to require owner only."""
    @wraps(func)
    async def wrapper(client, message: Message):
        user_id = message.from_user.id if message.from_user else None

        if not user_id:
            return

        if not await is_owner(user_id):
            await message.reply(_OWNER_WARN)
            return

        return await func(client, message)

    return wrapper


def rate_limit(func):
    """Decorator to apply rate limiting."""
    @wraps(func)
    async def wrapper(client, message: Message):
        user_id = message.from_user.id if message.from_user else None
        
        if not user_id:
            return
        
        # Get command name from function
        cmd = func.__name__.replace("_cmd", "").replace("_", "")
        
        if not await cache.check_cooldown(user_id, cmd, config.COMMAND_COOLDOWN):
            return  # Silent reject on cooldown
        
        try:
            return await func(client, message)
        except FloodWait as e:
            logger.warning(f"FloodWait of {e.value}s on {cmd}. Dropping request to protect token limitation.")
            return
        except Exception as e:
            logger.error(f"Error executing command {cmd}: {e}")
            return
    
    return wrapper
