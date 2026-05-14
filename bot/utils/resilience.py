import asyncio
import logging
import sys
import time
import os
import traceback
from typing import List, Dict, Any

from config import config

logger = logging.getLogger(__name__)

# In-memory storage for the last 10 errors
error_history: List[Dict[str, Any]] = []

def add_to_error_history(exc_type, exc_value, exc_traceback):
    """Add an error to the history, keeping only the last 10."""
    global error_history
    tb_str = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))

    error_record = {
        "time": time.time(),
        "type": getattr(exc_type, "__name__", str(exc_type)),
        "message": str(exc_value),
        "traceback": tb_str
    }

    error_history.append(error_record)
    if len(error_history) > 10:
        error_history.pop(0)

async def notify_owner(message: str):
    """Notify the bot owner via Telegram."""
    if not config.OWNER_ID:
        return

    try:
        from bot.core import bot as bot_module
        if bot_module.bot_client and bot_module.bot_client.is_connected:
            await bot_module.bot_client.send_message(config.OWNER_ID, message)
    except Exception as e:
        logger.error(f"Failed to notify owner: {e}")

class GlobalExceptionHandler:
    """Catches all unhandled exceptions."""

    @staticmethod
    def handle_sys_exception(exc_type, exc_value, exc_traceback):
        """Handle synchronous unhandled exceptions."""
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return

        logger.critical(f"Uncaught synchronous exception: {exc_value}", exc_info=(exc_type, exc_value, exc_traceback))
        add_to_error_history(exc_type, exc_value, exc_traceback)

        # Schedule notification if loop is running
        try:
            loop = asyncio.get_running_loop()
            if not loop.is_closed():
                loop.create_task(notify_owner(f"🚨 **CRITICAL ERROR**\n\n`{exc_type.__name__}: {exc_value}`\n\nCheck logs for details. Bot may restart soon."))
        except RuntimeError:
            pass # No running loop

    @staticmethod
    def handle_asyncio_exception(loop, context):
        """Handle asyncio unhandled exceptions."""
        msg = context.get("exception", context["message"])
        logger.critical(f"Uncaught asyncio exception: {msg}")

        exc = context.get("exception")
        if exc:
            exc_type = type(exc)
            exc_traceback = exc.__traceback__
            add_to_error_history(exc_type, exc, exc_traceback)

            if not loop.is_closed():
                loop.create_task(notify_owner(f"🚨 **ASYNCIO ERROR**\n\n`{exc_type.__name__}: {str(exc)}`\n\nCheck logs for details."))
        else:
            # Just add string message if no actual exception object
            error_record = {
                "time": time.time(),
                "type": "Asyncio Context Error",
                "message": str(msg),
                "traceback": "N/A"
            }
            error_history.append(error_record)
            if len(error_history) > 10:
                error_history.pop(0)

def setup_global_exception_handlers():
    """Install the global exception handlers."""
    sys.excepthook = GlobalExceptionHandler.handle_sys_exception

    try:
        loop = asyncio.get_running_loop()
        loop.set_exception_handler(GlobalExceptionHandler.handle_asyncio_exception)
    except RuntimeError:
        pass # Will be set in main() once loop starts

class Watchdog:
    """Monitors bot health and forces restart if stuck."""

    def __init__(self, timeout_seconds: int = 300):
        self.timeout_seconds = timeout_seconds
        self.last_ping = time.time()
        self._task = None

    def ping(self):
        """Update the last ping time."""
        self.last_ping = time.time()

    async def start(self):
        """Start the watchdog task."""
        if self._task is None:
            self.ping()
            self._task = asyncio.create_task(self._monitor())
            logger.info(f"Watchdog started (timeout: {self.timeout_seconds}s)")

    def stop(self):
        """Stop the watchdog task."""
        if self._task:
            self._task.cancel()
            self._task = None

    async def _monitor(self):
        while True:
            await asyncio.sleep(30)
            now = time.time()
            if now - self.last_ping > self.timeout_seconds:
                logger.critical(f"WATCHDOG TRIGGERED: No response for {self.timeout_seconds}s. Force restarting.")
                # We can't await notify_owner reliably here because we might be totally stuck
                self._force_restart()

    def _force_restart(self):
        """Forcefully restart the bot process."""
        try:
            logger.critical("Execv self...")
            os.execv(sys.executable, ['python', '-m', 'bot'])
        except Exception as e:
            logger.error(f"Failed to execv: {e}")
            os._exit(1)

watchdog = Watchdog()
