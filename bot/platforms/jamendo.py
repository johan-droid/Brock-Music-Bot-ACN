import logging
import os
from typing import List, Dict, Any, Optional

import aiohttp

from bot.platforms.jamendo_embedded import DEFAULT_JAMENDO_CLIENT_ID, JamendoEmbedded
from bot.utils.resilience import with_retries_and_cb, jamendo_cb
from config import config

logger = logging.getLogger(__name__)

_env_client_id = os.getenv("JAMENDO_CLIENT_ID")
_config_client_id = getattr(config, "JAMENDO_CLIENT_ID", None)
JAMENDO_CLIENT_ID = _env_client_id or _config_client_id or DEFAULT_JAMENDO_CLIENT_ID
JAMENDO_CLIENT_ID_SOURCE = "env" if _env_client_id else "config" if _config_client_id else "embedded"
JAMENDO_API_BASE = "https://api.jamendo.com/v3.0"

_cache = {}
_embedded = JamendoEmbedded(client_id=JAMENDO_CLIENT_ID)


class Track:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class JamendoClient:
    @staticmethod
    def _to_track_dict(item: Dict[str, Any]) -> Dict[str, Any]:
        track_id = item.get("id") or item.get("track_id")
        title = item.get("name") or item.get("title") or "Unknown Title"
        artist = item.get("artist_name") or item.get("artist") or "Unknown Artist"
        audio = item.get("audio") or item.get("audio_url") or item.get("stream_url") or item.get("url") or ""
        image = item.get("image") or item.get("album_image") or item.get("thumbnail_url") or item.get("thumbnail") or ""
        duration = int(item.get("duration") or 0)

        return {
            "id": str(track_id) if track_id is not None else "",
            "track_id": str(track_id) if track_id is not None else "",
            "name": title,
            "title": title,
            "artist_name": artist,
            "artist": artist,
            "duration": duration,
            "audio": audio,
            "audio_url": audio,
            "stream_url": audio,
            "url": audio,
            "image": image,
            "album_image": image,
            "thumbnail": image,
            "thumbnail_url": image,
            "source": "jamendo",
        }

    @staticmethod
    @with_retries_and_cb(jamendo_cb, max_retries=5, timeout=8)
    async def _make_request(endpoint: str, params: dict) -> dict:
        params["client_id"] = JAMENDO_CLIENT_ID
        params["format"] = "jsonpretty"

        cache_key = f"{endpoint}:{str(params)}"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{JAMENDO_API_BASE}/{endpoint}", params=params) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        _cache[cache_key] = data
                        return data
                    if resp.status == 429:
                        raise Exception("Jamendo Rate Limit 429")
                    if resp.status >= 500:
                        raise Exception(f"Jamendo Server Error {resp.status}")
                    resp.raise_for_status()
        except Exception as e:
            if cache_key in _cache:
                logger.warning(f"Using cached result for {endpoint} due to error: {e}")
                return _cache[cache_key]
            raise e

    @classmethod
    async def search(cls, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        try:
            data = await cls._make_request("tracks/", {"search": query, "limit": limit})
            results = data.get("results", [])
            tracks = [cls._to_track_dict(item) for item in results]
            if tracks:
                return tracks
        except Exception as e:
            logger.error(f"Jamendo search failed: {e}")

        fallback = await _embedded.search_tracks(query, limit)
        return [cls._to_track_dict(item) for item in fallback]

    @classmethod
    async def extract(cls, track_id: str) -> Optional[Dict[str, Any]]:
        try:
            data = await cls._make_request("tracks/", {"id": track_id})
            results = data.get("results", [])
            if results:
                track = cls._to_track_dict(results[0])
                track["headers"] = {}
                return track
        except Exception as e:
            logger.error(f"Jamendo extract failed: {e}")

        fallback = await _embedded.get_track_by_id(int(track_id)) if str(track_id).isdigit() else None
        if not fallback:
            return None
        track = cls._to_track_dict(fallback)
        track["headers"] = {}
        return track

    async def get_random_tracks(self, limit: int = 20, genre: Optional[str] = None) -> List[Dict[str, Any]]:
        params = {"limit": limit}
        if genre:
            params["tags"] = genre
        try:
            data = await self._make_request("tracks/", params)
            results = data.get("results", [])
            if results:
                return [self._to_track_dict(item) for item in results]
        except Exception as e:
            logger.error(f"Jamendo random tracks failed: {e}")

        fallback = await _embedded.search_by_genre(genre or "popular", limit)
        return [self._to_track_dict(item) for item in fallback]


class JamendoAPI:
    """Jamendo API wrapper for user OAuth and playlists."""

    BASE_URL = "https://api.jamendo.com/v3.0"
    OAUTH_URL = "https://api.jamendo.com/v3.0/oauth/authorize"
    TOKEN_URL = "https://api.jamendo.com/v3.0/oauth/grant"

    def __init__(self):
        self.client_id = getattr(config, "JAMENDO_CLIENT_ID", None)
        self.client_secret = getattr(config, "JAMENDO_CLIENT_SECRET", None)
        self.redirect_uri = getattr(config, "JAMENDO_REDIRECT_URI", "http://localhost:8000/jamendo/callback")

    def is_configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    def generate_oauth_url(self, user_id: int) -> str:
        if not self.is_configured():
            return ""
        return (
            f"{self.OAUTH_URL}?client_id={self.client_id}&redirect_uri={self.redirect_uri}"
            f"&scope=music&state={user_id}"
        )

    async def exchange_auth_code(self, code: str) -> Optional[Dict[str, Any]]:
        if not self.is_configured():
            return None

        async with aiohttp.ClientSession() as session:
            data = {
                "grant_type": "authorization_code",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "code": code,
                "redirect_uri": self.redirect_uri,
            }
            try:
                async with session.post(self.TOKEN_URL, data=data) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    logger.error(f"Jamendo auth failed: {resp.status} {await resp.text()}")
                    return None
            except Exception as e:
                logger.error(f"Jamendo auth exception: {e}")
                return None

    async def create_jamendo_playlist(self, access_token: str, name: str) -> Optional[str]:
        async with aiohttp.ClientSession() as session:
            params = {
                "client_id": self.client_id,
                "access_token": access_token,
                "name": name,
            }
            try:
                async with session.post(f"{self.BASE_URL}/playlists/", params=params) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("headers", {}).get("status") == "success":
                            return data.get("results", [{}])[0].get("id")
                    logger.error(f"Jamendo create playlist failed: {await resp.text()}")
                    return None
            except Exception as e:
                logger.error(f"Jamendo create playlist exception: {e}")
                return None

    async def add_tracks_to_jamendo_playlist(self, access_token: str, playlist_id: str, track_ids: List[str]) -> bool:
        if not track_ids:
            return True

        async with aiohttp.ClientSession() as session:
            params = {
                "client_id": self.client_id,
                "access_token": access_token,
                "id": playlist_id,
                "track_id": track_ids,
            }
            try:
                async with session.post(f"{self.BASE_URL}/playlists/tracks/", data=params) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get("headers", {}).get("status") == "success"
                    logger.error(f"Jamendo add tracks failed: {await resp.text()}")
                    return False
            except Exception as e:
                logger.error(f"Jamendo add tracks exception: {e}")
                return False


jamendo_client = JamendoClient()
jamendo_api = JamendoAPI()
