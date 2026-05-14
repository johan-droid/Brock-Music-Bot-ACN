import asyncio
import time
import json
import logging
import random
import sys
import os
import aiohttp
from typing import Callable, Any, Dict, List
from functools import wraps

logger = logging.getLogger(__name__)

# Structured JSON logging setup will be injected into logging_config or handled here
class JsonFormatter(logging.Formatter):
    def format(self, record):
        log_record = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "message": record.getMessage(),
            "module": record.module,
            "funcName": record.funcName
        }
        if record.exc_info:
            log_record["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_record)

def setup_json_logging():
    root_logger = logging.getLogger()
    for handler in root_logger.handlers:
        handler.setFormatter(JsonFormatter())

# Global error tracking
LAST_ERRORS: List[Dict[str, Any]] = []

def log_error(msg: str, exc: Exception = None):
    error_entry = {
        "time": time.time(),
        "message": msg,
        "exception": str(exc) if exc else None
    }
    LAST_ERRORS.append(error_entry)
    if len(LAST_ERRORS) > 10:
        LAST_ERRORS.pop(0)
    logger.error(msg, exc_info=exc)

class CircuitBreaker:
    def __init__(self, name: str, threshold: int = 5, recovery_time: int = 30):
        self.name = name
        self.threshold = threshold
        self.recovery_time = recovery_time
        self.failures = 0
        self.last_failure = 0
        self.state = "CLOSED" # CLOSED, OPEN, HALF_OPEN

    def record_failure(self):
        self.failures += 1
        self.last_failure = time.time()
        if self.failures >= self.threshold:
            self.state = "OPEN"
            logger.warning(f"Circuit {self.name} OPENED")

    def record_success(self):
        self.failures = 0
        if self.state != "CLOSED":
            self.state = "CLOSED"
            logger.info(f"Circuit {self.name} CLOSED (Recovered)")

    def can_proceed(self) -> bool:
        if self.state == "CLOSED":
            return True
        if time.time() - self.last_failure >= self.recovery_time:
            self.state = "HALF_OPEN"
            return True
        return False

# Global circuit breakers
jamendo_cb = CircuitBreaker("Jamendo")

class RateLimitAware:
    @staticmethod
    async def call_telegram(func, *args, **kwargs):
        from pyrogram.errors import FloodWait
        try:
            return await func(*args, **kwargs)
        except FloodWait as e:
            logger.warning(f"Telegram FloodWait: waiting {e.value} seconds")
            await asyncio.sleep(e.value)
            return await func(*args, **kwargs)

def with_retries_and_cb(circuit_breaker: CircuitBreaker, max_retries: int = 5, timeout: int = 8):
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            if not circuit_breaker.can_proceed():
                logger.warning(f"Circuit {circuit_breaker.name} is OPEN, using degraded mode/cache")
                raise Exception(f"Circuit {circuit_breaker.name} OPEN")

            for attempt in range(max_retries):
                try:
                    # Apply timeout
                    result = await asyncio.wait_for(func(*args, **kwargs), timeout=timeout)
                    circuit_breaker.record_success()
                    return result
                except asyncio.TimeoutError:
                    log_error(f"Timeout calling {func.__name__} (attempt {attempt+1})")
                    circuit_breaker.record_failure()
                except Exception as e:
                    # Check if 429
                    if hasattr(e, 'status') and e.status == 429:
                        retry_after = int(e.headers.get("Retry-After", 5))
                        logger.warning(f"Rate limited. Waiting {retry_after}s")
                        await asyncio.sleep(retry_after)
                        continue

                    log_error(f"Error calling {func.__name__} (attempt {attempt+1})", e)
                    circuit_breaker.record_failure()

                if attempt < max_retries - 1:
                    delay = min(2 ** attempt + random.uniform(0, 1), 10)
                    await asyncio.sleep(delay)

            raise Exception(f"Max retries exceeded for {func.__name__}")
        return wrapper
    return decorator

class Watchdog:
    def __init__(self, timeout: int = 300):
        self.timeout = timeout
        self.last_ping = time.time()
        self._task = None

    def ping(self):
        self.last_ping = time.time()

    async def _loop(self):
        while True:
            await asyncio.sleep(60)
            if time.time() - self.last_ping > self.timeout:
                logger.error(f"Watchdog triggered! Process hung for {self.timeout}s. Exiting for Heroku restart.")
                os._exit(1)

    def start(self):
        self._task = asyncio.create_task(self._loop())

global_watchdog = Watchdog()

async def notify_owner(msg: str):
    from config import config
    from bot.core.bot import bot_client
    if config.OWNER_ID and bot_client:
        try:
            await RateLimitAware.call_telegram(bot_client.send_message, chat_id=config.OWNER_ID, text=msg)
        except Exception as e:
            logger.error(f"Failed to notify owner: {e}")
