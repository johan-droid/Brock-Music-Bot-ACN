"""
JioSaavn music extractor for Indian music
Uses the public JioSaavn API (unofficial)
"""

import logging
import aiohttp
from typing import Any, Dict, List, Optional

from bot.utils.circuit_breaker import CircuitBreakerRegistry, CircuitBreakerOpen, retry_with_backoff, source_health_tracker
from bot.utils.errors import PreviewOnlyError

logger = logging.getLogger(__name__)

# JioSaavn API endpoints (unofficial)
JIOSAAVN_BASE = "https://www.jiosaavn.com/api.php"


class JioSaavnExtractor:
    """Extract music from JioSaavn - Best for Indian/Bollywood music"""

    def __init__(self):
        self.enabled = True
        self._circuit_breaker = CircuitBreakerRegistry.get("jiosaavn")
        logger.info("JioSaavn extractor initialized")

    @retry_with_backoff(retries=2, base_delay=1.0, max_delay=5.0)
    async def _make_request(self, params: dict) -> Optional[dict]:
        """Make request to JioSaavn API"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(JIOSAAVN_BASE, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status == 200:
                        await source_health_tracker.record_success("jiosaavn")
                        if self._circuit_breaker:
                            await self._circuit_breaker._record_success()
                        return await resp.json()
                    logger.warning(f"JioSaavn API returned {resp.status}")
                    await source_health_tracker.record_failure("jiosaavn")
                    if self._circuit_breaker:
                        await self._circuit_breaker._record_failure()
        except Exception as e:
            logger.debug(f"JioSaavn API request failed: {e}")
            await source_health_tracker.record_failure("jiosaavn")
            if self._circuit_breaker:
                await self._circuit_breaker._record_failure()
        return None

    async def search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Search tracks on JioSaavn"""
        if self._circuit_breaker and self._circuit_breaker.is_open:
            return []

        params = {
            "__call": "autocomplete.get",
            "query": query,
            "_format": "json",
            "_marker": 0,
            "ctx": "web6dot0"
        }

        try:
            result = await self._make_request(params)
            if not result or "songs" not in result or not result["songs"]:
                return []

            songs = result["songs"]["data"] if isinstance(
                result["songs"], dict) else result["songs"]
            results = []

            for song in songs[:limit]:
                track_id = song.get("id")
                if not track_id:
                    continue

                # JioSaavn search API doesn't return full stream URLs,
                # we just return the basic info and ID for later extraction
                results.append({
                    "id": str(track_id),
                    "title": song.get("title", "Unknown").replace("&quot;", '"'),
                    "artist": song.get("more_info", {}).get("primary_artists", "Unknown Artist"),
                    "duration": 0,  # Autocomplete API rarely gives duration
                    "thumbnail": song.get("image", "").replace("50x50", "150x150"),
                    "url": song.get("url", ""),
                    "source": "jiosaavn"
                })

            return results
        except Exception as e:
            logger.debug(f"JioSaavn search failed: {e}")
            return []

    async def extract(self, track_id: str) -> Optional[Dict[str, Any]]:
        """Get track details and stream URL"""
        if self._circuit_breaker and self._circuit_breaker.is_open:
            return None

        params = {
            "__call": "song.getDetails",
            "pids": track_id,
            "_format": "json",
            "_marker": 0,
            "ctx": "web6dot0"
        }

        try:
            result = await self._make_request(params)
            if not result or "songs" not in result:
                return None

            songs = result["songs"]
            if not songs:
                return None

            song = songs[0]

            # Get highest quality audio URL
            media_url = ""
            
            # PRIORITY: encrypted_media_url (Full quality) > media_preview_url (often preview)
            # Try both top-level and more_info nested location
            encrypted_url = song.get("encrypted_media_url") or song.get("more_info", {}).get("encrypted_media_url")
            if encrypted_url:
                media_url = self._decrypt_media_url(encrypted_url)
                
            if not media_url:
                media_url = song.get("media_preview_url") or song.get("more_info", {}).get("media_preview_url")

            if media_url and ("jiotunepreview" in media_url.lower() or "preview.saavncdn.com" in media_url.lower()):
                logger.warning(
                    f"JioSaavn returned a preview URL for track {track_id}")
                raise PreviewOnlyError("JioSaavn stream is only a preview.")

            return {
                "id": str(track_id),
                "title": song.get("title", "Unknown"),
                "artist": song.get("primary_artists", "Unknown Artist") or song.get("more_info", {}).get("primary_artists", "Unknown Artist"),
                "duration": self._parse_duration(song.get("duration", "0:00")),
                "stream_url": media_url,
                "thumbnail": song.get("image", "").replace("150x150", "500x500"),
                "url": song.get("perma_url", ""),
                "source": "jiosaavn"
            }
        except PreviewOnlyError:
            raise
        except Exception as e:
            logger.debug(f"JioSaavn extract failed: {e}")
            return None

    def _parse_duration(self, duration_str: str) -> int:
        """Convert '3:45' to 225 seconds, or handle pure int seconds"""
        if isinstance(duration_str, int):
            return duration_str

        try:
            # If it's just a number string
            if duration_str.isdigit():
                return int(duration_str)

            parts = duration_str.split(':')
            if len(parts) == 2:
                return int(parts[0]) * 60 + int(parts[1])
            elif len(parts) == 3:
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
            return 0
        except:
            return 0

    def _decrypt_media_url(self, encrypted_url: str) -> str:
        """Decrypt JioSaavn media URL using DES-ECB"""
        if not encrypted_url:
            return ""
        
        try:
            import base64
            from Crypto.Cipher import DES
            
            # Key used by JioSaavn for media URL encryption
            key = b"38346b346c336d31"
            cipher = DES.new(key, DES.MODE_ECB)
            
            # Decode base64 and decrypt
            ciphertext = base64.b64decode(encrypted_url)
            decrypted = cipher.decrypt(ciphertext)
            
            # Remove PKCS7 padding
            padding_len = decrypted[-1]
            if 1 <= padding_len <= 8:
                decrypted = decrypted[:-padding_len]
                
            decoded = decrypted.decode("utf-8")
            
            if not decoded.startswith("http"):
                return ""
                
            # Quality upgrades for high-fidelity audio
            # 320kbps is the maximum supported bitrate
            decoded = decoded.replace("_96.mp4", "_320.mp4")\
                             .replace("_160.mp4", "_320.mp4")\
                             .replace("_96.m4a", "_320.m4a")\
                             .replace("_160.m4a", "_320.m4a")
                             
            # Ensure HTTPS for security and compatibility
            if decoded.startswith("http://"):
                decoded = decoded.replace("http://", "https://")
                
            return decoded
        except Exception as e:
            logger.debug(f"JioSaavn decryption failed: {e}")
            return ""


# Global extractor instance
jiosaavn_extractor = JioSaavnExtractor()
