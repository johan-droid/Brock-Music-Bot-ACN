"""Temp file cleanup scheduler."""

import logging
import os
import asyncio
from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

# Directories to clean
CLEANUP_DIRS = [
    "/tmp/musicbot",
    "./downloads",
    "./temp",
]

# Max age for temp files (24 hours)
MAX_AGE_HOURS = 24


class CleanupScheduler:
    """Manages scheduled cleanup tasks."""
    
    def __init__(self):
        self.scheduler = AsyncIOScheduler()
    
    def start(self):
        """Start the scheduler."""
        # Schedule temp file cleanup every hour
        self.scheduler.add_job(
            self.cleanup_temp_files,
            trigger=IntervalTrigger(hours=1),
            id="temp_cleanup",
            replace_existing=True,
        )
        
        self.scheduler.start()
        logger.info("Cleanup scheduler started")
    
    def stop(self):
        """Stop the scheduler."""
        self.scheduler.shutdown()
        logger.info("Cleanup scheduler stopped")
    
    async def cleanup_temp_files(self):
        """Clean up old temporary files."""
        logger.info("Running temp file cleanup...")
        
        cutoff_time = datetime.now() - timedelta(hours=MAX_AGE_HOURS)
        total_removed = 0
        
        for directory in CLEANUP_DIRS:
            if not os.path.exists(directory):
                continue
            
            try:
                for filename in os.listdir(directory):
                    filepath = os.path.join(directory, filename)
                    
                    try:
                        # Check if file is old enough
                        stat = os.stat(filepath)
                        mtime = datetime.fromtimestamp(stat.st_mtime)
                        
                        if mtime < cutoff_time:
                            os.remove(filepath)
                            total_removed += 1
                            logger.debug(f"Removed old file: {filepath}")
                            
                    except Exception as e:
                        logger.warning(f"Failed to remove {filepath}: {e}")
                        
            except Exception as e:
                logger.error(f"Error cleaning directory {directory}: {e}")
        
        if total_removed > 0:
            logger.info(f"Cleanup complete: removed {total_removed} old files")


# Global scheduler instance
cleanup_scheduler = CleanupScheduler()


def start_scheduler():
    """Start the cleanup scheduler."""
    cleanup_scheduler.start()


def stop_scheduler():
    """Stop the cleanup scheduler."""
    cleanup_scheduler.stop()
