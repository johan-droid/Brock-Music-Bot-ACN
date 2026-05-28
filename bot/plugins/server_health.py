"""Server-health command for the external track service."""

from typing import Any, cast

from pyrogram import Client, filters

Client = cast(Any, Client)
from pyrogram.types import Message

from bot.core.music_backend import music_backend
from bot.utils.permissions import rate_limit


@Client.on_message(filters.command("serverhealth") & (filters.private | filters.group))
@rate_limit
async def serverhealth_cmd(client: Client, message: Message):
    health = await music_backend.health()
    if not health.get("configured"):
        await message.reply_text(
            "💀 The Tone Dial to the music server is not configured.\n"
            "Set `MUSIC_MICROSERVICE_URL` or `MUSIC_MICROSERVICE_URLS`, then call Brook back to the stage."
        )
        return

    endpoints = health.get("endpoints", [])
    healthy = sum(1 for endpoint in endpoints if endpoint.get("ok"))
    lines = [
        "🎻 Soul King relay status",
        f"Clear connections: `{healthy}` / `{len(endpoints)}`",
    ]
    for endpoint in endpoints[:5]:
        status = "singing" if endpoint.get("ok") else "silent"
        url = endpoint.get("url", "unknown")
        code = endpoint.get("status", "-")
        lines.append(f"- `{status}` `{code}` {url}")

    await message.reply_text("\n".join(lines))
