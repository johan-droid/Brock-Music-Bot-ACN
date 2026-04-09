import asyncio
import os

from pyrogram import Client
from dotenv import load_dotenv


def _load_env_files() -> None:
    from dotenv import dotenv_values

    for p in ("bot/.env.local", ".env.local", ".env"):
        if not os.path.exists(p):
            continue

        values = dotenv_values(p) or {}
        for k, v in values.items():
            if v is None:
                continue
            if k not in os.environ:
                os.environ[k] = v


def _get_api_credentials() -> tuple[int, str]:
    api_id_raw = os.getenv("API_ID") or os.getenv("TELEGRAM_API_ID") or ""
    api_hash = os.getenv("API_HASH") or os.getenv("TELEGRAM_API_HASH") or ""

    if not api_id_raw:
        api_id_raw = input("Enter API_ID (from my.telegram.org): ").strip()
    if not api_hash:
        api_hash = input("Enter API_HASH (from my.telegram.org): ").strip()

    if not api_id_raw or not api_hash:
        raise RuntimeError("API_ID and API_HASH are required.")

    return int(api_id_raw), api_hash

async def main():
    _load_env_files()
    api_id, api_hash = _get_api_credentials()
    
    print("\n" + "="*60)
    print("      TELEGRAM USERBOT SESSION GENERATOR")
    print("="*60 + "\n")
    print("🚨 IMPORTANT: You MUST log in with a REAL TELEGRAM ACCOUNT (Phone Number).")
    print("❌ DO NOT USE A BOT TOKEN. Bots CANNOT join Voice Chats!")
    print("\nWhen prompted:")
    print("1. Enter your phone number with country code (e.g., +1234567890)")
    print("2. Enter the login code Telegram sends you")
    print("3. Enter your 2FA password (if you have one enabled)\n")
    
    app = Client(
        "userbot_1",
        api_id=api_id,
        api_hash=api_hash,
        in_memory=True,  # Don't create a session file, generate string instead
    )
    
    async with app:
        me = await app.get_me()
        if me.is_bot:
            print("\n❌ ERROR: You logged in as a Bot! This will NOT work for PyTgCalls.")
            print("Please run the script again and use a real phone number.")
            return

        # Export the session string directly
        session_string = await app.export_session_string()

        print("\n" + "="*60)
        print("✅ SUCCESS! Logged in as:", me.first_name)
        print("(@" + (me.username or "no username") + ")")
        print("\nSESSION STRING (Copy this value):")
        print("="*60 + "\n")
        print("SESSION_STRING_1=" + session_string)
        print("\n" + "="*60)
        print("Add this SESSION_STRING_1 value to your Railway variables!")
        print("="*60 + "\n")

if __name__ == "__main__":
    asyncio.run(main())
