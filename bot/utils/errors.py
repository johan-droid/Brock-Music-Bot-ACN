"""Structured error handling for music extraction."""

class MusicBotError(Exception):
    """Base exception for all music bot errors."""
    user_message = "An unexpected error occurred."

class SourceExhaustedError(MusicBotError):
    user_message = "All available music sources failed. Please try again later."

class BotDetectionError(MusicBotError):
    user_message = "Service temporarily unavailable due to bot detection. We are resolving this."

class GeoRestrictionError(MusicBotError):
    user_message = "This track is not available in your region."

class PreviewOnlyError(MusicBotError):
    user_message = "Only a preview is available from this source."

class CircuitBreakerOpenError(MusicBotError):
    user_message = "Service is temporarily overloaded. Please try again in a few minutes."

class FallbackExhaustedError(MusicBotError):
    user_message = "Could not find a working stream for this track across all sources."

def format_error_message(e: Exception) -> str:
    """Map HTTP/API errors to user-friendly messages without stack leakage."""
    if isinstance(e, MusicBotError):
        return e.user_message
    return "An unexpected error occurred while processing your request. Our team has been notified."
