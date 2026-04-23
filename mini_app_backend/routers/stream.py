"""Audio resolve/proxy endpoints for mini app playback."""

from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any, Dict
from urllib.parse import quote

import aiohttp
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from mini_app_backend.dependencies import require_auth_context
from mini_app_backend.schemas import AuthContext, TrackPayload
from mini_app_backend.services.music_service import music_service
from mini_app_backend.settings import settings


router = APIRouter(prefix="/stream", tags=["stream"])

_FORWARDED_HEADERS = (
    "content-type",
    "content-length",
    "content-range",
    "accept-ranges",
    "cache-control",
    "etag",
    "last-modified",
)


def _sign_proxy_url(url: str, exp: int) -> str:
    payload = f"{url}|{exp}"
    return hmac.new(
        settings.stream_proxy_secret.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _assert_valid_proxy_signature(url: str, exp: int, sig: str) -> None:
    now = int(time.time())
    if exp < now:
        raise HTTPException(status_code=401, detail="Proxy URL expired")
    expected = _sign_proxy_url(url, exp)
    if not hmac.compare_digest(expected, sig):
        raise HTTPException(status_code=401, detail="Invalid proxy signature")


@router.post("/resolve")
async def resolve_stream(
    track: TrackPayload,
    auth: AuthContext = Depends(require_auth_context),
) -> Dict[str, Any]:
    _ = auth
    payload = await music_service.resolve(track.model_dump())
    if not payload:
        raise HTTPException(status_code=404, detail="Unable to resolve playable stream")

    url = payload.get("url") or payload.get("stream_url")
    if not url:
        raise HTTPException(status_code=404, detail="Resolved payload is missing stream URL")

    exp = int(time.time()) + 120
    sig = _sign_proxy_url(url, exp)
    proxy_url = f"/api/v1/stream/proxy?url={quote(url, safe='')}&exp={exp}&sig={sig}"
    payload["proxy_url"] = proxy_url
    payload["proxy_expires_at"] = exp
    return payload


@router.get("/proxy")
async def stream_proxy(
    request: Request,
    url: str = Query(..., min_length=1),
    exp: int = Query(...),
    sig: str = Query(..., min_length=16),
):
    _assert_valid_proxy_signature(url=url, exp=exp, sig=sig)

    headers: Dict[str, str] = {}
    range_header = request.headers.get("range")
    if range_header:
        headers["Range"] = range_header

    timeout = aiohttp.ClientTimeout(total=settings.MINI_APP_STREAM_PROXY_TIMEOUT_SECONDS)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url, headers=headers, allow_redirects=True) as upstream:
            if upstream.status >= 400:
                detail = f"Upstream stream request failed with status {upstream.status}"
                return JSONResponse(status_code=upstream.status, content={"detail": detail})

            response_headers: Dict[str, str] = {}
            for key, value in upstream.headers.items():
                if key.lower() in _FORWARDED_HEADERS:
                    response_headers[key] = value
            response_headers.setdefault("Accept-Ranges", "bytes")

            media_type = upstream.headers.get("Content-Type", "application/octet-stream")
            return StreamingResponse(
                upstream.content.iter_chunked(settings.MINI_APP_STREAM_PROXY_CHUNK_SIZE),
                status_code=upstream.status,
                headers=response_headers,
                media_type=media_type,
            )
