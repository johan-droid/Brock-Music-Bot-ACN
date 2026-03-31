import asyncio
import logging
import aiohttp
import html
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)


@dataclass
class Track:
    """Universal track representation."""
    title: str
    artist: str
    duration: int  # seconds
    stream_url: str
    thumbnail: Optional[str] = None
    source: str = "unknown"  # jiosaavn, youtube, soundcloud
    track_id: Optional[str] = None

    def get(self, key: str, default: Any = None) -> Any:
        # Map common dict keys to attributes
        mapping = {
            "url": "stream_url",
            "uploader": "artist",
            "id": "track_id",
            "thumb": "thumbnail"
        }
        attr = mapping.get(key, key)
        return getattr(self, attr, default)

    def to_dict(self) -> Dict[str, Any]:
        """Convert Track to dictionary."""
        d = asdict(self)
        # Compatibility keys
        d["url"] = self.stream_url
        d["uploader"] = self.artist
        d["id"] = self.track_id
        d["thumb"] = self.thumbnail
        return d


class JioSaavnExtractor:
    """
    JioSaavn extractor - Legal free music source (Indian music).
    No API key required, public endpoints.
    """
    
    BASE_URL = "https://www.jiosaavn.com/api.php"
    
    def __init__(self, session: aiohttp.ClientSession):
        self.session = session
    
    async def search(self, query: str, limit: int = 5) -> List[Track]:
        """Search for songs on JioSaavn."""
        try:
            params = {
                "_format": "json",
                "_marker": "0",
                "api_version": "4",
                "ctx": "web6dot0",
                "q": query,
                "n": limit,
                "p": "1",
                "caller": "PWA",
                "saavn_app": "2",
                "__call": "search.getResults"
            }
            
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Referer": "https://www.jiosaavn.com/",
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "en-US,en;q=0.9",
            }
            
            async with self.session.get(self.BASE_URL, params=params, headers=headers, timeout=10) as resp:
                if resp.status != 200:
                    logger.warning(f"JioSaavn search failed with status {resp.status}")
                    return []
                
                try:
                    data = await resp.json()
                except Exception:
                    # Fallback to text and manual cleanup if mimetype is wrong
                    text = await resp.text()
                    import json
                    try:
                        data = json.loads(text)
                    except Exception as je:
                        logger.error(f"JioSaavn JSON decode error: {je}")
                        return []
                results = []
                
                for song in data.get("results", []):
                    # Unescape HTML entities (JioSaavn returns them frequently)
                    raw_title = song.get("title", "Unknown")
                    
                    # Artist may be top-level or nested in more_info
                    more_info = song.get("more_info", {})
                    raw_artist = (
                        song.get("primary_artists")
                        or more_info.get("artistMap", {}).get("primary_artists", [{}])[0].get("name")
                        or song.get("singers")
                        or song.get("artist")
                        or "Unknown Artist"
                    )
                    if isinstance(raw_artist, list):
                        raw_artist = ", ".join(str(a) for a in raw_artist)
                    
                    # Capture the encrypted stream URL from search (avoids a second API call)
                    encrypted_url = more_info.get("encrypted_media_url", "")
                    
                    track = Track(
                        title=html.unescape(str(raw_title)).strip(),
                        artist=html.unescape(str(raw_artist)).strip(),
                        duration=int(song.get("duration") or 0),
                        stream_url=encrypted_url,  # Encrypted — decoded on demand via generateAuthToken
                        thumbnail=(song.get("image") or "").replace("150x150", "500x500"),
                        source="jiosaavn",
                        track_id=song.get("id")
                    )
                    results.append(track)
                
                return results
                    
        except Exception as e:
            logger.error(f"JioSaavn search error: {e}")
            return []
    
    async def get_stream_url(self, track_id: str, encrypted_url: str = "") -> Optional[str]:
        """Get streaming URL for a JioSaavn track.
        
        Uses song.generateAuthToken to decode the encrypted_media_url captured during
        search, avoiding the unreliable song.getDetails endpoint. Falls back to a 
        fresh song.getDetails call only if no encrypted URL is available.
        """
        if not track_id and not encrypted_url:
            logger.error("JioSaavn get_stream_url called with no track_id or encrypted_url")
            return None
        
        # Primary path: decode the pre-captured encrypted URL
        if encrypted_url:
            result = await self._generate_auth_token(encrypted_url)
            if result:
                return result
            logger.warning(f"generateAuthToken failed for {track_id}, falling back to song.getDetails")
        
        # Fallback: fetch song details directly
        if not track_id:
            return None
        try:
            params = {
                "_format": "json",
                "_marker": "0",
                "api_version": "4",
                "ctx": "web6dot0",
                "caller": "PWA",
                "saavn_app": "2",
                "__call": "song.getDetails",
                "pids": str(track_id)
            }
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json, text/plain, */*",
                "Referer": "https://www.jiosaavn.com/",
            }
            async with self.session.get(self.BASE_URL, params=params, headers=headers, timeout=10) as resp:
                import json as _json
                try:
                    data = await resp.json(content_type=None)
                except Exception:
                    text = await resp.text()
                    try:
                        data = _json.loads(text)
                    except Exception:
                        logger.error(f"JioSaavn song.getDetails returned non-JSON for {track_id}")
                        return None
                
                songs = data.get("songs", [])
                if not songs and isinstance(data, dict) and str(track_id) in data:
                    songs = [data[str(track_id)]]
                if not songs:
                    return None
                
                media_url = songs[0].get("media_url", "")
                if media_url:
                    return media_url.replace("_96.", "_320.").replace("_160.", "_320.")
                
                # Try encrypted URL from details as last resort
                enc = songs[0].get("more_info", {}).get("encrypted_media_url", "")
                if enc:
                    return await self._generate_auth_token(enc)
                return None
        except Exception as e:
            logger.error(f"JioSaavn stream error: {e}")
            return None

    async def _generate_auth_token(self, encrypted_url: str) -> Optional[str]:
        """Decode an encrypted JioSaavn stream URL via song.generateAuthToken."""
        import urllib.parse
        try:
            params = {
                "__call": "song.generateAuthToken",
                "url": encrypted_url,
                "bitrate": "320",
                "api_version": "4",
                "_format": "json",
                "ctx": "web6dot0",
                "_marker": "0",
            }
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json, text/plain, */*",
                "Referer": "https://www.jiosaavn.com/",
            }
            async with self.session.get(self.BASE_URL, params=params, headers=headers, timeout=10) as resp:
                import json as _json
                try:
                    data = await resp.json(content_type=None)
                except Exception:
                    text = await resp.text()
                    try:
                        data = _json.loads(text)
                    except Exception:
                        logger.error("JioSaavn generateAuthToken returned non-JSON")
                        return None
                
                auth_url = data.get("auth_url")
                if auth_url:
                    logger.info(f"JioSaavn stream URL decoded via generateAuthToken")
                    return auth_url
                
                logger.warning(f"generateAuthToken response missing auth_url: {data}")
                return None
        except Exception as e:
            logger.error(f"JioSaavn generateAuthToken error: {e}")
            return None


