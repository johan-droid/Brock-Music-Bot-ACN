import os
import pytest
from bot.platforms.jamendo_client import JamendoClient

@pytest.fixture
def mock_env(monkeypatch):
    monkeypatch.setenv("TEST_MODE", "1")
    monkeypatch.setenv("JAMENDO_CLIENT_ID", "dummy_client_id")

@pytest.mark.asyncio
async def test_search_tracks_test_mode(mock_env):
    client = JamendoClient()
    results = await client.search_tracks("some query", limit=2)

    assert len(results) == 2
    assert results[0]["id"] == 1
    assert results[0]["title"] == "Mock Track 1"
    assert results[0]["artist"] == "Mock Artist"
    assert results[0]["audio_url"] == "https://example.com/mock_audio.mp3"
    assert results[0]["thumbnail_url"] == "https://example.com/mock_thumbnail.jpg"
    assert results[0]["duration"] == 180

@pytest.mark.asyncio
async def test_get_track_by_id_test_mode(mock_env):
    client = JamendoClient()
    result = await client.get_track_by_id(999)

    assert result is not None
    assert result["id"] == 999
    assert result["title"] == "Mock Track 999"
    assert result["artist"] == "Mock Artist"
    assert result["duration"] == 180
