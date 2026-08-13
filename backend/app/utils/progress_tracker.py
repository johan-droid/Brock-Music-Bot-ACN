"""Tracks real-time playback position per chat using a start timestamp."""

import asyncio
import time
import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class ProgressTracker:
    """Tracks when each chat started playing and cumulative elapsed seconds."""

    def __init__(self):
        # chat_id → unix timestamp when current track started
        self._started_at: Dict[int, float] = {}
        # chat_id → seconds already elapsed before last pause
        self._offset: Dict[int, float] = {}
        # chat_id → True if currently paused
        self._paused: Dict[int, bool] = {}

    def start(self, chat_id: int, seek: int = 0) -> None:
        """Mark a track as started (optionally at a seek position)."""
        self._started_at[chat_id] = time.monotonic()
        self._offset[chat_id] = float(seek)
        self._paused[chat_id] = False

    def pause(self, chat_id: int) -> None:
        """Record current elapsed time so we can resume correctly."""
        self._offset[chat_id] = self.elapsed(chat_id)
        self._paused[chat_id] = True

    def resume(self, chat_id: int) -> None:
        """Reset the start timestamp so elapsed keeps counting from now."""
        self._started_at[chat_id] = time.monotonic()
        self._paused[chat_id] = False

    def seek(self, chat_id: int, position: int) -> None:
        """Jump to a specific position in the track."""
        self._started_at[chat_id] = time.monotonic()
        self._offset[chat_id] = float(position)
        self._paused[chat_id] = False

    def stop(self, chat_id: int) -> None:
        """Clear tracking for a chat."""
        self._started_at.pop(chat_id, None)
        self._offset.pop(chat_id, None)
        self._paused.pop(chat_id, None)

    def elapsed(self, chat_id: int) -> float:
        """Return elapsed seconds, accounting for pauses and seeks."""
        if self._paused.get(chat_id):
            return self._offset.get(chat_id, 0.0)

        started = self._started_at.get(chat_id)
        if started is None:
            return 0.0

        return self._offset.get(chat_id, 0.0) + (time.monotonic() - started)

    def progress_bar(self, chat_id: int, duration: int, width: int = 16) -> str:
        """
        Return a Unicode progress bar string.

        Example: ██████░░░░░░░░░░  2:34 / 4:12
        """
        elapsed = self.elapsed(chat_id)
        if duration <= 0:
            return "⬛" * width + "  LIVE 🔴"

        ratio = min(elapsed / duration, 1.0)
        filled = int(ratio * width)
        bar = "█" * filled + "░" * (width - filled)

        e_min, e_sec = divmod(int(elapsed), 60)
        d_min, d_sec = divmod(int(duration), 60)
        return f"{bar}  {e_min}:{e_sec:02d} / {d_min}:{d_sec:02d}"

    def is_tracking(self, chat_id: int) -> bool:
        """Return True if we have a start record for this chat."""
        return chat_id in self._started_at


# Global singleton
progress_tracker = ProgressTracker()
