import os
import time
import logging
import asyncio
import aiohttp
from typing import List, Dict, Optional, Any
import json
import re

logger = logging.getLogger(__name__)

DEFAULT_JAMENDO_CLIENT_ID = "56d30c95"


def _build_soup(html: str):
    try:
        from bs4 import BeautifulSoup  # type: ignore[import]
    except Exception:
        logger.warning("beautifulsoup4 is not installed; Jamendo web scraping fallback is disabled.")
        return None
    return BeautifulSoup(html, 'html.parser')

class JamendoEmbedded:
    """
    Zero-dependency standalone Jamendo integration module.
    Provides three layers of fallback for track metadata and audio URL extraction.
    """

    API_V3_BASE = "https://api.jamendo.com/v3.0"
    STORAGE_BASE = "https://prod-1.storage.jamendo.com/"

    MOOD_TO_TAGS = {
        'happy': ['happy', 'energetic', 'upbeat', 'joy', 'positive'],
        'sad': ['sad', 'melancholic', 'depressing', 'sorrow', 'emotional'],
        'chill': ['chillout', 'ambient', 'downtempo', 'relax', 'calm', 'lounge'],
        'energetic': ['energetic', 'workout', 'gym', 'party', 'dance', 'upbeat'],
        'romantic': ['romantic', 'love', 'sweet', 'ballad'],
        'focus': ['focus', 'study', 'concentration', 'work', 'ambient'],
        'dark': ['dark', 'creepy', 'scary', 'suspense', 'tension']
    }

    RADIO_STREAMS = [
        {"name": "Jamendo Lounge", "url": "https://streaming.radionomy.com/JamRock"},
        {"name": "Electronic", "url": "https://streaming.radionomy.com/JamElectronic"},
        {"name": "Pop", "url": "https://streaming.radionomy.com/JamPop"},
        {"name": "Rock", "url": "https://streaming.radionomy.com/JamRock"},
        {"name": "Metal", "url": "https://listen.radioking.com/radio/10421/stream/17855"},
        {"name": "Classical", "url": "http://listen.radionomy.com/jamendo-classical"},
        {"name": "Hip Hop", "url": "http://listen.radionomy.com/jamendo-hiphop"},
        {"name": "Jazz", "url": "http://listen.radionomy.com/jamendo-jazz"},
        {"name": "Dance", "url": "http://listen.radionomy.com/jamendo-dance"},
        {"name": "World", "url": "http://listen.radionomy.com/jamendo-world"},
        {"name": "Ambient", "url": "http://listen.radionomy.com/jamendo-ambient"},
        {"name": "R&B", "url": "http://listen.radionomy.com/jamendo-rnb"},
        {"name": "Reggae", "url": "http://listen.radionomy.com/jamendo-reggae"},
        {"name": "Folk", "url": "http://listen.radionomy.com/jamendo-folk"},
        {"name": "Country", "url": "http://listen.radionomy.com/jamendo-country"},
        {"name": "Soundtrack", "url": "http://listen.radionomy.com/jamendo-soundtrack"},
        {"name": "Indie", "url": "http://listen.radionomy.com/jamendo-indie"},
        {"name": "Blues", "url": "http://listen.radionomy.com/jamendo-blues"},
        {"name": "Latin", "url": "http://listen.radionomy.com/jamendo-latin"},
        {"name": "Chanson", "url": "http://listen.radionomy.com/jamendo-chanson"}
    ]

    def __init__(self, client_id: Optional[str] = None, cache_ttl: int = 600):
        if client_id is not None:
            self.client_id = client_id
        else:
            self.client_id = os.environ.get("JAMENDO_CLIENT_ID") or DEFAULT_JAMENDO_CLIENT_ID
        self.cache_ttl = cache_ttl
        self._cache = {}

    def _get_cache(self, key: str) -> Optional[Any]:
        if key in self._cache:
            entry = self._cache[key]
            if time.time() < entry['expiry']:
                return entry['data']
            else:
                del self._cache[key]
        return None

    def _set_cache(self, key: str, data: Any):
        self._cache[key] = {
            'data': data,
            'expiry': time.time() + self.cache_ttl
        }

    async def _api_get(self, endpoint: str, params: dict) -> Optional[dict]:
        """Layer 1: Official API request"""
        if not self.client_id:
            return None

        params['client_id'] = self.client_id
        params['format'] = 'jsonpretty'
        url = f"{self.API_V3_BASE}/{endpoint.lstrip('/')}"

        try:
            async with aiohttp.ClientSession() as session:
                timeout = aiohttp.ClientTimeout(total=8)
                async with session.get(url, params=params, timeout=timeout) as resp:
                    if resp.status == 200:
                        return await resp.json()
        except Exception as e:
            logger.warning(f"Jamendo API V3 Error: {e}")
        return None

    def _parse_api_track(self, item: dict) -> dict:
        return {
            "id": int(item.get("id", 0)),
            "title": item.get("name", "Unknown Title"),
            "artist": item.get("artist_name", "Unknown Artist"),
            "duration": int(item.get("duration", 0)),
            "audio_url": item.get("audio", ""),
            "thumbnail_url": item.get("image", "")
        }

    # --- Layer 1/2 Search Tracks ---
    async def search_tracks(self, query: str, limit: int = 10) -> list[dict]:
        cache_key = f"search:{query}:{limit}"
        cached = self._get_cache(cache_key)
        if cached is not None:
            return cached

        # Layer 1: API
        if self.client_id:
            data = await self._api_get("tracks/", {"search": query, "limit": limit})
            if data and data.get("headers", {}).get("status") == "success":
                results = [self._parse_api_track(t) for t in data.get("results", [])]
                if results:
                    self._set_cache(cache_key, results)
                    return results

        # Layer 2: Web Scraping fallback
        results = await self._scrape_search(query, limit)
        if results:
            self._set_cache(cache_key, results)
        return results

    async def _scrape_search(self, query: str, limit: int) -> list[dict]:
        """Scrape tracks from Jamendo public site (Layer 2)"""
        url = f"https://www.jamendo.com/search"
        try:
            async with aiohttp.ClientSession() as session:
                timeout = aiohttp.ClientTimeout(total=8)
                async with session.get(url, params={"q": query}, timeout=timeout) as resp:
                    if resp.status == 200:
                        html = await resp.text()
                        soup = _build_soup(html)
                        if soup is None:
                            return []

                        track_ids = []

                        # Extract IDs from __NEXT_DATA__
                        scripts = soup.find_all('script')
                        for s in scripts:
                            if s.string and '__NEXT_DATA__' in s.string:
                                try:
                                    json_data = json.loads(s.string)
                                    # Fallback to regex id extraction from the json dump
                                    matches = re.findall(r'"id":\s*(\d+)', s.string)
                                    track_ids.extend(matches)
                                except Exception:
                                    pass

                        # Extract from JSON-LD
                        ld_scripts = soup.find_all('script', type='application/ld+json')
                        for ld in ld_scripts:
                            if ld.string:
                                try:
                                    ld_data = json.loads(ld.string)
                                    matches = re.findall(r'"@id":.*?/track/(\d+)', ld.string)
                                    track_ids.extend(matches)
                                except Exception:
                                    pass

                        # Fallback parsing
                        found = re.findall(r'/track/(\d+)', html)
                        track_ids.extend(found)

                        items = soup.select("[data-track-id]")
                        for item in items:
                            val = item.get("data-track-id")
                            if val:
                                track_ids.append(val)

                        track_ids = list(dict.fromkeys(track_ids)) # Unique

                        results = []
                        for tid in track_ids[:limit]:
                            track = await self.get_track_by_id(int(tid))
                            if track:
                                results.append(track)
                        return results
        except Exception as e:
            logger.warning(f"Jamendo Scrape Search Error: {e}")
        return []

    # --- Track by ID ---
    async def get_track_by_id(self, track_id: int) -> Optional[dict]:
        cache_key = f"track:{track_id}"
        cached = self._get_cache(cache_key)
        if cached is not None:
            return cached

        # Layer 1: API
        if self.client_id:
            data = await self._api_get("tracks/", {"id": track_id})
            if data and data.get("headers", {}).get("status") == "success":
                results = data.get("results", [])
                if results:
                    track = self._parse_api_track(results[0])
                    self._set_cache(cache_key, track)
                    return track

        # Layer 2: Storage URL Construction & Scraping
        track = await self._scrape_track_metadata(track_id)
        if track:
            self._set_cache(cache_key, track)
        return track

    async def _scrape_track_metadata(self, track_id: int) -> Optional[dict]:
        url = f"https://www.jamendo.com/track/{track_id}"
        try:
            async with aiohttp.ClientSession() as session:
                timeout = aiohttp.ClientTimeout(total=8)
                async with session.get(url, timeout=timeout) as resp:
                    if resp.status == 200:
                        html = await resp.text()
                        soup = _build_soup(html)
                        if soup is None:
                            return None

                        title = "Unknown Title"
                        artist = "Unknown Artist"
                        thumbnail_url = ""

                        if soup.title and soup.title.string:
                            parts = soup.title.string.split('|')[0].strip().split(' - ')
                            if len(parts) >= 2:
                                title = parts[0].strip()
                                artist = parts[1].strip()
                            else:
                                title = parts[0].strip()

                        og_image = soup.find('meta', property='og:image')
                        if og_image:
                            thumbnail_url = og_image.get('content', '')

                        audio_url = await self.get_track_audio_url(track_id)

                        if not audio_url:
                            return None

                        return {
                            "id": track_id,
                            "title": title,
                            "artist": artist,
                            "duration": 0,
                            "audio_url": audio_url,
                            "thumbnail_url": thumbnail_url
                        }
        except Exception as e:
            logger.warning(f"Jamendo Scrape Track Metadata Error: {e}")
        return None

    # --- Direct Audio URL Construction ---
    async def get_track_audio_url(self, track_id: int) -> Optional[str]:
        # Parse licensing page as per prompt
        licensing_url = f"https://licensing.jamendo.com/track/{track_id}"
        try:
            async with aiohttp.ClientSession() as session:
                timeout = aiohttp.ClientTimeout(total=8)
                async with session.get(licensing_url, timeout=timeout) as resp:
                    if resp.status == 200:
                        html = await resp.text()
                        soup = _build_soup(html)
                        if soup is None:
                            return None
                        scripts = soup.find_all('script')
                        for s in scripts:
                            if s.string and 'prod-1.storage.jamendo.com' in s.string:
                                match = re.search(r'https://prod-1.storage.jamendo.com/\?trackid=(\d+)', s.string)
                                if match:
                                    tid = match.group(1)
                                    url_mp32 = f"{self.STORAGE_BASE}?trackid={tid}&format=mp32"
                                    if await self._check_url(url_mp32):
                                        return url_mp32
        except Exception:
            pass

        url_mp32 = f"{self.STORAGE_BASE}?trackid={track_id}&format=mp32"
        if await self._check_url(url_mp32):
            return url_mp32

        url_mp31 = f"{self.STORAGE_BASE}?trackid={track_id}&format=mp31"
        if await self._check_url(url_mp31):
            return url_mp31

        url_ogg = f"http://storage-new.newjamendo.com/?trackid={track_id}&format=ogg2&u=0"
        if await self._check_url(url_ogg):
            return url_ogg

        return None

    async def _check_url(self, url: str) -> bool:
        try:
            async with aiohttp.ClientSession() as session:
                headers = {"Range": "bytes=0-100"}
                timeout = aiohttp.ClientTimeout(total=5)
                async with session.get(url, headers=headers, timeout=timeout) as resp:
                    if resp.status in (200, 206):
                        content_type = resp.headers.get('Content-Type', '')
                        if 'audio' in content_type.lower() or 'mpeg' in content_type.lower() or 'ogg' in content_type.lower():
                            return True
        except:
            pass
        return False

    # --- Genres & Moods ---
    async def search_by_genre(self, genre: str, limit: int = 20) -> list[dict]:
        cache_key = f"genre:{genre}:{limit}"
        cached = self._get_cache(cache_key)
        if cached is not None:
            return cached

        # Layer 1
        if self.client_id:
            data = await self._api_get("tracks/", {"tags": genre, "limit": limit})
            if data and data.get("headers", {}).get("status") == "success":
                results = [self._parse_api_track(t) for t in data.get("results", [])]
                if results:
                    self._set_cache(cache_key, results)
                    return results

        # Layer 2 Scraping
        results = await self._scrape_search(genre, limit)
        if results:
            self._set_cache(cache_key, results)
        return results

    async def search_by_mood(self, mood: str, limit: int = 20) -> list[dict]:
        mood_lower = mood.lower()
        tags = self.MOOD_TO_TAGS.get(mood_lower, [mood_lower])
        return await self.search_by_genre(tags[0], limit)

    # --- Layer 3: Radios ---
    async def get_radio_stream(self, genre: Optional[str] = None) -> Optional[str]:
        if self.client_id:
            try:
                data = await self._api_get("radios/", {})
                if data and data.get("headers", {}).get("status") == "success":
                    radios = data.get("results", [])
                    if radios:
                        radio_id = radios[0]["id"]
                        if genre:
                            for r in radios:
                                if genre.lower() in r.get("name", "").lower() or genre.lower() in r.get("dispname", "").lower():
                                    radio_id = r["id"]
                                    break

                        stream_data = await self._api_get("radios/stream/", {"id": radio_id})
                        if stream_data and stream_data.get("headers", {}).get("status") == "success":
                            results = stream_data.get("results", [])
                            if results and results[0].get("stream"):
                                return results[0]["stream"]
            except:
                pass

        if genre:
            for radio in self.RADIO_STREAMS:
                if genre.lower() in radio["name"].lower():
                    if await self._check_url(radio["url"]):
                        return radio["url"]

        for radio in self.RADIO_STREAMS:
            if await self._check_url(radio["url"]):
                return radio["url"]

        return None

    # --- Health Check ---
    async def health_check(self) -> dict:
        layer1 = False
        if self.client_id:
            data = await self._api_get("tracks/", {"limit": 1})
            layer1 = bool(data and data.get("headers", {}).get("status") == "success")

        layer2 = await self._check_url(f"{self.STORAGE_BASE}?trackid=1886257&format=mp32")

        layer3 = False
        for radio in self.RADIO_STREAMS:
            if await self._check_url(radio["url"]):
                layer3 = True
                break

        return {
            "layer1": layer1,
            "layer2": layer2,
            "layer3": layer3
        }
