"""Start command: /start in private and groups."""

import os
import logging
import asyncio
from pyrogram import Client, filters
from typing import Any, cast

Client = cast(Any, Client)
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.enums import ParseMode
from config import config
import bot.utils.database as app_db

logger = logging.getLogger(__name__)

# Cache Telegram file_id after first upload to avoid re-uploading every time
_START_MEDIA_FILE_ID: str = None
_START_MEDIA_KIND: str = None

_ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "assets")
_START_MEDIA_CANDIDATES = (
    ("animation", os.path.join(_ASSETS_DIR, "brook_start.mp4")),
    ("animation", os.path.join(_ASSETS_DIR, "brook_start.gif")),
    ("animation", os.path.join(_ASSETS_DIR, "brook_start.webm")),
    ("photo", os.path.join(_ASSETS_DIR, "brook_start.png")),
)
_BROOK_STAGE_FRAMES = (
    "🎶 <i>Brook tunes his violin... yohohoho...</i>",
    "🎵 <i>The Soul King sways with the rhythm of the Grand Line...</i>",
    "💀 <i>The stage is set. Let the concert begin!</i>",
)


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


def _resolve_start_media() -> tuple[str, str] | tuple[None, None]:
    for media_kind, path in _START_MEDIA_CANDIDATES:
        if os.path.exists(path):
            return media_kind, path
    return None, None


def _with_stage_frame(text: str, frame: str) -> str:
    return f"{text}\n\n{frame}"


async def _animate_sent_start_message(sent: Message, base_text: str, buttons: InlineKeyboardMarkup) -> None:
    for idx, frame in enumerate(_BROOK_STAGE_FRAMES):
        try:
            await asyncio.sleep(0.9 if idx == 0 else 0.8)
            animated_text = _with_stage_frame(base_text, frame)
            if sent.photo or sent.animation or sent.video:
                await sent.edit_caption(
                    caption=animated_text,
                    reply_markup=buttons,
                    parse_mode=ParseMode.HTML,
                )
            else:
                await sent.edit_text(
                    text=animated_text,
                    reply_markup=buttons,
                    parse_mode=ParseMode.HTML,
                )
        except Exception as e:
            logger.debug(f"Brook intro animation ended early: {e}")
            return


async def _send_with_image(message: Message, text: str, buttons: InlineKeyboardMarkup):
    """Send the start message. Uses cached media → local asset → text fallback."""
    global _START_MEDIA_FILE_ID, _START_MEDIA_KIND

    # 1. Try cached Telegram file_id (instant, no re-upload)
    if _START_MEDIA_FILE_ID and _START_MEDIA_KIND:
        try:
            if _START_MEDIA_KIND == "animation":
                sent = await message.reply_animation(
                    animation=_START_MEDIA_FILE_ID,
                    caption=text,
                    reply_markup=buttons,
                    parse_mode=ParseMode.HTML,
                )
            else:
                sent = await message.reply_photo(
                    photo=_START_MEDIA_FILE_ID,
                    caption=text,
                    reply_markup=buttons,
                    parse_mode=ParseMode.HTML,
                )
            asyncio.create_task(_animate_sent_start_message(sent, text, buttons))
            return
        except Exception as e:
            logger.warning(f"Cached Brook media send failed, retrying local asset: {e}")
            _START_MEDIA_FILE_ID = None
            _START_MEDIA_KIND = None

    # 2. Try local asset upload (prefer animation, then fallback image)
    media_kind, media_path = _resolve_start_media()
    if media_kind and media_path:
        try:
            with open(media_path, "rb") as media:
                if media_kind == "animation":
                    sent = await message.reply_animation(
                        animation=media,
                        caption=text,
                        reply_markup=buttons,
                        parse_mode=ParseMode.HTML,
                    )
                else:
                    sent = await message.reply_photo(
                        photo=media,
                        caption=text,
                        reply_markup=buttons,
                        parse_mode=ParseMode.HTML,
                    )
            if sent.animation:
                _START_MEDIA_FILE_ID = sent.animation.file_id
                _START_MEDIA_KIND = "animation"
            elif sent.photo:
                _START_MEDIA_FILE_ID = sent.photo.file_id
                _START_MEDIA_KIND = "photo"
            if _START_MEDIA_FILE_ID:
                logger.info("Brook start media uploaded and file_id cached.")
            asyncio.create_task(_animate_sent_start_message(sent, text, buttons))
            return
        except Exception as e:
            logger.warning(f"Local Brook media upload failed: {e}")

    # 3. Final fallback: text only
    sent = await message.reply_text(
        text=text,
        reply_markup=buttons,
        parse_mode=ParseMode.HTML,
    )
    asyncio.create_task(_animate_sent_start_message(sent, text, buttons))


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
