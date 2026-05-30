import pytest
from bot.core.call import validate_stream_url
import os

def test_validate_stream_url_safe_local():
    assert validate_stream_url("/tmp/musicbot/test.mp3", "song_hunter") == False # Will be false if file doesn't exist
    assert validate_stream_url("data/hunter_cache/test.mp3", "telegram") == False

def test_validate_stream_url_unsafe_local():
    assert validate_stream_url("/etc/passwd", "song_hunter") == False
    assert validate_stream_url("/root/.ssh/id_rsa", "telegram") == False

def test_validate_stream_url_remote():
    assert validate_stream_url("https://example.com/stream.mp3", "auto") == True
    assert validate_stream_url("http://example.com/stream.mp3", "auto") == True

def test_validate_stream_url_blocked_remote():
    assert validate_stream_url("http://169.254.169.254/latest/meta-data/", "auto") == False
    assert validate_stream_url("file:///etc/passwd", "auto") == False
    assert validate_stream_url("http://127.0.0.1/test", "auto") == False
