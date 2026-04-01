"""Userbot Client(s) initialization for voice chat streaming."""

import base64
import binascii
import logging
from pathlib import Path
from typing import Any, Dict, List, Tuple
import pyrogram.errors
from pyrogram.client import Client
from config import config

logger = logging.getLogger(__name__)

# Global userbot clients list
userbot_clients: List[Client] = []
_rr_cursor: int = 0


def _decode_session_file_b64(encoded: str, target_file: Path) -> None:
    """Decode SESSION_FILE_B64_* into a .session file on disk."""
    raw = "".join(encoded.strip().split())
    missing_padding = len(raw) % 4
    if missing_padding:
        raw += "=" * (4 - missing_padding)

    try:
        payload = base64.b64decode(raw, validate=False)
    except binascii.Error as exc:
        raise RuntimeError("Invalid base64 value for SESSION_FILE_B64_*.") from exc

    target_file.parent.mkdir(parents=True, exist_ok=True)
    target_file.write_bytes(payload)


def _build_client_from_auth(index: int, auth: Dict[str, str]) -> Tuple[Client, Path, str, str]:
    """Create a Pyrogram client from auth entry (string, file path, or base64 file)."""
    mode = auth["mode"]
    label = auth["label"]
    client_name = f"userbot_{index}"
    session_file = Path("./sessions") / f"{client_name}.session"
    workdir = session_file.parent
    kwargs: Dict[str, Any] = {}

    if mode == "string":
        kwargs["session_string"] = auth["value"]
    elif mode == "file_b64":
        _decode_session_file_b64(auth["value"], session_file)
    elif mode == "file_path":
        file_path = Path(auth["value"]).expanduser()
        if file_path.is_dir():
            file_path = file_path / f"userbot_{index}.session"
        if not file_path.exists():
            raise RuntimeError(f"{label} points to missing file: {file_path}")
        session_file = file_path
        workdir = file_path.parent
        client_name = file_path.stem
    else:
        raise RuntimeError(f"Unsupported userbot auth mode: {mode}")

    api_id = config.API_ID
    api_hash = config.API_HASH

    if api_id is None or api_hash is None:
        raise RuntimeError(
            "TELEGRAM_ENABLED is true but API_ID/API_HASH is unset (unexpected in _build_client_from_auth)."
        )

    client = Client(
        client_name,
        api_id=api_id,
        api_hash=api_hash,
        workdir=str(workdir),
        **kwargs,
    )
    return client, session_file, label, mode


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
            "At least one userbot auth is required when TELEGRAM_ENABLED is true. "
            "Set one of: SESSION_FILE_PATH_1, SESSION_FILE_B64_1, or SESSION_STRING_1."
        )

    userbot_clients.clear()
    auth_key_duplicated_count = 0

    for i, auth in enumerate(auth_entries, 1):
        client: Client | None = None
        session_file = Path("./sessions") / f"userbot_{i}.session"
        auth_label = auth.get("label", f"userbot_{i}")
        auth_mode = auth.get("mode", "string")
        try:
            client, session_file, auth_label, auth_mode = _build_client_from_auth(i, auth)
            
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
                    "Stop other instances or rotate %s. "
                    "For local cleanup, delete %s if present and restart.",
                    i,
                    auth_label,
                    session_file,
                )
                can_remove_local = auth_mode in {"string", "file_b64"}
                if can_remove_local and session_file.exists():
                    try:
                        session_file.unlink()
                        logger.info("Removed stale session file %s", session_file)
                    except Exception as exc:
                        logger.warning("Could not remove stale session file %s: %s", session_file, exc)

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
            "Validate your SESSION_FILE_PATH_*/SESSION_FILE_B64_*/SESSION_STRING_* values and make sure at least one userbot session is logged in and not duplicated. "
            "Use generate_session.py to re-create a working userbot session."
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
