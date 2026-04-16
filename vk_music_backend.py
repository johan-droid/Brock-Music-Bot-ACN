"""VK-first music backend with FastAPI and shared aggregation logic."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

import aiohttp
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from bot.utils.cache import cache, init_redis

logger = logging.getLogger(__name__)


class BackendSettings(BaseSettings):
    """Environment-driven configuration for the VK music backend."""

    model_config = SettingsConfigDict(
        env_file=(".env.local", ".env", "bot/.env.local", "bot/.env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    SOURCE_ORDER: str = "vk,deezer"
    HTTP_TIMEOUT: int = 15
    SEARCH_CACHE_TTL: int = 900
    RESOLVE_CACHE_TTL: int = 19800
    RATE_LIMIT_PER_MINUTE: int = 120
    RATE_LIMIT_BURST: int = 20
    MAX_RESULTS: int = 20
    # CORS configuration: comma/space/semicolon-separated allowed origins
    CORS_ALLOWED_ORIGINS: Optional[str] = None
    # Optionally allow a regex to match origins (takes precedence over explicit list)
    CORS_ALLOW_ORIGIN_REGEX: Optional[str] = None
    # Whether to allow credentials; will be forced False if allowed origins contains '*'
    CORS_ALLOW_CREDENTIALS: bool = False

    VK_API_BASE_URL: Optional[str] = None
    VK_API_TOKEN: Optional[str] = None
    VK_SEARCH_PATH: str = "/search"
    VK_RESOLVE_PATH: str = "/resolve"
    VK_TOKEN_HEADER: str = "Authorization"

    DEEZER_API_BASE_URL: str = "https://api.deezer.com"
    DEEZER_TOKENS: Optional[str] = None
    DEEZER_RESOLVE_URL: Optional[str] = None


settings = BackendSettings()


_VK_PAGE_URL_RX = re.compile(
    r"(?:https?://)?(?:m\.)?(?:vk\.com|vk\.ru)(?:/[?#].*|/.*)?",
    re.IGNORECASE,
)
_DEEZER_PAGE_URL_RX = re.compile(
    r"(?:https?://)?(?:www\.)?(?:deezer\.com|deezer\.page\.link)(?:/[?#].*|/.*)?",
    re.IGNORECASE,
)
_UNSUPPORTED_PAGE_DOMAINS = (
    "youtube.com",
    "youtube-nocookie.com",
    "youtu.be",
    "spotify.com",
    "soundcloud.com",
    "jiosaavn.com",
    "audiomack.com",
)


def is_vk_page_url(url: str) -> bool:
    value = (url or "").strip()
    if not value:
        return False
    return bool(_VK_PAGE_URL_RX.fullmatch(value))


def is_deezer_page_url(url: str) -> bool:
    value = (url or "").strip()
    if not value:
        return False
    return bool(_DEEZER_PAGE_URL_RX.fullmatch(value))


def is_unsupported_page_url(url: str) -> bool:
    value = (url or "").strip().lower()
    if not value:
        return False
    return any(domain in value for domain in _UNSUPPORTED_PAGE_DOMAINS)


def _infer_source_from_url(url: str, fallback: str = "direct") -> str:
    value = (url or "").strip().lower()
    if not value:
        return fallback
    if is_vk_page_url(value) or "vk.com" in value or "vk.ru" in value or "vkvideo.ru" in value:
        return "vk"
    if is_deezer_page_url(value) or "deezer" in value:
        return "deezer"
    if is_unsupported_page_url(value):
        return "unsupported"
    return fallback


def _normalize_url_text(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return text
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", text):
        return text
    if text.startswith(("www.", "vk.com", "m.vk.com", "vkvideo.ru", "deezer.com", "deezer.page.link")):
        return f"https://{text}"
    return text


@dataclass
class TrackPayload:
    """Normalized track payload used by both backend and bot."""

    title: str
    artist: str
    duration: int
    stream_url: str
    source: str = "vk"
    track_id: Optional[str] = None
    thumbnail: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        extra = data.pop("extra", {}) or {}
        data.update(extra)
        data["url"] = self.stream_url
        data["stream_url"] = self.stream_url
        data["uploader"] = self.artist
        data["id"] = self.track_id
        return data

    @classmethod
    def from_any(cls, value: Any) -> "TrackPayload":
        if isinstance(value, TrackPayload):
            return value

        if isinstance(value, dict):
            extra = dict(value)
            title = str(value.get("title") or value.get("name") or "Unknown")
            artist = str(value.get("artist") or value.get("uploader") or value.get("author") or "Unknown")
            duration = int(value.get("duration") or value.get("length") or 0)
            stream_url = _normalize_url_text(str(value.get("stream_url") or value.get("url") or value.get("play_url") or ""))
            source = str(value.get("source") or value.get("origin_source") or "").strip().lower()
            if source in ("", "unknown", "auto", "direct"):
                source = _infer_source_from_url(stream_url)
            track_id = value.get("track_id") or value.get("id") or value.get("vk_id") or value.get("deezer_id")
            thumbnail = value.get("thumbnail") or value.get("thumb") or value.get("cover")
            return cls(
                title=title,
                artist=artist,
                duration=duration,
                stream_url=stream_url,
                source=source,
                track_id=str(track_id) if track_id is not None else None,
                thumbnail=str(thumbnail) if thumbnail else None,
                extra=extra,
            )

        text = str(value or "").strip()
        return cls(
            title=text or "Unknown",
            artist="Unknown",
            duration=0,
            stream_url=_normalize_url_text(text),
            source=_infer_source_from_url(text),
            track_id=None,
        )


class DeezerTokenPool:
    """Rotates Deezer tokens using a simple health score and cooldown window."""

    def __init__(self, raw_tokens: Optional[str]):
        tokens = []
        for token in re.split(r"[\s,]+", raw_tokens or ""):
            token = token.strip()
            if token:
                tokens.append(token)

        self.tokens = tokens
        self.health: Dict[str, Dict[str, Any]] = {
            token: {"score": 1.0, "success": 0, "fail": 0, "cooldown_until": 0.0}
            for token in tokens
        }

    def _snapshot(self) -> List[Dict[str, Any]]:
        snapshot = []
        now = time.time()
        for token in self.tokens:
            state = self.health[token]
            snapshot.append(
                {
                    "token_suffix": token[-4:] if len(token) > 4 else token,
                    "score": round(float(state["score"]), 3),
                    "success": int(state["success"]),
                    "fail": int(state["fail"]),
                    "cooling_down": state["cooldown_until"] > now,
                }
            )
        return snapshot

    def pick(self) -> Optional[str]:
        now = time.time()
        available = [token for token in self.tokens if self.health[token]["cooldown_until"] <= now]
        if not available:
            available = list(self.tokens)
        if not available:
            return None
        available.sort(key=lambda token: self.health[token]["score"], reverse=True)
        return available[0]

    def record_success(self, token: Optional[str]) -> None:
        if not token or token not in self.health:
            return
        state = self.health[token]
        state["success"] += 1
        state["score"] = min(2.0, float(state["score"]) + 0.1)
        state["cooldown_until"] = 0.0

    def record_failure(self, token: Optional[str], status_code: Optional[int] = None) -> None:
        if not token or token not in self.health:
            return
        state = self.health[token]
        state["fail"] += 1
        state["score"] = max(0.05, float(state["score"]) - 0.25)
        backoff = 20.0
        if status_code in (401, 403):
            backoff = 60.0
        elif status_code == 429:
            backoff = 120.0
        state["cooldown_until"] = time.time() + backoff


class ProviderBase:
    source_name = "unknown"

    def __init__(self, settings: BackendSettings):
        self.settings = settings

    async def search(self, query: str, limit: int = 10) -> List[TrackPayload]:
        raise NotImplementedError

    async def resolve(self, target: Any) -> Optional[TrackPayload]:
        raise NotImplementedError

    async def health(self) -> Dict[str, Any]:
        return {"enabled": True, "source": self.source_name}


class VKProvider(ProviderBase):
    source_name = "vk"

    async def search(self, query: str, limit: int = 10) -> List[TrackPayload]:
        base_url = (self.settings.VK_API_BASE_URL or "").strip().rstrip("/")
        if not base_url:
            return []

        endpoint = f"{base_url}{self.settings.VK_SEARCH_PATH}"
        headers = {}
        if self.settings.VK_API_TOKEN:
            header_name = (self.settings.VK_TOKEN_HEADER or "Authorization").strip() or "Authorization"
            if header_name.lower() == "authorization":
                headers[header_name] = f"Bearer {self.settings.VK_API_TOKEN}"
            else:
                headers[header_name] = self.settings.VK_API_TOKEN

        timeout = aiohttp.ClientTimeout(total=self.settings.HTTP_TIMEOUT)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(endpoint, params={"q": query, "limit": limit}, headers=headers) as response:
                if response.status >= 400:
                    logger.warning("VK search returned HTTP %s", response.status)
                    return []
                payload = await response.json(content_type=None)

        items = payload.get("items") if isinstance(payload, dict) else payload
        if not isinstance(items, list):
            return []

        results: List[TrackPayload] = []
        for item in items[:limit]:
            if not isinstance(item, dict):
                continue
            track_id = item.get("id") or item.get("vk_id") or item.get("track_id")
            stream_url = item.get("stream_url") or item.get("url") or item.get("play_url") or ""
            if not stream_url and track_id:
                stream_url = f"vk://{track_id}"
            results.append(
                TrackPayload(
                    title=str(item.get("title") or item.get("name") or "Unknown"),
                    artist=str(item.get("artist") or item.get("uploader") or item.get("author") or "Unknown"),
                    duration=int(item.get("duration") or item.get("length") or 0),
                    stream_url=str(stream_url),
                    source=self.source_name,
                    track_id=str(track_id) if track_id is not None else None,
                    thumbnail=str(item.get("thumbnail") or item.get("cover") or "") or None,
                    extra=item,
                )
            )
        return results

    async def resolve(self, target: Any) -> Optional[TrackPayload]:
        candidate = TrackPayload.from_any(target)
        if (
            candidate.source == self.source_name
            and candidate.stream_url
            and candidate.stream_url.startswith("http")
            and _infer_source_from_url(candidate.stream_url) == "direct"
        ):
            return candidate

        base_url = (self.settings.VK_API_BASE_URL or "").strip().rstrip("/")
        if not base_url:
            return None

        endpoint = f"{base_url}{self.settings.VK_RESOLVE_PATH}"
        payload: Dict[str, Any] = {}
        if candidate.track_id:
            payload["id"] = candidate.track_id
        if candidate.stream_url:
            payload["url"] = candidate.stream_url
        payload["query"] = candidate.title
        payload["artist"] = candidate.artist

        headers = {}
        if self.settings.VK_API_TOKEN:
            header_name = (self.settings.VK_TOKEN_HEADER or "Authorization").strip() or "Authorization"
            if header_name.lower() == "authorization":
                headers[header_name] = f"Bearer {self.settings.VK_API_TOKEN}"
            else:
                headers[header_name] = self.settings.VK_API_TOKEN

        timeout = aiohttp.ClientTimeout(total=self.settings.HTTP_TIMEOUT)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(endpoint, json=payload, headers=headers) as response:
                if response.status >= 400:
                    logger.warning("VK resolve returned HTTP %s", response.status)
                    return None
                data = await response.json(content_type=None)

        resolved = TrackPayload.from_any(data)
        if not resolved.stream_url and isinstance(data, dict):
            resolved.stream_url = str(data.get("stream_url") or data.get("url") or data.get("play_url") or "")
        if not resolved.track_id and candidate.track_id:
            resolved.track_id = candidate.track_id
        resolved.source = self.source_name
        return resolved if resolved.stream_url else None

    async def health(self) -> Dict[str, Any]:
        return {
            "enabled": bool((self.settings.VK_API_BASE_URL or "").strip()),
            "base_url": self.settings.VK_API_BASE_URL,
            "source": self.source_name,
        }


class DeezerProvider(ProviderBase):
    source_name = "deezer"

    def __init__(self, settings: BackendSettings, token_pool: DeezerTokenPool):
        super().__init__(settings)
        self.token_pool = token_pool

    def _auth_params(self, token: Optional[str]) -> Dict[str, str]:
        params: Dict[str, str] = {}
        if token:
            params["access_token"] = token
        return params

    async def search(self, query: str, limit: int = 10) -> List[TrackPayload]:
        endpoint = f"{self.settings.DEEZER_API_BASE_URL.rstrip('/')}/search"
        attempts = max(1, len(self.token_pool.tokens) or 1)
        timeout = aiohttp.ClientTimeout(total=self.settings.HTTP_TIMEOUT)

        async with aiohttp.ClientSession(timeout=timeout) as session:
            for _ in range(attempts):
                token = self.token_pool.pick()
                params = {"q": query, "limit": limit}
                params.update(self._auth_params(token))
                async with session.get(endpoint, params=params) as response:
                    if response.status in (401, 403, 429):
                        self.token_pool.record_failure(token, response.status)
                        continue
                    if response.status >= 400:
                        logger.warning("Deezer search returned HTTP %s", response.status)
                        continue
                    payload = await response.json(content_type=None)
                    self.token_pool.record_success(token)
                    break
            else:
                return []

        items = payload.get("data") if isinstance(payload, dict) else payload
        if not isinstance(items, list):
            return []

        results: List[TrackPayload] = []
        for item in items[:limit]:
            if not isinstance(item, dict):
                continue
            artist = "Unknown"
            album = None
            if isinstance(item.get("artist"), dict):
                artist = item["artist"].get("name") or artist
            if isinstance(item.get("album"), dict):
                album = item["album"].get("title")
            track_id = item.get("id")
            stream_url = item.get("preview") or item.get("stream_url") or ""
            if not stream_url and track_id:
                stream_url = f"deezer://{track_id}"
            results.append(
                TrackPayload(
                    title=str(item.get("title") or "Unknown"),
                    artist=str(artist),
                    duration=int(item.get("duration") or 0),
                    stream_url=str(stream_url),
                    source=self.source_name,
                    track_id=str(track_id) if track_id is not None else None,
                    thumbnail=str((item.get("album") or {}).get("cover_small") or (item.get("album") or {}).get("cover") or "") or None,
                    extra={"album": album, **item},
                )
            )
        return results

    async def resolve(self, target: Any) -> Optional[TrackPayload]:
        candidate = TrackPayload.from_any(target)
        if (
            candidate.source == self.source_name
            and candidate.stream_url
            and candidate.stream_url.startswith("http")
            and _infer_source_from_url(candidate.stream_url) == "direct"
        ):
            return candidate

        resolve_url = (self.settings.DEEZER_RESOLVE_URL or "").strip()
        if resolve_url:
            timeout = aiohttp.ClientTimeout(total=self.settings.HTTP_TIMEOUT)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(resolve_url, json=candidate.to_dict()) as response:
                    if response.status >= 400:
                        logger.warning("Deezer resolve returned HTTP %s", response.status)
                        return None
                    data = await response.json(content_type=None)
                    resolved = TrackPayload.from_any(data)
                    if resolved.stream_url:
                        resolved.source = self.source_name
                        return resolved

        if candidate.stream_url.startswith("http") and not is_unsupported_page_url(candidate.stream_url):
            candidate.source = self.source_name
            return candidate
        return None

    async def health(self) -> Dict[str, Any]:
        return {
            "enabled": True,
            "resolve_url": self.settings.DEEZER_RESOLVE_URL,
            "tokens": self.token_pool._snapshot(),
            "source": self.source_name,
        }


class MusicService:
    """Shared VK-first aggregator used by both the backend API and Telegram bot."""

    def __init__(self, settings_obj: Optional[BackendSettings] = None):
        self.settings = settings_obj or settings
        self.token_pool = DeezerTokenPool(self.settings.DEEZER_TOKENS)
        self.providers: Dict[str, ProviderBase] = {
            "vk": VKProvider(self.settings),
            "deezer": DeezerProvider(self.settings, self.token_pool),
        }
        self.source_order = [
            name.strip().lower()
            for name in (self.settings.SOURCE_ORDER or "vk,deezer").split(",")
            if name.strip().lower() in self.providers
        ] or ["vk", "deezer"]
        self._ready = False

    async def start(self) -> None:
        self._ready = True

    async def close(self) -> None:
        self._ready = False

    @staticmethod
    def _cache_key(prefix: str, query: str, limit: int) -> str:
        digest = hashlib.sha1(f"{query.strip().lower()}::{limit}".encode("utf-8")).hexdigest()
        return f"{prefix}:{digest}"

    @staticmethod
    def _normalize_target(target: Any) -> TrackPayload:
        return TrackPayload.from_any(target)

    async def _cache_get_json(self, key: str) -> Optional[Any]:
        try:
            raw = await cache.get(key)
        except Exception:
            return None
        if not raw:
            return None
        try:
            return json.loads(raw)
        except Exception:
            return None

    async def _cache_set_json(self, key: str, value: Any, ttl: int) -> None:
        try:
            await cache.set(key, json.dumps(value, ensure_ascii=False), ex=ttl)
        except Exception:
            pass

    async def search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        query = (query or "").strip()
        if not query:
            return []

        cache_key = self._cache_key("vkms:search", query, limit)
        cached = await self._cache_get_json(cache_key)
        if isinstance(cached, list):
            return cached[:limit]

        results: List[TrackPayload] = []
        seen: set[str] = set()

        for source_name in self.source_order:
            provider = self.providers[source_name]
            try:
                provider_results = await provider.search(query, limit=max(1, limit - len(results)))
            except Exception as exc:
                logger.warning("%s search failed for '%s': %s", source_name, query, exc)
                continue

            for item in provider_results or []:
                if not isinstance(item, TrackPayload):
                    continue
                dedupe_key = (item.track_id or item.stream_url or item.title).strip().lower()
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                results.append(item)
                if len(results) >= limit:
                    break

            if len(results) >= limit:
                break

        payload = [track.to_dict() for track in results]
        await self._cache_set_json(cache_key, payload, self.settings.SEARCH_CACHE_TTL)
        return payload

    def _resolve_source_order(self, target: TrackPayload) -> List[str]:
        url = (target.stream_url or "").strip().lower()
        source = (target.source or "").strip().lower()

        if source in self.providers:
            preferred = [source]
        elif url.startswith("vk://") or "vk.com" in url:
            preferred = ["vk", "deezer"]
        elif url.startswith("deezer://") or "deezer" in url:
            preferred = ["deezer", "vk"]
        else:
            preferred = list(self.source_order)

        for name in self.source_order:
            if name not in preferred:
                preferred.append(name)
        return preferred

    async def resolve(self, target: Any) -> Optional[Dict[str, Any]]:
        candidate = self._normalize_target(target)
        cache_key = self._cache_key("vkms:resolve", candidate.stream_url or candidate.track_id or candidate.title, 1)
        cached = await self._cache_get_json(cache_key)
        if isinstance(cached, dict) and cached.get("stream_url"):
            return cached

        if candidate.stream_url and candidate.stream_url.startswith("http") and _infer_source_from_url(candidate.stream_url) == "direct":
            direct = candidate.to_dict()
            await self._cache_set_json(cache_key, direct, self.settings.RESOLVE_CACHE_TTL)
            return direct

        for source_name in self._resolve_source_order(candidate):
            provider = self.providers[source_name]
            try:
                resolved = await provider.resolve(candidate)
            except Exception as exc:
                logger.warning("%s resolve failed for '%s': %s", source_name, candidate.title, exc)
                continue
            if not resolved or not resolved.stream_url:
                continue
            payload = resolved.to_dict()
            await self._cache_set_json(cache_key, payload, self.settings.RESOLVE_CACHE_TTL)
            return payload

        return None

    async def health(self) -> Dict[str, Any]:
        provider_health: Dict[str, Any] = {}
        for source_name, provider in self.providers.items():
            try:
                provider_health[source_name] = await provider.health()
            except Exception as exc:
                provider_health[source_name] = {"enabled": False, "error": str(exc), "source": source_name}
        return {
            "ready": self._ready,
            "source_order": self.source_order,
            "providers": provider_health,
            "redis_mode": getattr(cache, "CACHE_MODE", "unknown"),
        }

    async def allow_request(self, client_id: str, route: str) -> bool:
        now = int(time.time())
        window = now // 60
        key = f"vkms:rl:{client_id}:{route}:{window}"
        try:
            # Use atomic increment semantics when possible and set TTL on first increment
            count = await cache.incr(key)
            if int(count) == 1:
                # first hit in this time window - set expiry
                try:
                    await cache.expire(key, 65)
                except Exception:
                    # best-effort expiry; continue
                    pass
            return int(count) <= self.settings.RATE_LIMIT_PER_MINUTE
        except Exception:
            # Conservative default: deny when cache/rate-limiter unavailable
            return False


music_service = MusicService()


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    limit: int = Field(default=20, ge=1, le=50)


class ResolveRequest(BaseModel):
    title: Optional[str] = None
    artist: Optional[str] = None
    duration: int = 0
    stream_url: Optional[str] = None
    source: Optional[str] = None
    track_id: Optional[str] = None
    thumbnail: Optional[str] = None


app = FastAPI(title="VK Music Backend", version="0.1.0")

# Configure CORS origins using environment-driven settings to avoid overly-permissive defaults
raw_allowed = (settings.CORS_ALLOWED_ORIGINS or "").strip()
if raw_allowed:
    allowed_origins = [o.strip() for o in re.split(r"[\s,;]+", raw_allowed) if o.strip()]
else:
    allowed_origins = []

# Determine whether credentials are allowed; never allow credentials when wildcard origin is present
allow_credentials = bool(settings.CORS_ALLOW_CREDENTIALS) and ("*" not in allowed_origins)

cors_kwargs = {"allow_methods": ["*"], "allow_headers": ["*"], "allow_credentials": allow_credentials}
if settings.CORS_ALLOW_ORIGIN_REGEX:
    cors_kwargs["allow_origin_regex"] = settings.CORS_ALLOW_ORIGIN_REGEX
else:
    # If no explicit origins configured, default to an empty list (deny by default)
    cors_kwargs["allow_origins"] = allowed_origins

app.add_middleware(CORSMiddleware, **cors_kwargs)


@app.on_event("startup")
async def _startup() -> None:
    await init_redis()
    await music_service.start()


@app.on_event("shutdown")
async def _shutdown() -> None:
    await music_service.close()


@app.middleware("http")
async def _rate_limit_middleware(request: Request, call_next):
    if request.url.path in {"/health", "/docs", "/openapi.json", "/redoc"}:
        return await call_next(request)

    client_ip = request.headers.get("x-forwarded-for")
    if client_ip:
        client_ip = client_ip.split(",")[0].strip()
    elif request.client:
        client_ip = request.client.host or "unknown"
    else:
        client_ip = "unknown"

    if not await music_service.allow_request(client_ip, request.url.path):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    return await call_next(request)


@app.get("/health")
async def health() -> Dict[str, Any]:
    return await music_service.health()


@app.get("/providers")
async def providers() -> Dict[str, Any]:
    return await music_service.health()


@app.get("/search")
async def search(q: str, limit: int = 20) -> Dict[str, Any]:
    query = (q or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query is required")
    results = await music_service.search(query, limit=limit)
    return {"query": query, "limit": limit, "count": len(results), "items": results}


@app.post("/resolve")
async def resolve(payload: ResolveRequest) -> Dict[str, Any]:
    target = TrackPayload.from_any(payload.model_dump(exclude_none=True))
    resolved = await music_service.resolve(target)
    if not resolved:
        raise HTTPException(status_code=404, detail="Unable to resolve a playable stream")
    return resolved


@app.post("/search")
async def search_post(payload: SearchRequest) -> Dict[str, Any]:
    results = await music_service.search(payload.query, limit=payload.limit)
    return {"query": payload.query, "limit": payload.limit, "count": len(results), "items": results}


@app.get("/status")
async def status() -> Dict[str, Any]:
    return await music_service.health()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("vk_music_backend:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")), reload=False)
