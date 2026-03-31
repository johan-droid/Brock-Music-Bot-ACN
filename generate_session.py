import asyncio
from pyrogram import Client

async def main():
    api_id = "31686467"
    api_hash = "985164f322dd4319bb56951ca0a2ba25"
    
    print("\n" + "="*60)
    print("      TELEGRAM USERBOT SESSION STRING GENERATOR")
    print("="*60 + "\n")
    print("🚨 IMPORTANT: You MUST log in with a REAL TELEGRAM ACCOUNT (Phone Number).")
    print("❌ DO NOT USE A BOT TOKEN. Bots CANNOT join Voice Chats!")
    print("\nWhen prompted:")
    print("1. Enter your phone number with country code (e.g., +1234567890)")
    print("2. Enter the login code Telegram sends you")
    print("3. Enter your 2FA password (if you have one enabled)\n")
    
    # We use a temporary file-based session to ensure login completes successfully,
    # then we export the string and delete the file (in-memory can sometimes be buggy).
    app = Client(
        "temp_userbot",
        api_id=api_id,
        api_hash=api_hash,
        in_memory=True
    )
    
    async with app:
        me = await app.get_me()
        if me.is_bot:
            print("\n❌ ERROR: You logged in as a Bot! This will NOT work for PyTgCalls.")
            print("Please run the script again and use a real phone number.")
            return

        session_string = await app.export_session_string()
        print("\n" + "="*60)
        print("✅ SUCCESS! Logged in as:", me.first_name)
        print("\nYOUR SESSION STRING (Copy everything inside the quotes):")
        print("="*60 + "\n")
        print(session_string)
        print("\n" + "="*60)
        print("Copy the string above and paste it into SESSION_STRING_1 in bot/.env.local")
        print("="*60 + "\n")

if __name__ == "__main__":
    asyncio.run(main())
