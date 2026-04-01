"""Logging setup with file and Telegram log channel support."""

import logging
import logging.handlers
import os
from datetime import datetime
from config import config
from bot.core import bot as bot_module


class TelegramLogHandler(logging.Handler):
    """Custom handler to send logs to Telegram channel."""
    
    def __init__(self, chat_id: int):
        super().__init__()
        self.chat_id = chat_id
        self._bot = None
    
    def emit(self, record: logging.LogRecord):
        try:
            if not self._bot:
                self._bot = bot_module.bot_client

            if not self._bot and bot_module.bot_client:
                self._bot = bot_module.bot_client
            
            # Only send warnings and above to Telegram
            if record.levelno < logging.WARNING:
                return
            
            # Format message
            msg = self.format(record)
            if len(msg) > 4000:
                msg = msg[:4000] + "..."
            
            # Send async - fire and forget
            if self._bot and self._bot.is_connected:
                import asyncio
                asyncio.create_task(
                    self._bot.send_message(self.chat_id, f"`{msg}`", parse_mode="markdown")
                )
        except Exception:
            pass  # Don't let logging errors crash the bot


def setup_logging():
    """Setup logging configuration."""
    # Create logs directory
    log_dir = "/var/log/musicbot" if os.path.exists("/var/log") else "./logs"
    os.makedirs(log_dir, exist_ok=True)
    
    # Root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    
    # Clear existing handlers
    root_logger.handlers.clear()
    
    # Formatter
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    
    # Console handler
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(formatter)
    root_logger.addHandler(console)
    
    # File handler with rotation
    log_file = os.path.join(log_dir, "bot.log")
    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)
    
    # Error log file
    error_file = os.path.join(log_dir, "error.log")
    error_handler = logging.handlers.RotatingFileHandler(
        error_file,
        maxBytes=10 * 1024 * 1024,
        backupCount=5
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)
    root_logger.addHandler(error_handler)
    
    # Telegram log handler (if configured)
    if config.LOG_GROUP_ID:
        telegram_handler = TelegramLogHandler(config.LOG_GROUP_ID)
        telegram_handler.setLevel(logging.WARNING)
        telegram_handler.setFormatter(formatter)
        root_logger.addHandler(telegram_handler)
    
    # Reduce noise from external libraries
    logging.getLogger("pyrogram").setLevel(logging.WARNING)
    logging.getLogger("pytgcalls").setLevel(logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    
    logging.info("Logging setup complete")
