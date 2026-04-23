"""Telegram Mini App initData validation helpers."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Dict
from urllib.parse import parse_qsl

from .schemas import AuthContext, TelegramUser


class InitDataError(ValueError):
    """Raised when Telegram initData validation fails."""


def _parse_init_data(init_data: str) -> Dict[str, str]:
    if not init_data:
        raise InitDataError("initData is missing")
    try:
        parsed = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=True))
    except ValueError as exc:
        raise InitDataError("initData has invalid format") from exc
    if "hash" not in parsed:
        raise InitDataError("initData hash is missing")
    return parsed


def _build_data_check_string(parsed: Dict[str, str]) -> str:
    pairs = [f"{k}={v}" for k, v in sorted(parsed.items(), key=lambda item: item[0]) if k != "hash"]
    return "\n".join(pairs)


def _compute_telegram_hash(bot_token: str, data_check_string: str) -> str:
    secret = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    return hmac.new(secret, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()


def validate_init_data(init_data: str, bot_token: str, max_age_seconds: int) -> AuthContext:
    """Validate Telegram initData and return authenticated user context."""

    if not bot_token:
        raise InitDataError("BOT_TOKEN is required for initData validation")

    parsed = _parse_init_data(init_data)
    expected_hash = _compute_telegram_hash(bot_token, _build_data_check_string(parsed))
    received_hash = parsed.get("hash", "")

    if not hmac.compare_digest(expected_hash, received_hash):
        raise InitDataError("initData signature mismatch")

    auth_date_raw = parsed.get("auth_date")
    if not auth_date_raw:
        raise InitDataError("auth_date is missing")

    try:
        auth_date = int(auth_date_raw)
    except Exception as exc:
        raise InitDataError("auth_date must be an integer") from exc

    now = int(time.time())
    if auth_date > now + 60:
        raise InitDataError("auth_date is invalid (in the future)")
    if (now - auth_date) > max_age_seconds:
        raise InitDataError("initData is expired")

    user_payload = parsed.get("user")
    if not user_payload:
        raise InitDataError("user payload is missing")

    try:
        user_data = json.loads(user_payload)
    except json.JSONDecodeError as exc:
        raise InitDataError("user payload is invalid JSON") from exc

    if not isinstance(user_data, dict) or not user_data.get("id"):
        raise InitDataError("user payload is invalid")

    user = TelegramUser.model_validate(user_data)
    return AuthContext(
        user=user,
        query_id=parsed.get("query_id"),
        auth_date=auth_date,
        chat_type=parsed.get("chat_type"),
        chat_instance=parsed.get("chat_instance"),
        raw_init_data=init_data,
    )
