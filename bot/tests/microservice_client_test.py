from bot.core.microservice_client import MusicMicroserviceClient, _normalize_urls
import pytest


def test_normalize_urls_dedupes_and_adds_scheme():
    urls = _normalize_urls(
        [
            "music-ms.onrender.com/",
            "https://music-ms.onrender.com",
            "http://backup-ms.local/",
            "  ",
        ]
    )
    assert urls == ["https://music-ms.onrender.com", "http://backup-ms.local"]


def test_authorization_header_format():
    client = MusicMicroserviceClient(
        base_urls=["https://music-ms.onrender.com"],
        token="secret-token",
        token_header="Authorization",
    )
    headers = client._headers()
    assert headers["Authorization"] == "Bearer secret-token"


@pytest.mark.asyncio
async def test_search_accepts_results_shape():
    client = MusicMicroserviceClient(base_urls=["https://music-ms.onrender.com"])

    async def fake_request(*args, **kwargs):
        return {"results": [{"id": "123", "title": "Song"}]}

    client._request = fake_request  # type: ignore[method-assign]
    items = await client.search("song", limit=5)
    assert items == [{"id": "123", "title": "Song"}]


@pytest.mark.asyncio
async def test_resolve_accepts_nested_track_shape():
    client = MusicMicroserviceClient(base_urls=["https://music-ms.onrender.com"])

    async def fake_request(*args, **kwargs):
        return {"track": {"track_id": "abc", "stream_url": "https://cdn.example/track.mp3"}}

    client._request = fake_request  # type: ignore[method-assign]
    item = await client.resolve({"track_id": "abc"})
    assert item == {"track_id": "abc", "stream_url": "https://cdn.example/track.mp3"}
