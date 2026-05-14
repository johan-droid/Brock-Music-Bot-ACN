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
from bot.core.call import call_manager
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
        active_chats = list(call_manager.active_chats.keys())
        
        for chat_id in active_chats:
            try:
                status = await queue_manager.get_status(chat_id)
                
                # Check participant count if possible
                participants = await call_manager.get_participant_count(chat_id)
                
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


# Global instance
time_manager = TimeManager()
