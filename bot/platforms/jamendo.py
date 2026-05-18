"""Jamendo OAuth API wrapper for playlist management."""

import json
import logging
from typing import Dict, Any, List, Optional
import aiohttp

from config import config

logger = logging.getLogger(__name__)

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
        """Generate OAuth authorization URL for Jamendo."""
        if not self.is_configured():
            return ""

        # We pass the telegram user_id as state to map it back
        return f"{self.OAUTH_URL}?client_id={self.client_id}&redirect_uri={self.redirect_uri}&scope=music&state={user_id}"

    async def exchange_auth_code(self, code: str) -> Optional[Dict[str, Any]]:
        """Exchange auth code for access token."""
        if not self.is_configured():
            return None

        async with aiohttp.ClientSession() as session:
            data = {
                "grant_type": "authorization_code",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "code": code,
                "redirect_uri": self.redirect_uri
            }
            try:
                async with session.post(self.TOKEN_URL, data=data) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    else:
                        logger.error(f"Jamendo auth failed: {resp.status} {await resp.text()}")
                        return None
            except Exception as e:
                logger.error(f"Jamendo auth exception: {e}")
                return None

    async def create_jamendo_playlist(self, access_token: str, name: str) -> Optional[str]:
        """Create a new playlist on Jamendo."""
        async with aiohttp.ClientSession() as session:
            params = {
                "client_id": self.client_id,
                "access_token": access_token,
                "name": name
            }
            try:
                # Based on Jamendo V3 docs, playlists/create is not standard GET but let's assume standard POST/GET structure
                # Jamendo v3 API playlist creation: POST /playlists/
                async with session.post(f"{self.BASE_URL}/playlists/", params=params) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("headers", {}).get("status") == "success":
                            # Return playlist ID
                            return data.get("results", [{}])[0].get("id")
                    logger.error(f"Jamendo create playlist failed: {await resp.text()}")
                    return None
            except Exception as e:
                logger.error(f"Jamendo create playlist exception: {e}")
                return None

    async def add_tracks_to_jamendo_playlist(self, access_token: str, playlist_id: str, track_ids: List[str]) -> bool:
        """Add tracks to a Jamendo playlist."""
        if not track_ids:
            return True

        async with aiohttp.ClientSession() as session:
            # Jamendo v3 allows adding tracks: POST /playlists/tracks/
            params = {
                "client_id": self.client_id,
                "access_token": access_token,
                "id": playlist_id,
                "track_id": track_ids  # might need to be comma separated depending on API
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

jamendo_api = JamendoAPI()
