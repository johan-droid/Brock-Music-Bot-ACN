
import logging
import random
from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.enums import ParseMode

logger = logging.getLogger(__name__)

BROOK_QUOTES = [
    "Yohohoho! Did someone call the Soul King?",
    "I can hear you with my ears... although I don't have ears! Skull joke! Yohohoho!",
    "Are you ready for a concert? Use /play to start the music!",
    "I may be just bones, but my heart is full of music... wait, I don't have a heart! Yohohoho!",
    "Need some music to stir your soul? I'm at your service!",
    "I'm so happy to be here I could cry... if I had tear ducts! Yohohoho!",
]

@Client.on_message(filters.mentioned & filters.group)
async def mention_handler(client: Client, message: Message):
    """Respond when the bot is mentioned in a group."""
    quote = random.choice(BROOK_QUOTES)
    await message.reply_text(f"<b>{quote}</b>", parse_mode=ParseMode.HTML)

@Client.on_message(filters.regex(r"(?i)(brook|soul king)") & filters.group)
async def name_handler(client: Client, message: Message):
    """Respond when 'brook' or 'soul king' is mentioned in a group."""
    # Only respond if it's not a command to avoid double responding
    if message.text and message.text.startswith("/"):
        return
        
    quote = random.choice(BROOK_QUOTES)
    await message.reply_text(f"<i>{quote}</i>", parse_mode=ParseMode.HTML)
