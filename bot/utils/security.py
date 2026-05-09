import time
import asyncio
import logging
import sqlite3
import re
import os
from functools import wraps
from typing import Optional, Callable
from pyrogram.types import Message
from pyrogram import Client

logger = logging.getLogger(__name__)

try:
    import aiosqlite
    HAS_AIOSQLITE = True
except ImportError:
    HAS_AIOSQLITE = False

# --- 1. Async Permission Middleware Decorator ---
def require_role(min_level: int):
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(client: Client, message: Message, *args, **kwargs):
            user_id = message.from_user.id if message.from_user else None
            chat_id = message.chat.id if message.chat else None

            if not user_id or not chat_id:
                return

            from bot.utils.permissions import get_permission_level

            level = await get_permission_level(user_id, chat_id, check_vc=True)
            if level < min_level:
                await log_audit("PERMISSION_DENIED", user_id, chat_id, f"Attempted to access {func.__name__} with level {level} < {min_level}")
                if min_level >= 3:
                    await message.reply("⛔ You lack the necessary permissions to use this command.")
                return

            return await func(client, message, *args, **kwargs)
        return wrapper
    return decorator

# --- 2. Token-Based Rate Limiter (Sliding Window) ---
class RateLimiter:
    def __init__(self, db_path: str = "./data/ratelimit.db"):
        self.db_path = db_path
        self._init_db_sync()

    def _init_db_sync(self):
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS rate_limits (key TEXT, timestamp REAL)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_rate_limits_key ON rate_limits(key, timestamp)")
            conn.commit()

    async def is_rate_limited(self, key: str, limit: int, window: int) -> bool:
        now = time.time()

        def _db_op():
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cutoff = now - window
                # Atomic-like check and insert via transaction
                with conn:
                    conn.execute("DELETE FROM rate_limits WHERE key = ? AND timestamp < ?", (key, cutoff))
                    row = conn.execute("SELECT COUNT(*) as cnt FROM rate_limits WHERE key = ?", (key,)).fetchone()
                    if row['cnt'] >= limit:
                        return True
                    conn.execute("INSERT INTO rate_limits (key, timestamp) VALUES (?, ?)", (key, now))
                    return False

        if HAS_AIOSQLITE:
            async with aiosqlite.connect(self.db_path) as db:
                cutoff = now - window
                # In aiosqlite, we can execute scripts or multiple statements but let's do it sequentially within a transaction
                await db.execute("BEGIN TRANSACTION")
                await db.execute("DELETE FROM rate_limits WHERE key = ? AND timestamp < ?", (key, cutoff))
                async with db.execute("SELECT COUNT(*) as cnt FROM rate_limits WHERE key = ?", (key,)) as cursor:
                    row = await cursor.fetchone()
                    current_count = row[0] if row else 0

                if current_count >= limit:
                    await db.commit()
                    return True

                await db.execute("INSERT INTO rate_limits (key, timestamp) VALUES (?, ?)", (key, now))
                await db.commit()
                return False
        else:
            return await asyncio.to_thread(_db_op)

rate_limiter = RateLimiter()

def advanced_rate_limit(limit: int = 5, window: int = 60, per_chat: bool = False):
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(client: Client, message: Message, *args, **kwargs):
            user_id = message.from_user.id if message.from_user else None
            chat_id = message.chat.id if message.chat else None

            if not user_id:
                return

            key = f"{chat_id}:{user_id}" if per_chat and chat_id else str(user_id)
            cmd = func.__name__
            limit_key = f"ratelimit:{cmd}:{key}"

            if await rate_limiter.is_rate_limited(limit_key, limit, window):
                logger.warning(f"Rate limit exceeded for {limit_key}")
                await log_audit("RATE_LIMIT", user_id, chat_id, f"Exceeded {limit} reqs / {window}s on {cmd}")
                return

            return await func(client, message, *args, **kwargs)
        return wrapper
    return decorator

