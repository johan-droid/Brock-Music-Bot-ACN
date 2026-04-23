"""Common FastAPI dependencies for mini app routes."""

from __future__ import annotations

from typing import Optional

from fastapi import Header, HTTPException, Query, Request, status

from .auth import InitDataError, validate_init_data
from .schemas import AuthContext
from .settings import settings


def _extract_init_data(
    x_telegram_init_data: Optional[str],
    authorization: Optional[str],
    init_data_query: Optional[str],
) -> Optional[str]:
    if x_telegram_init_data:
        return x_telegram_init_data
    if init_data_query:
        return init_data_query

    token = (authorization or "").strip()
    if token.lower().startswith("tma "):
        return token[4:].strip()
    return None


async def require_auth_context(
    request: Request,
    x_telegram_init_data: Optional[str] = Header(default=None, alias="X-Telegram-Init-Data"),
    authorization: Optional[str] = Header(default=None),
    init_data_query: Optional[str] = Query(default=None, alias="init_data"),
) -> AuthContext:
    raw_init_data = _extract_init_data(x_telegram_init_data, authorization, init_data_query)
    if not raw_init_data:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing Telegram initData")

    try:
        context = validate_init_data(
            init_data=raw_init_data,
            bot_token=settings.BOT_TOKEN or "",
            max_age_seconds=settings.MINI_APP_INITDATA_MAX_AGE_SECONDS,
        )
    except InitDataError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    request.state.auth_context = context
    return context