class MusicBackend:
    """
    Unified music backend that tries multiple sources.
    Priority: JioSaavn (legal) → YouTube (fair use) → SoundCloud
    """
    
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
        self.jiosaavn: Optional[JioSaavnExtractor] = None
        self.youtube = None
        self.soundcloud = None
    
    async def init(self):
        """Initialize the shared HTTP session and platform extractors."""
        if not self.session:
            self.session = aiohttp.ClientSession(
                headers={"User-Agent": "Mozilla/5.0 (compatible; SoulKing/1.0; +https://github.com/johan-droid/Music-Bot)"}
            )
            self.jiosaavn = JioSaavnExtractor(self.session)
            
            # YouTube and SoundCloud extractors are already in bot/platforms/
            from bot.platforms.youtube import youtube
            from bot.platforms.soundcloud import soundcloud
            self.youtube = youtube
            self.soundcloud = soundcloud
            logger.info("MusicBackend persistent session initialized")

    async def close(self):
        """Gracefully close the HTTP session."""
        if self.session:
            await self.session.close()
            self.session = None
            logger.info("MusicBackend session closed")
    
    async def search(self, query: str, limit: int = 5) -> List[Track]:
        """
        Search across all sources in parallel.
        Returns unified Track objects.
        """
        if not self.session:
            await self.init()

        # Run all searches in parallel for maximum efficiency
        tasks = [
            self.jiosaavn.search(query, limit),
            self.youtube.search(query, limit),
            self.soundcloud.search(query, limit)
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        tracks = []
        
        # 1. Process JioSaavn results
        if not isinstance(results[0], Exception):
            tracks.extend(results[0])
            logger.info(f"JioSaavn found {len(results[0])} tracks")
            
        # 2. Process YouTube results
        if not isinstance(results[1], Exception):
            yt_results = results[1]
            for result in yt_results:
                track = Track(
                    title=result.get("title", "Unknown"),
                    artist=result.get("uploader", "Unknown"),
                    duration=result.get("duration", 0),
                    stream_url=result.get("url", ""),
                    thumbnail=result.get("thumbnail"),
                    source="youtube",
                    track_id=result.get("id")
                )
                # Avoid duplicates
                if not any(t.title.lower() == track.title.lower() for t in tracks):
                    tracks.append(track)
            logger.info(f"YouTube found {len(yt_results)} tracks")

        # 3. Process SoundCloud results
        if not isinstance(results[2], Exception) and len(tracks) < limit * 2:
            sc_results = results[2]
            for result in sc_results:
                track = Track(
                    title=result.get("title", "Unknown"),
                    artist=result.get("artist", "Unknown"),
                    duration=result.get("duration", 0),
                    stream_url=result.get("stream_url", ""),
                    thumbnail=result.get("thumbnail"),
                    source="soundcloud",
                    track_id=result.get("id")
                )
                if not any(t.title.lower() == track.title.lower() for t in tracks):
                    tracks.append(track)
            logger.info(f"SoundCloud found {len(sc_results)} tracks")
        
        return tracks[:limit]
    
    async def get_stream_url(self, track: Track) -> Optional[str]:
        """Resolve stream URL for a track based on its source."""
        if not self.session:
            await self.init()

        if track.source == "jiosaavn":
            tid = track.track_id or track.get("id")
            # stream_url holds the encrypted_media_url captured during search
            encrypted_url = track.stream_url or ""
            if not tid and not encrypted_url:
                logger.error(f"JioSaavn track missing ID and encrypted URL: {track.title}")
                return None
            return await self.jiosaavn.get_stream_url(tid or "", encrypted_url)
        elif track.source == "youtube":
            tid = track.track_id or track.get("id") or track.stream_url
            result = await self.youtube.extract(tid)
            return result.get("url") if result else None
        elif track.source == "soundcloud":
            return track.stream_url if track.stream_url else None
        return None


# Global instance
music_backend = MusicBackend()
