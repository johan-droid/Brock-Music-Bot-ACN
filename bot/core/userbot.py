"""Userbot Client(s) initialization for voice chat streaming."""

import base64
import logging
import tempfile
from pathlib import Path
from typing import List
import pyrogram.errors
from pyrogram import Client
from config import config

logger = logging.getLogger(__name__)

# Global userbot clients list
userbot_clients: List[Client] = []
_rr_cursor: int = 0


def _build_client_from_session(index: int, auth: dict) -> Client:
    """Create a Pyrogram client from a session auth entry."""
    client_name = f"userbot_{index}"

    api_id = config.API_ID
    api_hash = config.API_HASH

    if api_id is None or api_hash is None:
        raise RuntimeError(
            "TELEGRAM_ENABLED is true but API_ID/API_HASH is unset. "
            "Please set API_ID and API_HASH in your environment variables."
        )

    auth_type = auth.get("type", "string")
    auth_value = auth.get("value")

    if auth_type == "string":
        if not isinstance(auth_value, str):
            raise RuntimeError("SESSION_STRING_* values must be valid strings.")

        return Client(
            client_name,
            api_id=api_id,
            api_hash=api_hash,
            session_string=auth_value,
        )

    if auth_type == "file":
        if not isinstance(auth_value, str) or not auth_value.strip():
            raise RuntimeError("SESSION_FILE_PATH_* values must be a valid file path string.")

        return Client(
            auth_value,
            api_id=api_id,
            api_hash=api_hash,
        )

    if auth_type == "b64":
        if not isinstance(auth_value, str) or not auth_value.strip():
            raise RuntimeError("SESSION_FILE_B64_* values must be valid base64-encoded data.")

        # Sanitize and validate base64 input
        # Remove whitespace and common formatting characters
        sanitized = "".join(auth_value.strip().split())
        
        # Validate base64 characters only (A-Z, a-z, 0-9, +, /, =)
        import re
        if not re.match(r'^[A-Za-z0-9+/=]+$', sanitized):
            raise RuntimeError("SESSION_FILE_B64_* contains invalid characters. Only base64 characters allowed.")
        
        # Check for reasonable length (prevent DoS with huge inputs)
        if len(sanitized) > 100000:  # ~75KB decoded max
            raise RuntimeError("SESSION_FILE_B64_* value too large.")
        
        # Validate base64 by attempting decode
        try:
            decoded = base64.b64decode(sanitized, validate=True)
        except Exception as e:
            raise RuntimeError(f"SESSION_FILE_B64_* is not valid base64: {e}")
        
        # Validate decoded content looks like a session file (SQLite header)
        if not decoded.startswith(b'SQLite format 3'):
            raise RuntimeError("SESSION_FILE_B64_* does not contain a valid SQLite session file.")

        tmp_dir = Path(tempfile.gettempdir())
        tmp_dir.mkdir(parents=True, exist_ok=True)
        session_file = tmp_dir / f"userbot_{index}.session"
        session_file.write_bytes(decoded)
        return Client(
            str(session_file),
            api_id=api_id,
            api_hash=api_hash,
        )

    raise RuntimeError(
        f"Unsupported userbot auth type: {auth_type}. "
        "Supported auth types are SESSION_STRING_*, SESSION_FILE_PATH_*, and SESSION_FILE_B64_*."
    )


