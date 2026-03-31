"""JioSaavn integration — search with encrypted stream URL + generateAuthToken resolution."""

import html
import logging
import json
import aiohttp
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

JIOSAAVN_API = "https://www.jiosaavn.com/api.php"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.jiosaavn.com/",
    "Accept-Language": "en-US,en;q=0.9",
}


class JioSaavnExtractor:
    """Extract audio from JioSaavn using their public API."""

    def __init__(self):
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if not self._session or self._session.closed:
            self._session = aiohttp.ClientSession(headers=_HEADERS)
        return self._session

    # ── Internal JSON fetch ─────────────────────────────────────────────────

    async def _api_get(self, params: dict, timeout: int = 10) -> Optional[dict]:
        """Perform a GET to the JioSaavn API and return parsed JSON or None."""
        session = await self._get_session()
        try:
            async with session.get(JIOSAAVN_API, params=params, timeout=timeout) as resp:
                try:
                    return await resp.json(content_type=None)
                except Exception:
                    text = await resp.text()
                    try:
                        return json.loads(text)
                    except Exception:
                        logger.error(f"JioSaavn non-JSON response ({resp.status})")
                        return None
        except Exception as e:
            logger.error(f"JioSaavn API request failed: {e}")
            return None

    # ── Search ──────────────────────────────────────────────────────────────

    async def search(self, query: str, limit: int = 5) -> list:
        """Search JioSaavn and return list of result dicts."""
        params = {
            "__call": "search.getResults",
            "_format": "json",
            "_marker": "0",
            "api_version": "4",
            "ctx": "web6dot0",
            "caller": "PWA",
            "saavn_app": "2",
            "q": query,
            "n": limit,
            "p": "1",
        }

        data = await self._api_get(params)
        if not data:
            return []

        results = []
        for song in data.get("results", []):
            raw_title = song.get("title", "Unknown")

            more_info = song.get("more_info", {})
            raw_artist = (
                song.get("primary_artists")
                or _first_artist(more_info.get("artistMap", {}).get("primary_artists", []))
                or song.get("singers")
                or song.get("artist")
                or "Unknown Artist"
            )
            if isinstance(raw_artist, list):
                raw_artist = ", ".join(str(a) for a in raw_artist)

            encrypted_url = more_info.get("encrypted_media_url", "")

            results.append({
                "title": html.unescape(str(raw_title)).strip(),
                "uploader": html.unescape(str(raw_artist)).strip(),
                "duration": int(song.get("duration") or 0),
                # Store encrypted URL so streamURL can be resolved without a second API call
                "url": encrypted_url,
                "thumbnail": (song.get("image") or "").replace("150x150", "500x500"),
                "id": song.get("id"),
                "source": "jiosaavn",
            })

        return results

    # ── Stream URL resolution ────────────────────────────────────────────────

    async def get_stream_url(
        self, track_id: str = "", encrypted_url: str = ""
    ) -> Optional[str]:
        """
        Resolve a playable stream URL.
        Prefers generateAuthToken with the encrypted_url captured during search.
        Falls back to song.getDetails if necessary.
        """
        if not track_id and not encrypted_url:
            return None

        if encrypted_url:
            result = await self._generate_auth_token(encrypted_url)
            if result:
                return result
            logger.warning(f"generateAuthToken failed for {track_id}, trying song.getDetails")

        if not track_id:
            return None

        return await self._get_details_url(track_id)

    async def _generate_auth_token(self, encrypted_url: str) -> Optional[str]:
        """Decode an encrypted JioSaavn media URL via song.generateAuthToken."""
        params = {
            "__call": "song.generateAuthToken",
            "_format": "json",
            "_marker": "0",
            "api_version": "4",
            "ctx": "web6dot0",
            "bitrate": "320",
            "url": encrypted_url,
        }
        data = await self._api_get(params)
        if data:
            auth_url = data.get("auth_url")
            if auth_url:
                logger.info("JioSaavn stream URL decoded via generateAuthToken")
                # Ensure the URL is absolute and use 320kbps if possible
                if ".jiosaavn.com" in auth_url or "cdn-songs" in auth_url:
                   return auth_url.replace("_96.", "_320.").replace("_160.", "_320.")
                return auth_url
        return None

    async def _get_details_url(self, track_id: str) -> Optional[str]:
        """Fallback: fetch song details to get media URL."""
        params = {
            "__call": "song.getDetails",
            "_format": "json",
            "_marker": "0",
            "api_version": "4",
            "ctx": "web6dot0",
            "caller": "PWA",
            "saavn_app": "2",
            "pids": str(track_id),
        }
        data = await self._api_get(params)
        if not data:
            return None

        songs = data.get("songs", [])
        if not songs and isinstance(data, dict) and str(track_id) in data:
            songs = [data[str(track_id)]]
        if not songs:
            return None

        song = songs[0]
        media_url = song.get("media_url", "")
        if media_url:
            return media_url.replace("_96.", "_320.").replace("_160.", "_320.")

        enc = song.get("more_info", {}).get("encrypted_media_url", "")
        if enc:
            return await self._generate_auth_token(enc)

        return None

    # ── Direct URL extraction ────────────────────────────────────────────────

    async def extract(self, query: str) -> Optional[Dict[str, Any]]:
        """
        Extract audio from a JioSaavn URL or search query.
        For URLs: parse the song ID, resolve stream URL.
        For text: search and return the first result with resolved URL.
        """
        if "jiosaavn.com" in query or "saavn.com" in query:
            return await self._extract_from_url(query)

        results = await self.search(query, limit=1)
        if not results:
            return None

        first = results[0]
        stream_url = await self.get_stream_url(
            track_id=first.get("id", ""),
            encrypted_url=first.get("url", ""),
        )
        if stream_url:
            first["url"] = stream_url
        return first if stream_url else None

    async def _extract_from_url(self, url: str) -> Optional[Dict[str, Any]]:
        """Extract track info from a JioSaavn page URL."""
        import re
        match = re.search(r"/song/[^/]+/([^/?#]+)", url)
        if not match:
            logger.warning(f"JioSaavn: cannot parse song ID from URL: {url}")
            return None

        song_id = match.group(1)
        stream_url = await self.get_stream_url(track_id=song_id)
        if not stream_url:
            return None

        # Fetch metadata
        params = {
            "__call": "song.getDetails",
            "_format": "json",
            "_marker": "0",
            "api_version": "4",
            "ctx": "web6dot0",
            "pids": song_id,
        }
        data = await self._api_get(params)
        songs = (data or {}).get("songs", []) if data else []
        if songs:
            song = songs[0]
            artist = (
                song.get("primary_artists")
                or _first_artist(song.get("more_info", {}).get("artistMap", {}).get("primary_artists", []))
                or song.get("singers")
                or "Unknown Artist"
            )
            return {
                "url": stream_url,
                "title": html.unescape(song.get("song") or song.get("title") or "Unknown"),
                "uploader": html.unescape(str(artist)),
                "duration": int(song.get("duration") or 0),
                "thumbnail": (song.get("image") or "").replace("150x150", "500x500"),
                "id": song_id,
                "source": "jiosaavn",
            }

        return {
            "url": stream_url,
            "title": "Unknown",
            "uploader": "Unknown Artist",
            "duration": 0,
            "source": "jiosaavn",
            "id": song_id
        }


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _first_artist(artist_list: list) -> Optional[str]:
    """Return name of the first artist in an artistMap list."""
    if artist_list and isinstance(artist_list, list):
        first = artist_list[0]
        if isinstance(first, dict):
            return first.get("name")
        return str(first)
    return None


# Global extractor
jiosaavn = JioSaavnExtractor()


async def extract_jiosaavn(query: str) -> Optional[Dict[str, Any]]:
    """Extract from JioSaavn URL or search query."""
    return await jiosaavn.extract(query)


async def search_jiosaavn(query: str, limit: int = 5) -> list:
    """Search JioSaavn."""
    return await jiosaavn.search(query, limit)
