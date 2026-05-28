"""Start command: /start in private and groups."""

import os
import logging
from pyrogram import Client, filters
from typing import Any, cast

Client = cast(Any, Client)
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
        f"🎻 Yohohoho! Welcome aboard, <b>{mention}</b>!\n"
        "I am <b>Brook</b>, the Soul King of the Straw Hat crew. 🦴🎩\n\n"
        "I bring concerts to your voice chats with all the flair of a grand stage on the high seas. "
        "Whether you want a calm midnight melody, a rowdy crew anthem, or a full-on Bink's Sake mood, I am ready to perform.\n\n"
        "<b>┃ Soul King's Repertoire ❞</b>\n"
        "• 🎵 Stream tracks from your external music server\n"
        "• 🎬 Fill voice chats with audio and video performances\n"
        "• 📋 Build setlists, playlists, and radio-style sessions\n"
        "• 🔍 Hunt songs by title, mood, and vibe\n\n"
        "<i>\"Music is something that reaches the soul directly... fortunate for me, because I'm all soul! Yohohoho!\"</i> 💀🎻\n\n"
        "Tap /help and let us begin tonight's performance."
    )


def _build_private_buttons() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "➕ Invite Brook to Group",
                url=f"https://t.me/{config.BOT_USERNAME}?startgroup=true"
            ),
        ],
        [
            InlineKeyboardButton("📖 Songbook", callback_data="help_menu"),
            InlineKeyboardButton("🎸 Crew Support", url="https://t.me/SoulKingSupport"),
        ]
    ])


def _build_group_buttons() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📖 Songbook", callback_data="help_menu"),
            InlineKeyboardButton("🎬 Stage Status", callback_data="status_check"),
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
    if config.BOUND_GROUP_ID is not None and message.chat.id != config.BOUND_GROUP_ID:
        await message.reply(
            "⛔ This bot is bound to a different group and cannot be used here.",
            parse_mode=ParseMode.HTML
        )
        return

    group_name = message.chat.title or "your group"
    mention = message.from_user.mention if message.from_user else "friend"

    text = (
        f"<b>Yohohoho! Brook has taken the stage in {group_name}!</b> 💀🎵\n\n"
        f"Hey {mention}, the Soul King is tuned up and ready.\n"
        f"Use <code>/play [song name]</code> to begin a live concert in this crew's voice chat.\n\n"
        "<i>\"Let us fill the sea with music until even the stars start singing!\"</i>"
    )
    buttons = _build_group_buttons()
    await message.reply_text(text, reply_markup=buttons, parse_mode=ParseMode.HTML)
