"""One-shot userbot session generator.

Requests a code, waits for the code to appear in a file, signs in immediately,
prints the session string. Runs detached so nothing kills it mid-flow.

Usage:
    python generate_session.py phone <phone> <codefile>
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

from pyrogram import Client
from pyrogram.errors import (
    SessionPasswordNeeded,
    PhoneCodeExpired,
    PhoneCodeInvalid,
    FloodWait,
    PhoneNumberBanned,
    PhoneNumberFlood,
    PhoneNumberInvalid,
)

API_ID = 23144478
API_HASH = "4fb521f26810caebce2f77e8d3a4fd23"

WORKDIR = Path(__file__).resolve().parent / "sessions"
SESSION_FILE = WORKDIR / "vc_guest.session"
STATE_FILE = WORKDIR / "vc_guest_state.json"


def _client() -> Client:
    WORKDIR.mkdir(parents=True, exist_ok=True)
    return Client(
        "vc_guest",
        api_id=API_ID,
        api_hash=API_HASH,
        workdir=str(WORKDIR),
        in_memory=False,
    )


def _save_state(phone: str, phone_code_hash: str):
    STATE_FILE.write_text(json.dumps({"phone": phone, "phone_code_hash": phone_code_hash}))


def _load_state() -> dict:
    return json.loads(STATE_FILE.read_text())


async def finish_sign_in(phone: str, phone_code_hash: str, code: str) -> None:
    client = _client()
    await client.connect()
    try:
        try:
            await client.sign_in(phone, phone_code_hash, code)
        except SessionPasswordNeeded:
            print("2FA_PASSWORD_REQUIRED")
            sys.exit(2)
        me = await client.get_me()
        if me.is_bot:
            print("ERROR: This is a BOT account. Userbots must be real user accounts.")
            sys.exit(1)
        session_string = await client.export_session_string()
        print("=" * 60)
        print("SUCCESS! Logged in as:", me.first_name, "@" + me.username if me.username else "")
        print("SESSION_STRING_BELOW")
        print(session_string)
        print("=" * 60)
        sys.exit(0)
    finally:
        await client.disconnect()


async def main(phone: str, code_file: str) -> None:
    code_path = Path(code_file)
    if code_path.exists():
        os.remove(code_path)

    client = _client()
    await client.connect()
    try:
        sent = await client.send_code(phone)
        _save_state(phone, sent.phone_code_hash)
    except FloodWait as fw:
        print(f"FLOOD_WAIT {fw.value}")
        sys.exit(3)
    except (PhoneNumberFlood, PhoneNumberBanned):
        print("PHONE_NUMBER_FLOOD_OR_BANNED")
        sys.exit(3)
    except PhoneNumberInvalid:
        print("PHONE_NUMBER_INVALID")
        sys.exit(3)
    finally:
        await client.disconnect()
    print(f"CODE_SENT {phone}")

    state = _load_state()
    deadline = time.time() + 180
    while time.time() < deadline:
        if code_path.exists():
            code = code_path.read_text().strip()
            if code:
                os.remove(code_path)
                try:
                    await finish_sign_in(phone, state["phone_code_hash"], code)
                except (PhoneCodeExpired, PhoneCodeInvalid):
                    print("CODE_INVALID_OR_EXPIRED")
                    sys.exit(1)
        await asyncio.sleep(1)
    print("TIMEOUT")
    sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], sys.argv[2]))
