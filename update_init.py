with open("bot/utils/__init__.py", "r") as f:
    content = f.read()

exports = """
from bot.utils.errors import (
    MusicBotError,
    SourceExhaustedError,
    BotDetectionError,
    GeoRestrictionError,
    PreviewOnlyError,
    CircuitBreakerOpenError,
    FallbackExhaustedError,
    format_error_message,
)
"""

if "from bot.utils.errors import" not in content:
    content = content.replace("from bot.utils.logger import", exports + "from bot.utils.logger import")

    all_exports = """    # Errors
    "MusicBotError",
    "SourceExhaustedError",
    "BotDetectionError",
    "GeoRestrictionError",
    "PreviewOnlyError",
    "CircuitBreakerOpenError",
    "FallbackExhaustedError",
    "format_error_message",
    # Logger"""
    content = content.replace("# Logger", all_exports)

    with open("bot/utils/__init__.py", "w") as f:
        f.write(content)
