import pytest
from unittest.mock import AsyncMock, patch

from bot.platforms.jamendo import JamendoClient as JamendoAPI

@pytest.mark.asyncio
async def test_jamendo_api_generate_oauth_url():
    with patch('bot.platforms.jamendo.config') as mock_config:
        mock_config.JAMENDO_CLIENT_ID = "test_client_id"
        mock_config.JAMENDO_CLIENT_SECRET = "test_client_secret"
        mock_config.JAMENDO_REDIRECT_URI = "http://localhost:8000/callback"

        api = JamendoAPI()
        # Override to ensure the mock values are picked up
        api.client_id = "test_client_id"
        api.client_secret = "test_client_secret"
        api.redirect_uri = "http://localhost:8000/callback"

        url = api.generate_oauth_url(12345)
        assert "client_id=test_client_id" in url
        assert "state=12345" in url

@pytest.mark.asyncio
async def test_jamendo_api_unconfigured():
    api = JamendoAPI()
    api.client_id = None
    api.client_secret = None

    assert api.is_configured() is False
    assert api.generate_oauth_url(123) == ""
