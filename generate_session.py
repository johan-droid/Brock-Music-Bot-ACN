import asyncio
import base64
import os
from pathlib import Path

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
            # Windows has a hard limit of 32767 chars on environment values.
            if len(v) > 32767:
                # Prefer file path login mode; skip huge session b64 values.
                if k.startswith("SESSION_FILE_B64"):
                    continue
                if k.startswith("SESSION_STRING"):
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
    
    sessions_dir = Path("./sessions")
    sessions_dir.mkdir(parents=True, exist_ok=True)

    app = Client(
        "userbot_1",
        api_id=api_id,
        api_hash=api_hash,
        workdir=str(sessions_dir),
    )
    
    async with app:
        me = await app.get_me()
        if me.is_bot:
            print("\n❌ ERROR: You logged in as a Bot! This will NOT work for PyTgCalls.")
            print("Please run the script again and use a real phone number.")
            return

        session_file = sessions_dir / "userbot_1.session"
        if not session_file.exists():
            print("\n❌ ERROR: Session file was not created.")
            return

        session_b64 = base64.b64encode(session_file.read_bytes()).decode("ascii")

        print("\n" + "="*60)
        print("✅ SUCCESS! Logged in as:", me.first_name)
        print("\nSESSION FILE CREATED:")
        print("="*60 + "\n")
        print(session_file)
        print("\nENV VALUE FOR CLOUD DEPLOYMENT (Recommended):")
        print("SESSION_FILE_B64_1=" + session_b64)
        print("\n" + "="*60)
        print("Use SESSION_FILE_B64_1 in your deploy variables (or mount SESSION_FILE_PATH_1).")
        print("="*60 + "\n")

if __name__ == "__main__":
    asyncio.run(main())
