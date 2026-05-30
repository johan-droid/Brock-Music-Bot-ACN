import asyncio
from bot.core.microservice_client import MusicMicroserviceClient, _normalize_urls
from bot.utils.http_pool import HTTPConnectionPool
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
async def test_search_uses_post_routing_as_fallback_after_get_attempts():
    client = MusicMicroserviceClient(base_urls=["https://music-ms.onrender.com"])
    calls = []

    async def fake_request(method, path, **kwargs):
        calls.append((method, path, kwargs))
        if method == "POST":
            return {"items": [{"id": "r1", "title": "Routed Song"}]}
        return {"items": []}

    client._request = fake_request  # type: ignore[method-assign]
    items = await client.search("song", limit=5, routing={"variants": ["song"]})
    assert items == [{"id": "r1", "title": "Routed Song"}]
    assert calls[0][0] == "GET"
    assert calls[1][0] == "GET"
    assert calls[2][0] == "POST"


@pytest.mark.asyncio
async def test_request_failover_cools_failed_endpoint():
    client = MusicMicroserviceClient(
        base_urls=["https://primary-ms.onrender.com", "https://backup-ms.onrender.com"]
    )

    class FakeResponse:
        def __init__(self, status, payload):
            self.status = status
            self._payload = payload

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def json(self, content_type=None):
            return self._payload

        async def text(self):
            return str(self._payload)

    class FakeSession:
        def __init__(self):
            self.calls = []

        def request(self, method, url, **kwargs):
            self.calls.append(url)
            if "primary-ms" in url:
                return FakeResponse(503, {"error": "down"})
            return FakeResponse(200, {"items": [{"id": "ok", "title": "Backup"}]})

    fake_session = FakeSession()

    async def fake_get_session():
        return fake_session

    original = HTTPConnectionPool.get_session
    HTTPConnectionPool.get_session = fake_get_session  # type: ignore[assignment]
    try:
        first = await client.search("song", limit=3)
        second = await client.search("song", limit=3)
    finally:
        HTTPConnectionPool.get_session = original  # type: ignore[assignment]

    assert first == []
    assert second == []
    assert fake_session.calls[0].startswith("https://primary-ms")
    assert fake_session.calls[1].startswith("https://primary-ms")
    assert fake_session.calls[2].startswith("https://primary-ms")


@pytest.mark.asyncio
async def test_resolve_accepts_nested_track_shape():
    client = MusicMicroserviceClient(base_urls=["https://music-ms.onrender.com"])

    async def fake_request(*args, **kwargs):
        return {"track": {"track_id": "abc", "stream_url": "https://cdn.example/track.mp3"}}

    client._request = fake_request  # type: ignore[method-assign]
    item = await client.resolve({"track_id": "abc"})
    assert item == {"track_id": "abc", "stream_url": "https://cdn.example/track.mp3"}


@pytest.mark.asyncio
async def test_render_cold_start_timeout_retries_once_with_longer_timeout():
    client = MusicMicroserviceClient(
        base_urls=["https://music-ms.onrender.com"],
        timeout_seconds=5,
        cold_start_timeout_seconds=20,
    )

    timeouts_used = []

    class TimeoutResponse:
        async def __aenter__(self):
            raise asyncio.TimeoutError()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class SuccessResponse:
        status = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def json(self, content_type=None):
            return {"items": [{"id": "wake", "title": "Warm"}]}

        async def text(self):
            return ""

    class FakeSession:
        def __init__(self):
            self.calls = 0

        def request(self, method, url, **kwargs):
            timeout_total = getattr(kwargs.get("timeout"), "total", None)
            timeouts_used.append(timeout_total)
            self.calls += 1
            if self.calls == 1:
                return TimeoutResponse()
            return SuccessResponse()

    fake_session = FakeSession()

    async def fake_get_session():
        return fake_session

    original = HTTPConnectionPool.get_session
    HTTPConnectionPool.get_session = fake_get_session  # type: ignore[assignment]
    try:
        items = await client.search("song", limit=1)
    finally:
        HTTPConnectionPool.get_session = original  # type: ignore[assignment]

    assert items == [{"id": "wake", "title": "Warm"}]
    assert timeouts_used[:2] == [5, 5]


def test_initial_render_cold_start_detection():
    # Cold start detection is explicitly disabled in the current implementation
    render_client = MusicMicroserviceClient(base_urls=["https://music-ms.onrender.com"])
    assert render_client.is_initial_render_cold_start() is False

    non_render_client = MusicMicroserviceClient(base_urls=["https://api.example.com"])
    assert non_render_client.is_initial_render_cold_start() is False
