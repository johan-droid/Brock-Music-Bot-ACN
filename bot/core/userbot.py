"""Userbot Client(s) initialization for voice chat streaming."""

import logging
from typing import List
import pyrogram.errors
from pyrogram.client import Client
from config import config

logger = logging.getLogger(__name__)

# Global userbot clients list
userbot_clients: List[Client] = []
_rr_cursor: int = 0


def _build_client_from_session(index: int, session_string: str) -> Client:
    """Create a Pyrogram client from session string."""
    client_name = f"userbot_{index}"
    
    api_id = config.API_ID
    api_hash = config.API_HASH

    if api_id is None or api_hash is None:
        raise RuntimeError(
            "TELEGRAM_ENABLED is true but API_ID/API_HASH is unset. "
            "Please set API_ID and API_HASH in your environment variables."
        )

    client = Client(
        client_name,
        api_id=api_id,
        api_hash=api_hash,
        session_string=session_string,
    )
    return client


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
            client = _build_client_from_session(i, auth["value"])
            
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
        from bot.core.call import call_manager

        if call_manager:
            snapshot = call_manager.get_balancer_snapshot()
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
