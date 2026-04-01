"""Redis-backed queue manager for per-chat song queues - now with SQLite fallback."""

import json
import logging
from typing import List, Optional, Dict, Any
from bot.utils.cache import cache

logger = logging.getLogger(__name__)

# Global queue manager instance
queue_manager = None


class QueueManager:
    """Manages per-chat song queues using cache (Redis or SQLite)."""
    
    def __init__(self):
        pass
        
    async def init(self):
        """Initialize queue manager."""
        pass  # Cache is already initialized
    
    def _queue_key(self, chat_id: int) -> str:
        """Cache key for queue list."""
        return f"vc:queue:{chat_id}"
    
    def _playing_key(self, chat_id: int) -> str:
        """Cache key for currently playing track."""
        return f"vc:playing:{chat_id}"
    
    def _status_key(self, chat_id: int) -> str:
        """Cache key for player status."""
        return f"vc:status:{chat_id}"

    def _history_key(self, chat_id: int) -> str:
        """Cache key for track history (previous tracks)."""
        return f"vc:history:{chat_id}"
    
    async def get_queue(self, chat_id: int) -> List[Dict[str, Any]]:
        """Get the full queue for a chat."""
        key = self._queue_key(chat_id)
        data = await cache.lrange(key, 0, -1)
        return [json.loads(item) for item in data]
    
    async def add_to_queue(
        self, 
        chat_id: int, 
        title: str, 
        url: str, 
        duration: int,
        thumb: Optional[str] = None,
        requested_by: Optional[int] = None,
        source: str = "youtube",
        track_id: Optional[str] = None,
        uploader: Optional[str] = None
    ) -> int:
        """Add a song to the queue.
        
        Returns:
            Position in queue (1 = now playing)
        """
        track = {
            "title": title,
            "url": url,
            "duration": duration,
            "thumb": thumb,
            "requested_by": requested_by,
            "source": source,
            "id": track_id,
            "uploader": uploader,
        }
        
        key = self._queue_key(chat_id)
        await cache.rpush(key, json.dumps(track))
        
        queue_len = await cache.llen(key)
        logger.info(f"Added track to queue for chat {chat_id}: {title} (pos: {queue_len})")
        
        return queue_len

    async def add_to_front(
        self,
        chat_id: int,
        title: str,
        url: str,
        duration: int,
        thumb: Optional[str] = None,
        requested_by: Optional[int] = None,
        source: str = "youtube",
        track_id: Optional[str] = None,
        uploader: Optional[str] = None,
    ) -> int:
        """Add a song to the front of queue so it plays next immediately."""
        track = {
            "title": title,
            "url": url,
            "duration": duration,
            "thumb": thumb,
            "requested_by": requested_by,
            "source": source,
            "id": track_id,
            "uploader": uploader,
        }

        key = self._queue_key(chat_id)
        await cache.lpush(key, json.dumps(track))
        logger.info(f"Added track to FRONT of queue for chat {chat_id}: {title}")
        return 1
    
    async def get_next(self, chat_id: int) -> Optional[Dict[str, Any]]:
        """Get and remove the next song from queue."""
        key = self._queue_key(chat_id)
        data = await cache.lpop(key)
        
        # Save previous track for /previous support
        current = await self.get_current(chat_id)
        if current:
            history_key = self._history_key(chat_id)
            # lpush ensures most recent previous is first
            await cache.lpush(history_key, json.dumps(current))
            # Keep history length bounded for memory (20 tracks)
            await cache.ltrim(history_key, 0, 19)

        if data:
            track = json.loads(data)
            # Store as currently playing
            playing_key = self._playing_key(chat_id)
            track["position"] = 0  # Reset position
            await cache.set(playing_key, json.dumps(track))
            return track
        return None
    
    async def get_current(self, chat_id: int) -> Optional[Dict[str, Any]]:
        """Get currently playing track."""
        key = self._playing_key(chat_id)
        data = await cache.get(key)
        if data:
            return json.loads(data)
        return None
    
    async def clear_queue(self, chat_id: int):
        """Clear the entire queue for a chat."""
        key = self._queue_key(chat_id)
        await cache.delete(key)

        play_key = self._playing_key(chat_id)
        await cache.delete(play_key)

        history_key = self._history_key(chat_id)
        await cache.delete(history_key)
        
        # Reset status
        await self.set_status(chat_id, "idle")
        
        logger.info(f"Cleared queue for chat {chat_id}")
    
    async def remove_at(self, chat_id: int, position: int) -> Optional[Dict[str, Any]]:
        """Remove a song at specific position (1-indexed, skipping current)."""
        # position 1 = first in queue (index 0 in cache)
        key = self._queue_key(chat_id)
        
        # Get the item at position-1 (0-indexed)
        data = await cache.lindex(key, position - 1)
        if data:
            # Remove it - for SQLite we need to rebuild the list
            # Get all, modify, set back
            queue = await self.get_queue(chat_id)
            if 0 <= position - 1 < len(queue):
                removed = queue.pop(position - 1)
                # Clear and re-add
                await cache.delete(key)
                for track in queue:
                    await cache.rpush(key, json.dumps(track))
                return removed
        return None
    
    async def shuffle(self, chat_id: int):
        """Shuffle the queue randomly."""
        import random
        
        key = self._queue_key(chat_id)
        queue = await self.get_queue(chat_id)
        
        if len(queue) > 1:
            random.shuffle(queue)
            # Clear and re-add
            await cache.delete(key)
            for track in queue:
                await cache.rpush(key, json.dumps(track))
            logger.info(f"Shuffled queue for chat {chat_id}")
    
    async def move(self, chat_id: int, from_pos: int, to_pos: int):
        """Move a song from one position to another."""
        key = self._queue_key(chat_id)
        queue = await self.get_queue(chat_id)
        
        if 1 <= from_pos <= len(queue) and 1 <= to_pos <= len(queue):
            track = queue.pop(from_pos - 1)
            queue.insert(to_pos - 1, track)
            
            # Clear and re-add
            await cache.delete(key)
            for t in queue:
                await cache.rpush(key, json.dumps(t))
    
    async def get_queue_length(self, chat_id: int) -> int:
        """Get number of songs in queue."""
        key = self._queue_key(chat_id)
        return await cache.llen(key)
    
    async def set_status(self, chat_id: int, status: str):
        """Set player status: idle, playing, paused."""
        key = self._status_key(chat_id)
        await cache.set(key, status)
    
    async def get_status(self, chat_id: int) -> str:
        """Get player status."""
        key = self._status_key(chat_id)
        status = await cache.get(key)
        return status or "idle"
    
    async def update_position(self, chat_id: int, position: int):
        """Update current playback position."""
        key = self._playing_key(chat_id)
        data = await cache.get(key)
        if data:
            track = json.loads(data)
            track["position"] = position
            await cache.set(key, json.dumps(track))
    
    async def get_position(self, chat_id: int) -> int:
        """Get current playback position."""
        key = self._playing_key(chat_id)
        data = await cache.get(key)
        if data:
            track = json.loads(data)
            return track.get("position", 0)
        return 0

    async def get_previous(self, chat_id: int) -> Optional[Dict[str, Any]]:
        """Get last played track and set it as current."""
        history_key = self._history_key(chat_id)
        data = await cache.lpop(history_key)
        if not data:
            return None

        prev = json.loads(data)
        # preserve old now playing into queue front
        current = await self.get_current(chat_id)
        if current:
            await self.add_to_front(
                chat_id,
                title=current.get("title", "Unknown"),
                url=current.get("url", ""),
                duration=current.get("duration", 0),
                thumb=current.get("thumb"),
                requested_by=current.get("requested_by"),
                source=current.get("source", "youtube"),
                track_id=current.get("id"),
                uploader=current.get("uploader"),
            )

        # Set previous as now playing
        prev["position"] = 0
        await cache.set(self._playing_key(chat_id), json.dumps(prev))
        return prev


async def init_queue_manager():
    """Initialize the global queue manager."""
    global queue_manager
    queue_manager = QueueManager()
    await queue_manager.init()