# --- 3. Input Sanitization Pipeline ---
class Sanitizer:
    @staticmethod
    def sanitize_search_query(query: str) -> str:
        if not query:
            return ""

        if "http://" in query or "https://" in query:
            sanitized = query.strip()
            match = re.search(r'[;`$|\\]', sanitized)
            if match:
                sanitized = sanitized[:match.start()]
            return sanitized[:256].strip()

        sanitized = re.sub(r'[;&|`$<>\\%]', '', query)
        return sanitized[:256].strip()

    @staticmethod
    def sanitize_path(path: str) -> str:
        if not path:
            return ""
        sanitized = path.replace('../', '').replace('..\\', '')
        sanitized = re.sub(r'[^a-zA-Z0-9\-_./]', '', sanitized)
        return sanitized

def sanitize_input(func: Callable):
    @wraps(func)
    async def wrapper(client: Client, message: Message, *args, **kwargs):
        text = message.text or message.caption
        if text:
            sanitized = Sanitizer.sanitize_search_query(text)
            if message.text:
                message.text = sanitized
            if message.caption:
                message.caption = sanitized

            if hasattr(message, 'command') and message.command:
                message.command = [Sanitizer.sanitize_search_query(c) for c in message.command]

        return await func(client, message, *args, **kwargs)
    return wrapper

# --- 4. Audit Logging System ---
class AuditLogger:
    def __init__(self, db_path: str = "./data/audit.db"):
        self.db_path = db_path
        self._init_db_sync()

    def _init_db_sync(self):
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL,
                    action TEXT,
                    user_id INTEGER,
                    chat_id INTEGER,
                    details TEXT
                )
            """)
            try:
                conn.execute("""
                    CREATE TRIGGER IF NOT EXISTS prevent_audit_update
                    BEFORE UPDATE ON audit_logs
                    BEGIN SELECT RAISE(ABORT, 'Audit logs are append-only'); END;
                """)
                conn.execute("""
                    CREATE TRIGGER IF NOT EXISTS prevent_audit_delete
                    BEFORE DELETE ON audit_logs
                    BEGIN SELECT RAISE(ABORT, 'Audit logs cannot be deleted'); END;
                """)
            except sqlite3.Error:
                pass
            conn.commit()

    async def log(self, action: str, user_id: Optional[int], chat_id: Optional[int], details: str):
        now = time.time()
        def _db_op():
            try:
                with sqlite3.connect(self.db_path) as conn:
                    conn.execute("INSERT INTO audit_logs (timestamp, action, user_id, chat_id, details) VALUES (?, ?, ?, ?, ?)", (now, action, user_id, chat_id, details))
                logger.info(f"AUDIT [{action}]: User {user_id} in Chat {chat_id} - {details}")
            except Exception as e:
                logger.error(f"Failed to write audit log: {e}")

        if HAS_AIOSQLITE:
            try:
                async with aiosqlite.connect(self.db_path) as db:
                    await db.execute("INSERT INTO audit_logs (timestamp, action, user_id, chat_id, details) VALUES (?, ?, ?, ?, ?)", (now, action, user_id, chat_id, details))
                    await db.commit()
                logger.info(f"AUDIT [{action}]: User {user_id} in Chat {chat_id} - {details}")
            except Exception as e:
                logger.error(f"Failed to write audit log: {e}")
        else:
            await asyncio.to_thread(_db_op)

audit_logger = AuditLogger()

async def log_audit(action: str, user_id: Optional[int] = None, chat_id: Optional[int] = None, details: str = ""):
    await audit_logger.log(action, user_id, chat_id, details)

# --- 5. Secret Rotation Workflow ---
class SecretManager:
    def __init__(self):
        self.secrets = {}

    def get_secret(self, key: str, fallback: str = None) -> str:
        return os.environ.get(key) or self.secrets.get(key, fallback)

    async def rotate_secret(self, key: str, new_value: str):
        masked_new = f"{new_value[:4]}...{new_value[-4:]}" if new_value and len(new_value) > 8 else "***"
        self.secrets[key] = new_value
        os.environ[key] = new_value

        from config import config
        if hasattr(config, key):
            setattr(config, key, new_value)

        await log_audit("SECRET_ROTATION", None, None, f"Secret {key} rotated to {masked_new}")

        if key in ("BOT_TOKEN", "API_ID", "API_HASH"):
            logger.info(f"{key} rotated. For a full zero-downtime Pyrogram swap, please implement a dual-client load balancer. Pyrogram doesn't natively support hot-swapping tokens on an active client without dropping handlers or throwing 409 errors.")

        return True

secret_manager = SecretManager()
