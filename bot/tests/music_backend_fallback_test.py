import pytest

from bot.core import music_backend as backend_module


@pytest.mark.asyncio
async def test_search_keeps_unsupported_page_urls_for_later_resolution():
    backend = backend_module.MusicBackend()
    tracks = await backend.search("https://www.youtube.com/watch?v=dQw4w9WgXcQ", limit=1)
    assert tracks
    assert tracks[0].source == "unsupported"


@pytest.mark.asyncio
async def test_search_uses_local_fallback_when_microservice_and_index_are_empty(monkeypatch):
    backend = backend_module.MusicBackend()

    async def _empty_service(query: str, limit: int):
        return []

    async def _empty_index(query: str, limit: int):
        return []

    async def _fallback(query: str, limit: int):
        return [
            backend_module.Track(
                title="Fallback Song",
                artist="Fallback Artist",
                duration=180,
                stream_url="https://audio.example/fallback.mp3",
                source="youtube",
                track_id="fallback-1",
            )
        ]

    class _FakeCache:
        async def get(self, key):
            return None, False

        async def set(self, key, value, ttl=600):
            return True

    monkeypatch.setattr(backend, "_search_microservice", _empty_service)
    monkeypatch.setattr(backend, "_search_index", _empty_index)
    monkeypatch.setattr(backend, "_search_local_fallback", _fallback)
    monkeypatch.setattr(backend_module, "_get_multi_cache", lambda: _FakeCache())

    tracks = await backend.search("fallback unique query", limit=1)
    assert tracks
    assert tracks[0].title == "Fallback Song"
    assert tracks[0].source == "youtube"


@pytest.mark.asyncio
async def test_get_stream_payload_uses_local_resolver_for_unsupported_urls(monkeypatch):
    backend = backend_module.MusicBackend()

    async def _resolve_url(url: str, source: str = "external"):
        return {
            "title": "Resolved Song",
            "artist": "Resolved Artist",
            "duration": 120,
            "stream_url": "https://cdn.example/resolved.mp3",
            "url": "https://cdn.example/resolved.mp3",
            "thumbnail": "https://cdn.example/cover.jpg",
            "track_id": "resolved-1",
            "id": "resolved-1",
            "source": source,
        }

    monkeypatch.setattr(backend_module, "resolve_fallback_url", _resolve_url)

    payload = await backend.get_stream_payload(
        backend_module.Track(
            title="Some Song",
            artist="Some Artist",
            duration=0,
            stream_url="https://youtube.com/watch?v=abc123",
            source="unsupported",
            track_id="abc123",
        )
    )

    assert payload is not None
    assert payload.get("url") == "https://cdn.example/resolved.mp3"
