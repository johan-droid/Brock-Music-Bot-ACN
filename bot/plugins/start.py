"""Start command: /start in private and groups."""

import os
import logging
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.enums import ParseMode
from config import config
import bot.utils.database as app_db

logger = logging.getLogger(__name__)

# Cache Telegram file_id after first upload to avoid re-uploading every time
_START_IMAGE_FILE_ID: str = None

# Path to the local Brook welcome image
_LOCAL_IMAGE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "assets", "brook_start.png")


def _build_start_text(mention: str) -> str:
    return (
        f"🍁 Hey there... <b>{mention}</b>\n"
        "I am the Soul King, Brook! 🦴\n\n"
        "Welcome, my friend! I see you have a wonderful soul… although I don't have eyes to see it! "
        "<i>Skull joke! Yohohoho!</i> 💀🎩\n\n"
        "I am here to bring the music of the seas straight to your voice chats! "
        "Whether it's <b>Bink's Sake</b> or your favorite modern tunes, I shall play them with melodies that touch the soul!\n\n"
        "<b>┃ Main Features ❞</b>\n"
        "• 🎵 High-quality audio streaming\n"
        "• 🎥 Video chat support\n"
        "• 📋 Smooth &amp; advanced queue system\n"
        "• 🔍 Smart search &amp; title detection\n\n"
        "<i>\"Music is the medicine of the soul… which is good, because I'm already dead! Yohohoho!\"</i> 💀🎻\n\n"
        "Tap on /help to explore everything I can do! ⚡️"
    )


def _build_private_buttons() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "➕ Add Soul King to Group",
                url=f"https://t.me/{config.BOT_USERNAME}?startgroup=true"
            ),
        ],
        [
            InlineKeyboardButton("📖 Help", callback_data="help_menu"),
            InlineKeyboardButton("🎸 Support", url="https://t.me/SoulKingSupport"),
        ]
    ])


def _build_group_buttons() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📖 Help", callback_data="help_menu"),
            InlineKeyboardButton("🎬 Status", callback_data="status_check"),
        ]
    ])


async def _send_with_image(message: Message, text: str, buttons: InlineKeyboardMarkup):
    """Send the start message. Uses cached file_id → local file → text fallback."""
    global _START_IMAGE_FILE_ID

    # 1. Try cached Telegram file_id (instant, no re-upload)
    if _START_IMAGE_FILE_ID:
        try:
            sent = await message.reply_photo(
                photo=_START_IMAGE_FILE_ID,
                caption=text,
                reply_markup=buttons,
                parse_mode=ParseMode.HTML,
            )
            return
        except Exception as e:
            logger.warning(f"Cached file_id send failed, re-uploading: {e}")
            _START_IMAGE_FILE_ID = None

    # 2. Try local file upload (forces bytes upload — avoids WEBPAGE_MEDIA_EMPTY)
    if os.path.exists(_LOCAL_IMAGE_PATH):
        try:
            with open(_LOCAL_IMAGE_PATH, "rb") as img:
                sent = await message.reply_photo(
                    photo=img,
                    caption=text,
                    reply_markup=buttons,
                    parse_mode=ParseMode.HTML,
                )
            # Cache the file_id for future /start calls
            if sent.photo:
                _START_IMAGE_FILE_ID = sent.photo.file_id
                logger.info("Brook start image uploaded and file_id cached.")
            return
        except Exception as e:
            logger.warning(f"Local image upload failed: {e}")

    # 3. Final fallback: text only
    await message.reply_text(
        text=text,
        reply_markup=buttons,
        parse_mode=ParseMode.HTML,
    )


@Client.on_message(filters.command("start") & filters.private)
async def start_private(client: Client, message: Message):
    """Handle /start in DMs — personalized Brook welcome."""
    mention = message.from_user.mention if message.from_user else "friend"
    text = _build_start_text(mention)
    buttons = _build_private_buttons()
    await _send_with_image(message, text, buttons)


@Client.on_message(filters.command("start") & filters.group)
async def start_group(client: Client, message: Message):
    """Handle /start in groups — concise Brook group welcome."""
    group_name = message.chat.title or "your group"
    mention = message.from_user.mention if message.from_user else "friend"

    text = (
        f"<b>Yohohoho! The Soul King has arrived in {group_name}!</b> 💀🎵\n\n"
        f"Hey {mention}! I'm ready to perform!\n"
        f"Use <code>/play [song name]</code> to start a concert in your Voice Chat!\n\n"
        "<i>\"A heart is a heavy burden… good thing I don't have one! Yohohoho!\"</i>"
    )
    buttons = _build_group_buttons()
    await message.reply_text(text, reply_markup=buttons, parse_mode=ParseMode.HTML)