async def init_userbots() -> List[Client]:
    """Initialize all configured userbot clients.
    
    Returns:
        List of started Client instances
    """
    if not config.TELEGRAM_ENABLED:
        logger.info("TELEGRAM_ENABLED is false; skipping userbot initialization")
        return []

    if not config.API_ID or not config.API_HASH:
        raise RuntimeError(
            "TELEGRAM_ENABLED is true, but API_ID/API_HASH is unset. "
            f"Current values: API_ID set={bool(config.API_ID)}, API_HASH set={bool(config.API_HASH)}. "
            "Please set API_ID/API_HASH in environment (API_ID/TELEGRAM_API_ID/TG_API_ID, "
            "API_HASH/TELEGRAM_API_HASH/TG_API_HASH) and restart."
        )

    auth_entries = config.userbot_auth_entries
    if not auth_entries:
        raise RuntimeError(
            "At least one userbot session string is required when TELEGRAM_ENABLED is true. "
            "Set SESSION_STRING_1 in your environment variables. "
            "Generate a session string with: python generate_session.py"
        )

    userbot_clients.clear()
    auth_key_duplicated_count = 0

    for i, auth in enumerate(auth_entries, 1):
        client: Client | None = None
        auth_label = auth.get("label", f"userbot_{i}")
        try:
            client = _build_client_from_session(i, auth)
            
            await client.start()
            user_info = await client.get_me()
            
            if user_info.is_bot:
                await client.stop()
                logger.error(f"Userbot {i} (@{user_info.username or user_info.id}) is a BOT account!")
                raise RuntimeError(
                    f"{auth_label} belongs to a Bot (@{user_info.username}). "
                    "PyTgCalls requires a REAL USER account to join voice chats. "
                    "Please run 'python generate_session.py' and log in with a phone number."
                )

            logger.info(f"Userbot {i} started: @{user_info.username or user_info.id}")
            userbot_clients.append(client)
            
        except Exception as e:
            # Clean up partial startup if possible
            try:
                if client:
                    await client.stop()
            except Exception:
                pass

            is_duplicated = isinstance(e, pyrogram.errors.AuthKeyDuplicated) or "AUTH_KEY_DUPLICATED" in str(e).upper()
            if is_duplicated:
                auth_key_duplicated_count += 1
                logger.error(
                    "Failed to start userbot %d due to AUTH_KEY_DUPLICATED. "
                    "This means the same user session is used in another process/device. "
                    "Stop other instances or generate a new session string for %s.",
                    i,
                    auth_label,
                )

            logger.error(f"Failed to start userbot {i}: {e}")
            continue
    
    if not userbot_clients:
        if auth_key_duplicated_count > 0:
            raise RuntimeError(
                "No userbots could be started due AUTH_KEY_DUPLICATED. "
                "This usually means the same session is active elsewhere. "
                "Stop the other instances or rotate SESSION_* and restart."
            )

        raise RuntimeError(
            "No userbots could be started. "
            "Validate your SESSION_STRING_* values and make sure at least one userbot session is logged in and not duplicated. "
            "Use generate_session.py to create a working userbot session."
        )
    
    return userbot_clients


def get_available_userbot() -> Client:
    """Get an available userbot, preferring the least-loaded assistant."""
    global _rr_cursor

    if not userbot_clients:
        raise RuntimeError("No userbots available")

    # Prefer load-aware selection from call manager when initialized.
    try:
        from bot.core import call
        if call.call_manager:
            snapshot = call.call_manager.get_balancer_snapshot()
            loads = snapshot.get("loads", {})
            candidates = sorted(
                range(len(userbot_clients)),
                key=lambda idx: (int(loads.get(str(idx), 0)), idx),
            )
            if candidates:
                return userbot_clients[candidates[0]]
    except Exception as exc:
        logger.debug(f"Load-aware selector fallback: {exc}")

    # Fallback to round-robin if call manager is not ready.
    idx = _rr_cursor % len(userbot_clients)
    _rr_cursor += 1
    return userbot_clients[idx]


async def stop_userbots():
    """Stop for all initialized userbot clients."""
    if not userbot_clients:
        return

    logger.info(f"Stopping {len(userbot_clients)} userbot(s)...")
    for client in userbot_clients:
        try:
            await client.stop()
        except Exception as exc:
            logger.debug(f"Failed to stop userbot: {exc}")
    
    userbot_clients.clear()
    logger.info("All userbots stopped.")

