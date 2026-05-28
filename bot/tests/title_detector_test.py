from bot.utils.title_detector import build_title_routing_hints, get_provider_priority_for_query


def test_default_provider_priority_prefers_youtube_then_soundcloud_then_apple_music():
    priority, scores = get_provider_priority_for_query("some random song")
    assert priority[:3] == ["youtube", "soundcloud", "apple_music"]
    assert scores["youtube"] > scores["soundcloud"] > scores["apple_music"]


def test_soundcloud_keyword_boosts_soundcloud_priority():
    priority, scores = get_provider_priority_for_query("soundcloud exclusive remix")
    assert priority[0] == "soundcloud"
    assert scores["soundcloud"] > scores["youtube"]


def test_routing_hints_include_provider_priority_contract():
    hints = build_title_routing_hints("official music video test", limit=5)
    assert hints["provider_priority"][:3] == ["youtube", "soundcloud", "apple_music"]
    assert hints["primary_provider"] == "youtube"
    assert "provider_scores" in hints
