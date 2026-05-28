from pyrogram import Client, filters
from typing import Any, cast

Client = cast(Any, Client)
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pyrogram.enums import ParseMode
from bot.utils.effects_engine import get_active_effect, set_active_effect
from bot.utils.permissions import require_admin, get_permission_level, rate_limit

EFFECTS_OPTIONS = [
    "8D Audio",
    "Slowed+Reverb",
    "Nightcore",
    "Bass Boost",
    "Vocal Isolation",
    "Remove Effects"
]

@Client.on_message(filters.command("effects") & filters.group)
@require_admin
@rate_limit
async def effects_cmd(client: Client, message: Message):
    """Show audio effects menu."""
    chat_id = message.chat.id
    active_effect = get_active_effect(chat_id)

    text = f"🎛 **Audio Effects Menu**\n\nChoose an effect to apply to the next track played in this chat.\n\n"
    if active_effect:
        text += f"**Current Effect:** `{active_effect}`"
    else:
        text += "**Current Effect:** `None`"

    buttons = []
    # Create 2 buttons per row
    for i in range(0, len(EFFECTS_OPTIONS), 2):
        row = []
        for j in range(2):
            if i + j < len(EFFECTS_OPTIONS):
                effect = EFFECTS_OPTIONS[i + j]
                # mark active effect
                prefix = "✅ " if effect == active_effect else ""
                row.append(InlineKeyboardButton(f"{prefix}{effect}", callback_data=f"effect:{effect}"))
        buttons.append(row)

    await message.reply(
        text,
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode=ParseMode.MARKDOWN
    )

@Client.on_callback_query(filters.regex(r"^effect:(.+)"))
async def on_effect_callback(client: Client, callback_query: CallbackQuery):
    """Handle effect selection."""
    effect = callback_query.matches[0].group(1)
    chat_id = callback_query.message.chat.id
    user_id = callback_query.from_user.id

    if await get_permission_level(user_id, chat_id) < 3:
        await callback_query.answer("Admins only for audio effects.", show_alert=True)
        return

    set_active_effect(chat_id, effect)

    if effect == "Remove Effects":
        text = "✅ Audio effects removed. Tracks will play normally."
    else:
        text = f"✅ Audio effect set to **{effect}**. It will be applied to the next track played."

    await callback_query.answer(f"Effect set: {effect}", show_alert=True)

    # Update the message to show the new active effect
    active_effect = get_active_effect(chat_id)
    msg_text = f"🎛 **Audio Effects Menu**\n\nChoose an effect to apply to the next track played in this chat.\n\n"
    if active_effect:
        msg_text += f"**Current Effect:** `{active_effect}`\n\n{text}"
    else:
        msg_text += f"**Current Effect:** `None`\n\n{text}"

    buttons = []
    for i in range(0, len(EFFECTS_OPTIONS), 2):
        row = []
        for j in range(2):
            if i + j < len(EFFECTS_OPTIONS):
                btn_effect = EFFECTS_OPTIONS[i + j]
                prefix = "✅ " if btn_effect == active_effect else ""
                row.append(InlineKeyboardButton(f"{prefix}{btn_effect}", callback_data=f"effect:{btn_effect}"))
        buttons.append(row)

    await callback_query.message.edit_text(
        msg_text,
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode=ParseMode.MARKDOWN
    )
