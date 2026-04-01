"""Userbot Client(s) initialization for voice chat streaming."""

import logging
from pathlib import Path
from typing import List
import pyrogram.errors
from pyrogram import Client
from config import config

logger = logging.getLogger(__name__)

# Global userbot clients list
userbot_clients: List[Client] = []
_rr_cursor: int = 0


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

    sessions = config.session_strings
    if not sessions:
        raise RuntimeError("At least one SESSION_STRING is required when TELEGRAM_ENABLED is true")

    for i, session in enumerate(sessions, 1):
        try:
            client = Client(
                f"userbot_{i}",
                api_id=config.API_ID,
                api_hash=config.API_HASH,
                session_string=session,
                workdir="./sessions",
            )
            
            await client.start()
            user_info = await client.get_me()
            
            if user_info.is_bot:
                await client.stop()
                logger.error(f"Userbot {i} (@{user_info.username or user_info.id}) is a BOT account!")
                raise RuntimeError(
                    f"SESSION_STRING_{i} belongs to a Bot (@{user_info.username}). "
                    "PyTgCalls requires a REAL USER account to join voice chats. "
                    "Please run 'python generate_session.py' and log in with a phone number."
                )

            logger.info(f"Userbot {i} started: @{user_info.username or user_info.id}")
            userbot_clients.append(client)
            
        except Exception as e:
            # Clean up partial startup if possible
            try:
                await client.stop()
            except Exception:
                pass

            session_file = Path("./sessions") / f"userbot_{i}.session"
            if isinstance(e, pyrogram.errors.AuthKeyDuplicated) or "AUTH_KEY_DUPLICATED" in str(e).upper():
                logger.error(
                    "Failed to start userbot %d due to AUTH_KEY_DUPLICATED. "
                    "This means the same user session is used in another process/device. "
                    "Stop other instances or re-generate SESSION_STRING_%d via generate_session.py. "
                    "For local cleanup, delete %s if present and restart.",
                    i,
                    i,
                    session_file,
                )
                if session_file.exists():
                    try:
                        session_file.unlink()
                        logger.info("Removed stale session file %s", session_file)
                    except Exception as exc:
                        logger.warning("Could not remove stale session file %s: %s", session_file, exc)

            logger.error(f"Failed to start userbot {i}: {e}")
            if i == 1:
                # First userbot is required
                raise RuntimeError(
                    "Required userbot 1 failed to start: "
                    "ensure SESSION_STRING_1 is a valid logged-in user session and not used elsewhere. "
                    "Use generate_session.py to re-create it, then restart.",
                    ) from e
    
    if not userbot_clients:
        raise RuntimeError("No userbots could be started")
    
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
