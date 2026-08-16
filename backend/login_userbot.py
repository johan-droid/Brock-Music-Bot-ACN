#!/usr/bin/env python3
"""Trust-safe, local userbot session builder.

Only this machine talks to Telegram's API - no third-party service or
session-string bot is involved. You only read the login code from your
own Telegram app and put it in CODE_FILE.

Usage:
    python login_userbot.py +<phone>

Optional env:
    PROXY_URL      socks5://[user:pass@]host:port  or  http://[user:pass@]host:port
    CODE_FILE      path where the login code is expected (default: /tmp/login_code.txt)
    PASS_FILE      path where the 2FA password is expected (default: /tmp/login_pass.txt)
    WAIT_SECONDS   how long to wait for the code (default: 300)

Flow (atomic - code never expires between send and sign-in):
    connect -> send code (with backoff retries) -> wait for CODE_FILE
    -> sign in -> handle 2FA -> export session string -> write .env.local
"""

import argparse
import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

from pyrogram import Client
from pyrogram.errors import (
    SessionPasswordNeeded,
    PhoneCodeExpired,
    PhoneCodeInvalid,
    FloodWait,
    PhoneNumberInvalid,
    PhoneNumberBanned,
    PhoneNumberFlood,
)

API_ID = 23144478
API_HASH = "4fb521f26810caebce2f77e8d3a4fd23"

BASE_DIR = Path(__file__).resolve().parent
WORKDIR = BASE_DIR / "sessions"
SESSION_NAME = "userbot_login"
SESSION_FILE = WORKDIR / f"{SESSION_NAME}.session"
ENV_FILE = BASE_DIR / ".env.local"
CODE_FILE = Path(os.environ.get("CODE_FILE", "/tmp/login_code.txt"))
PASS_FILE = Path(os.environ.get("PASS_FILE", "/tmp/login_pass.txt"))
WAIT_SECONDS = int(os.environ.get("WAIT_SECONDS", "300"))
PROXY_URL = os.environ.get("PROXY_URL", "").strip()


def _proxy_dict() -> dict:
    """Parse PROXY_URL into Pyrogram's proxy parameter format."""
    if not PROXY_URL:
        return {}
    parsed = urlparse(PROXY_URL)
    scheme = (parsed.scheme or "").lower()
    if scheme not in ("socks5", "socks4", "http"):
        raise SystemExit(f"Unsupported proxy scheme {scheme!r}. Use socks5://, socks4:// or http://")
    if not parsed.hostname or not parsed.port:
        raise SystemExit(f"Proxy URL must include host and port: {PROXY_URL}")
    proxy = {
        "scheme": scheme,
        "hostname": parsed.hostname,
        "port": parsed.port,
    }
    if parsed.username:
        proxy["username"] = parsed.username
    if parsed.password:
        proxy["password"] = parsed.password
    return proxy


def _client() -> Client:
    WORKDIR.mkdir(parents=True, exist_ok=True)
    return Client(
        SESSION_NAME,
        api_id=API_ID,
        api_hash=API_HASH,
        workdir=str(WORKDIR),
        in_memory=False,
        proxy=_proxy_dict() or None,
    )


async def _send_code_with_retry(client: Client, phone: str) -> str:
    """Send the login code, retrying on transient throttle errors with backoff."""
    for attempt in range(1, 8):
        try:
            sent = await client.send_code(phone)
            return sent.phone_code_hash
        except FloodWait as fw:
            wait = fw.value + 2
            print(f"FloodWait: waiting {wait}s before retrying...")
            await asyncio.sleep(wait)
        except (PhoneNumberInvalid, PhoneNumberFlood, PhoneNumberBanned) as exc:
            if attempt >= 3:
                raise
            print(f"send_code throttled ({type(exc).__name__}); retrying in {5 * attempt}s...")
            await asyncio.sleep(5 * attempt)
    raise PhoneNumberInvalid("Could not send code after retries")


def _wait_for_code() -> str:
    deadline = time.time() + WAIT_SECONDS
    while time.time() < deadline:
        if CODE_FILE.exists():
            code = CODE_FILE.read_text().strip()
            if code:
                return code
        if PASS_FILE.exists() and PASS_FILE.read_text().strip():
            return None  # 2FA password will be used
        time.sleep(1)
    raise SystemExit("TIMEOUT: no login code received")


def _wait_for_password() -> str:
    deadline = time.time() + 120
    print("2FA enabled. Enter your account password into:", PASS_FILE)
    while time.time() < deadline:
        if PASS_FILE.exists():
            pw = PASS_FILE.read_text().strip()
            if pw:
                return pw
        time.sleep(1)
    raise SystemExit("TIMEOUT: no 2FA password received")


def _update_env_file(session_string: str) -> None:
    """Replace SESSION_STRING_1 and blank the other string slots in .env.local."""
    if not ENV_FILE.exists():
        raise SystemExit(f"Environment file not found: {ENV_FILE}")

    lines = ENV_FILE.read_text(encoding="utf-8").splitlines(keepends=True)
    found = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("#") or "=" not in stripped:
            continue
        key = stripped.split("=", 1)[0].strip()
        if key == "SESSION_STRING_1":
            lines[i] = f"SESSION_STRING_1={session_string}\n"
            found = True
        elif key in ("SESSION_STRING_2", "SESSION_STRING_3", "SESSION_STRING_4", "SESSION_STRING_5"):
            lines[i] = f"{key}=\n"

    if not found:
        lines.append(f"SESSION_STRING_1={session_string}\n")

    ENV_FILE.write_text("".join(lines), encoding="utf-8")
    print(f"Updated {ENV_FILE} (SESSION_STRING_1 set, slots 2-5 cleared)")


async def main() -> None:
    phone = sys.argv[1] if len(sys.argv) > 1 else None
    if not phone:
        raise SystemExit("Usage: python login_userbot.py +<phone>")
    if PROXY_URL:
        print(f"Using proxy: {PROXY_URL}")
    else:
        print("No proxy configured (set PROXY_URL to route through SOCKS5/HTTP if needed)")

    for f in (CODE_FILE, PASS_FILE):
        if f.exists():
            f.unlink()

    client = _client()
    await client.connect()
    try:
        phone_code_hash = await _send_code_with_retry(client, phone)
        print(f"CODE_SENT to {phone}")
        print("Enter the login code you receive into:", CODE_FILE)

        code = _wait_for_code()
        if code is None:
            password = _wait_for_password()
            code = None
        else:
            password = None

        try:
            if code is not None:
                await client.sign_in(phone, phone_code_hash, code)
            else:
                await client.sign_in(phone, phone_code_hash, "")
        except SessionPasswordNeeded:
            if password is None:
                password = _wait_for_password()
            try:
                await client.check_password(password)
            except Exception as exc:
                raise SystemExit(f"2FA password rejected: {exc}")

        me = await client.get_me()
        if me.is_bot:
            raise SystemExit("ERROR: this is a bot account; userbots must be real user accounts.")

        session_string = await client.export_session_string()
        print("=" * 60)
        print("SUCCESS! Logged in as:", me.first_name, "@" + me.username if me.username else "")
        print("=" * 60)
        _update_env_file(session_string)
        print("Session string configured. You can now run: python -m app")
    finally:
        try:
            await client.disconnect()
        finally:
            for f in (SESSION_FILE, Path(f"{SESSION_FILE}-journal")):
                try:
                    f.unlink(missing_ok=True)
                except OSError:
                    pass


if __name__ == "__main__":
    asyncio.run(main())
