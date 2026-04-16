"""Formatting utilities for durations, progress bars, etc."""

import math
from typing import Optional


def format_duration(seconds: int) -> str:
    """Format seconds into human-readable duration.
    
    Args:
        seconds: Duration in seconds
        
    Returns:
        Formatted string like "3:45" or "1:23:45"
    """
    if not seconds or seconds < 0:
        return "0:00"
    
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    else:
        return f"{minutes}:{secs:02d}"


def format_time_simple(seconds: int) -> str:
    """Simple time format."""
    return format_duration(seconds)


def create_progress_bar(current: int, total: int, length: int = 20) -> str:
    """Create a text progress bar.
    
    Args:
        current: Current position
        total: Total duration
        length: Bar length in characters
        
    Returns:
        Progress bar string
    """
    if total <= 0:
        return "─" * length
    
    progress = min(current / total, 1.0)
    filled = int(length * progress)
    
    bar = "●" + "─" * (length - 1)
    if filled > 0:
        bar = "━" * filled + "─" * (length - filled)
    
    return bar


def format_track_info(
    title: str, 
    duration: int, 
    position: int = 0,
    requested_by: Optional[int] = None,
    source: str = "unknown"
) -> str:
    """Format track information for display.
    
    Args:
        title: Track title
        duration: Duration in seconds
        position: Current playback position
        requested_by: User ID who requested
        source: Source platform
        
    Returns:
        Formatted text
    """
    bar = create_progress_bar(position, duration)
    current_str = format_duration(position)
    total_str = format_duration(duration)
    
    source_emoji = {
        "vk": "🟦",
        "deezer": "🎧",
        "telegram": "📎",
    }.get((source or "").lower(), "🎵")
    
    text = f"""
{source_emoji} **{title}**

{bar}
`{current_str}` / `{total_str}`
    """
    
    return text.strip()


def truncate_text(text: str, max_length: int = 60) -> str:
    """Truncate text to max length with ellipsis.
    
    Args:
        text: Input text
        max_length: Maximum length
        
    Returns:
        Truncated text
    """
    if len(text) <= max_length:
        return text
    return text[:max_length - 3] + "..."


def format_queue_list(tracks: list, page: int = 0, per_page: int = 10) -> str:
    """Format queue list for display.
    
    Args:
        tracks: List of track dicts
        page: Current page number (0-indexed)
        per_page: Items per page
        
    Returns:
        Formatted text
    """
    if not tracks:
        return "📭 Queue is empty"
    
    start = page * per_page
    end = start + per_page
    page_tracks = tracks[start:end]
    
    lines = [f"📋 **Queue** ({len(tracks)} songs)", ""]
    
    for i, track in enumerate(page_tracks, start=start + 1):
        title = truncate_text(track.get("title", "Unknown"), 50)
        duration = format_duration(track.get("duration", 0))
        lines.append(f"`{i:2d}.` {title} `({duration})`")
    
    total_duration = sum(t.get("duration", 0) for t in tracks)
    lines.append("")
    lines.append(f"**Total Duration:** {format_duration(total_duration)}")
    
    if len(tracks) > per_page:
        lines.append(f"\nPage {page + 1}/{(len(tracks) - 1) // per_page + 1}")
    
    return "\n".join(lines)


def format_bytes(bytes_count: int) -> str:
    """Format byte count to human readable.
    
    Args:
        bytes_count: Number of bytes
        
    Returns:
        Formatted string like "1.5 MB"
    """
    if bytes_count == 0:
        return "0 B"
    
    units = ["B", "KB", "MB", "GB", "TB"]
    i = int(math.floor(math.log(bytes_count, 1024)))
    p = math.pow(1024, i)
    s = round(bytes_count / p, 2)
    
    return f"{s} {units[i]}"
