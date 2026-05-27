"""Robust time management system for the music bot.

Handles:
- Sleep timers for chats
- Inactivity auto-leave logic
- Scheduled maintenance windows
- Periodic queue cleanup
"""

import asyncio
import logging
import re
from datetime import datetime, timedelta
from typing import Dict, Optional, Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from bot.core.queue import queue_manager
from bot.core import call
from bot.utils.cache import cache

logger = logging.getLogger(__name__)


class TimeManager:
    """Manages all time-related tasks and scheduling."""

    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        # chat_id -> job_id for sleep timers
        self._sleep_timers: Dict[int, str] = {}
        # chat_id -> last_activity timestamp
        self._inactivity_check: Dict[int, datetime] = {}
        
        self.inactivity_timeout = 300  # 5 minutes default

    def start(self):
        """Initialize and start the scheduler."""
        if not self.scheduler.running:
            # Schedule radio show monitor
            self.scheduler.add_job(
                self.monitor_radio_shows,
                trigger=IntervalTrigger(minutes=1),
                id="radio_show_monitor",
                replace_existing=True
            )

            # Schedule inactivity monitor
            self.scheduler.add_job(
                self.monitor_inactivity,
                trigger=IntervalTrigger(minutes=1),
                id="inactivity_monitor",
                replace_existing=True
            )
            
            # Schedule daily queue cleanup at 4 AM
            self.scheduler.add_job(
                self.scheduled_queue_clear,
                trigger=IntervalTrigger(hours=24),
                id="daily_queue_clear",
                replace_existing=True
            )
            
            self.scheduler.start()
            logger.info("TimeManager scheduler started")

    def stop(self):
        """Shutdown the scheduler."""
        if self.scheduler.running:
            self.scheduler.shutdown()
            logger.info("TimeManager scheduler stopped")

    def _parse_duration(self, duration_str: str) -> Optional[int]:
        """Parse duration string (e.g. 10m, 1h, 30s) to seconds."""
        match = re.match(r'^(\d+)([smh])$', duration_str.lower())
        if not match:
            return None
        
        value, unit = match.groups()
        value = int(value)
        
        if unit == 's':
            return value
        elif unit == 'm':
            return value * 60
        elif unit == 'h':
            return value * 3600
        return None

    async def set_sleep_timer(self, chat_id: int, duration_str: str) -> Optional[int]:
        """Set a sleep timer for a chat."""
        seconds = self._parse_duration(duration_str)
        if not seconds:
            return None

        # Cancel existing timer if any
        self.cancel_sleep_timer(chat_id)

        run_at = datetime.now() + timedelta(seconds=seconds)
        job_id = f"sleep_{chat_id}"
        
        self.scheduler.add_job(
            self._trigger_sleep,
            trigger=DateTrigger(run_date=run_at),
            args=[chat_id],
            id=job_id,
            replace_existing=True
        )
        
        self._sleep_timers[chat_id] = job_id
        logger.info(f"Sleep timer set for chat {chat_id} in {duration_str} ({seconds}s)")
        return seconds

    def cancel_sleep_timer(self, chat_id: int) -> bool:
        """Cancel an active sleep timer."""
        job_id = self._sleep_timers.pop(chat_id, None)
        if job_id:
            try:
                self.scheduler.remove_job(job_id)
                return True
            except Exception:
                pass
        return False

    def get_sleep_timer(self, chat_id: int) -> Optional[datetime]:
        """Get the scheduled time for a sleep timer."""
        job_id = self._sleep_timers.get(chat_id)
        if job_id:
            job = self.scheduler.get_job(job_id)
            if job:
                return job.next_run_time
        return None

    async def _trigger_sleep(self, chat_id: int):
        """Callback when sleep timer fires."""
        self._sleep_timers.pop(chat_id, None)
        logger.info(f"Sleep timer triggered for chat {chat_id}")
        
        from bot.plugins.play import cleanup_vc_session
        from bot.core import bot as bot_module
        from pyrogram.enums import ParseMode

        try:
            # Stop playback and cleanup
            await cleanup_vc_session(chat_id, send_message=False)
            
            # Notify the chat
            if bot_module.bot_client:
                await bot_module.bot_client.send_message(
                    chat_id,
                    "💤 **Yohohoho! The Soul King is taking a nap!**\n"
                    "Sleep timer reached. See you in my dreams (if I had eyes to sleep with)! 💀🎸",
                    parse_mode=ParseMode.MARKDOWN
                )
        except Exception as e:
            logger.error(f"Failed to execute sleep timer for {chat_id}: {e}")

    async def monitor_inactivity(self):
        """Check for inactive VCs and leave them."""
        if not call.call_manager:
            return
        active_chats = list(call.call_manager.active_chats.keys())
        
        for chat_id in active_chats:
            try:
                status = call.call_manager.active_chats.get(chat_id, "idle")
                
                # Check participant count if possible
                participants = await call.call_manager.get_participant_count(chat_id)
                
                # If only the bot is left or idle for too long
                if participants <= 1 or status == "idle":
                    last_active = self._inactivity_check.get(chat_id)
                    if not last_active:
                        self._inactivity_check[chat_id] = datetime.now()
                        continue
                    
                    if (datetime.now() - last_active).total_seconds() > self.inactivity_timeout:
                        logger.info(f"Inactivity timeout for chat {chat_id}, leaving...")
                        from bot.plugins.play import cleanup_vc_session
                        await cleanup_vc_session(chat_id, send_message=True)
                        self._inactivity_check.pop(chat_id, None)
                else:
                    # Reset inactivity timer if active
                    self._inactivity_check[chat_id] = datetime.now()
                    
            except Exception as e:
                logger.debug(f"Inactivity monitor error for {chat_id}: {e}")

    async def scheduled_queue_clear(self):
        """Periodically clear all queues to save memory/DB space."""
        logger.info("Running scheduled global queue cleanup...")
        # This is a maintenance task
        # We could clear all 'idle' chats' queues
        pass


    async def monitor_radio_shows(self):
        """Check for scheduled radio shows."""
        from bot.utils.database import db
        from bot.core.music_backend import music_backend
        from bot.core import bot as bot_module

        now = datetime.now()
        day = now.weekday()
        time_str = now.strftime("%H:%M")

        try:
            shows = await db.get_shows_by_time(day, time_str)
            for show in shows:
                chat_id = show.get("chat_id")
                show_id = show.get("id", show.get("show_id"))

                # Deactivate the show since it's starting
                await db.set_show_inactive(show_id)

                # Get tracks
                tracks = await db.get_show_tracks(show_id)
                if not tracks:
                    continue

                # Announce
                if bot_module.bot_client:
                    await bot_module.bot_client.send_message(
                        chat_id,
                        f"📢 @everyone 📻 **{show.get('show_name')}** is starting now!\n"
                        f"Hosted by: [Host](tg://user?id={show.get('host_user_id')})\n"
                        f"Lineup: {len(tracks)} tracks. Tuning in..."
                    )

                from bot.core.queue import queue_manager
                from bot.core import call

                added_count = 0
                for t in tracks:
                    track_ref = t.get("jamendo_track_id")
                    results = await music_backend.search(str(track_ref), limit=1)
                    if results:
                        track = results[0]
                        track_dict = track.to_dict()
                        track_dict["requested_by"] = show.get("host_user_id")
                        await queue_manager.add_to_queue(
                            chat_id=chat_id,
                            title=track_dict.get("title", "Unknown"),
                            url=track_dict.get("url") or track_dict.get("stream_url") or "",
                            duration=track_dict.get("duration", 0),
                            thumb=track_dict.get("thumbnail") or track_dict.get("thumb"),
                            requested_by=show.get("host_user_id"),
                            source=track_dict.get("source", "unknown"),
                            track_id=track_dict.get("id") or track_dict.get("track_id"),
                            uploader=track_dict.get("uploader") or track_dict.get("artist"),
                        )
                        added_count += 1

                if added_count > 0 and call.call_manager:
                    status = await queue_manager.get_status(chat_id)
                    if status != "playing":
                        next_track = await queue_manager.get_next(chat_id)
                        if next_track:
                            await queue_manager.set_status(chat_id, "playing")
                            try:
                                await call.call_manager.play(
                                    chat_id=chat_id,
                                    stream_url=next_track.get("url") or next_track.get("stream_url"),
                                    video=next_track.get("video", False),
                                    source=next_track.get("source", "unknown"),
                                )
                            except Exception as e:
                                await queue_manager.set_status(chat_id, "idle")
                                logger.error(f"Failed to play radio show: {e}")

        except Exception as e:
            logger.error(f"Error in monitor_radio_shows: {e}")

# Global instance
time_manager = TimeManager()
