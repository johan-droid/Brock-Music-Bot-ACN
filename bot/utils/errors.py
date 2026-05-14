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


def summarize_exception(e: Exception) -> str:
    """Provide a concise, one-line summary of an exception for cleaner logging."""
    if not e:
        return "Unknown Error"
    
    exc_type = type(e).__name__
    exc_msg = str(e).strip()
    
    # Handle common nested or long messages
    if "STREAM_VALIDATION_FAILED" in exc_msg:
        return "Stream Validation Failed (IP Block or Geo-Restriction)"
    if "TimeoutError" in exc_type or "timeout" in exc_msg.lower():
        return f"Service Timeout ({exc_type})"
    if "403" in exc_msg:
        return "Access Forbidden (403) - Bot Detection likely"
    if "503" in exc_msg:
        return "Service Unavailable (503) - Render/Heroku cold start or down"
    
    # Truncate long messages
    if len(exc_msg) > 100:
        exc_msg = exc_msg[:97] + "..."
        
    return f"{exc_type}: {exc_msg}"
