from bot.core.microservice_client import MusicMicroserviceClient, _normalize_urls


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
