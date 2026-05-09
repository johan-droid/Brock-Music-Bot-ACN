# Music Bot Admin System - Technical Documentation

## 📋 Overview

The Music Bot Admin System provides comprehensive administrative controls for Telegram group management, user permissions, bot configuration, and system monitoring.

## 🏗️ Architecture

### Core Components

- **Permission System** - Role-based access control
- **Admin Commands** - Administrative bot functions
- **User Management** - Member tracking and control
- **Group Management** - Chat settings and controls
- **Analytics System** - Usage statistics and metrics
- **Moderation Tools** - Content and behavior control
- **Configuration Manager** - Dynamic bot settings

### Dependencies

```python
# Core Admin
pyrogram>=2.0.106
python-dotenv>=1.0.0
asyncio
logging
json
datetime

# Database & Analytics
sqlite3 (built-in)
redis (optional for distributed analytics)

# Utilities
collections
typing
pathlib
```

## 👑 Permission System

### Role Hierarchy

```python
class UserRole(Enum):
    OWNER = "owner"        # Bot owner - full access
    ADMIN = "admin"        # Group admin - elevated access
    MODERATOR = "mod"     # Group moderator - limited admin
    VIP = "vip"           # Premium user - special features
    MEMBER = "member"      # Regular user - basic access
    RESTRICTED = "restricted"  # Restricted user - limited access
    BANNED = "banned"      # Banned user - no access
```

### Permission Matrix

| Permission | Owner | Admin | Moderator | VIP | Member |
|------------|--------|-------|-----------|-----|--------|
| `/admin` | ✅ | ✅ | ❌ | ❌ | ❌ |
| `/ban` | ✅ | ✅ | ✅ | ❌ | ❌ |
| `/unban` | ✅ | ✅ | ✅ | ❌ | ❌ |
| `/kick` | ✅ | ✅ | ✅ | ❌ | ❌ |
| `/mute` | ✅ | ✅ | ✅ | ❌ | ❌ |
| `/unmute` | ✅ | ✅ | ✅ | ❌ | ❌ |
| `/promote` | ✅ | ✅ | ❌ | ❌ | ❌ |
| `/demote` | ✅ | ✅ | ❌ | ❌ | ❌ |
| `/settings` | ✅ | ✅ | ✅ | ❌ | ❌ |
| `/stats` | ✅ | ✅ | ✅ | ❌ | ❌ |
| `/queue` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `/skip` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `/volume` | ✅ | ✅ | ❌ | ❌ | ❌ |
| `/play` | ✅ | ✅ | ✅ | ✅ | ✅ |

### Permission Implementation

```python
class PermissionManager:
    def __init__(self):
        self.owner_id = int(os.getenv("OWNER_ID", "0"))
        self.admin_ids = set(int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x)
        self.db = DatabaseManager()
    
    def get_user_role(self, user_id: int, chat_id: int) -> UserRole:
        # Check if owner
        if user_id == self.owner_id:
            return UserRole.OWNER
        
        # Check if global admin
        if user_id in self.admin_ids:
            return UserRole.ADMIN
        
        # Check database roles
        db_role = self.db.get_user_role(user_id, chat_id)
        return UserRole(db_role) if db_role else UserRole.MEMBER
    
    def has_permission(self, user_id: int, chat_id: int, permission: str) -> bool:
        role = self.get_user_role(user_id, chat_id)
        return self.check_role_permission(role, permission)
    
    def check_role_permission(self, role: UserRole, permission: str) -> bool:
        permissions = self.ROLE_PERMISSIONS.get(role, set())
        return permission in permissions
```

## 🔧 Admin Commands

### Core Admin Commands

#### `/admin` - Admin Panel
```python
@admin_required
async def admin_panel(client, message):
    """Display comprehensive admin control panel"""
    
    admin_panel = {
        "📊 **Current Stats**": await get_admin_stats(),
        "👥 **Active Chats**": len(call_manager.active_chats),
        "🎵 **Queue Status**": await get_queue_stats(),
        "⚙️ **System Health**": await get_system_health(),
        "📈 **Performance**": await get_performance_metrics()
    }
    
    # Format as beautiful message
    panel_text = format_admin_panel(admin_panel)
    await message.reply(panel_text)
```

#### `/stats` - System Statistics
```python
@admin_required
async def system_stats(client, message):
    """Show comprehensive system statistics"""
    
    stats = {
        "🤖 **Bot Information**": {
            "Uptime": get_uptime(),
            "Version": BOT_VERSION,
            "Memory": get_memory_usage(),
            "CPU": get_cpu_usage()
        },
        "📊 **Usage Statistics**": {
            "Total Plays": await get_total_plays(),
            "Total Searches": await get_total_searches(),
            "Active Users": await get_active_users_count(),
            "Total Users": await get_total_users_count()
        },
        "🎵 **Music Statistics**": {
            "Most Played Songs": await get_most_played_songs(),
            "Popular Artists": await get_popular_artists(),
            "Source Distribution": await get_source_distribution(),
            "Average Play Duration": await get_avg_play_duration()
        },
        "📈 **Performance Metrics**": {
            "Response Time": get_avg_response_time(),
            "Success Rate": get_success_rate(),
            "Error Rate": get_error_rate()
        }
    }
    
    await message.reply(format_stats_message(stats))
```

#### `/settings` - Bot Configuration
```python
@admin_required
async def bot_settings(client, message):
    """Display and modify bot settings"""
    
    current_settings = {
        "🎵 **Audio Quality": config.AUDIO_QUALITY,
        "🔊 **Max Volume": config.MAX_VOLUME,
        "⏱️ **Queue Limit": config.MAX_QUEUE_SIZE,
        "🚫 **Auto-Leave**: config.AUTO_LEAVE_VC,
        "🔞 **Skip Cooldown**: config.SKIP_COOLDOWN,
        "📊 **Analytics**: config.ANALYTICS_ENABLED,
        "🔒 **Strict Mode**: config.STRICT_MODE
    }
    
    # Interactive settings menu
    keyboard = create_settings_keyboard()
    await message.reply("⚙️ **Bot Settings**:", reply_markup=keyboard)
```

### User Management Commands

#### `/ban` - Ban User
```python
@moderator_required
async def ban_user(client, message):
    """Ban user from bot with optional reason and duration"""
    
    # Parse command: /ban @username [reason] [duration]
    args = message.text.split()[1:]
    
    if not args or not message.reply_to_message:
        await message.reply("❌ Usage: /ban @username [reason] [duration]")
        return
    
    # Extract user, reason, duration
    target_user, reason, duration = parse_ban_command(args)
    
    if not target_user:
        await message.reply("❌ User not found")
        return
    
    # Validate permissions
    if not can_ban_user(message.from_user.id, target_user.id):
        await message.reply("❌ Cannot ban this user (insufficient permissions)")
        return
    
    # Execute ban
    ban_record = {
        "user_id": target_user.id,
        "banned_by": message.from_user.id,
        "reason": reason or "No reason provided",
        "duration": duration or "permanent",
        "timestamp": datetime.utcnow(),
        "chat_id": message.chat.id
    }
    
    await db.create_ban(ban_record)
    
    # Notify user
    try:
        await client.send_message(
            target_user.id,
            f"🚫 You have been banned from {message.chat.title}\n"
            f"Reason: {reason}\n"
            f"Duration: {duration}"
        )
    except Exception:
        pass  # User might have blocked bot
    
    # Notify chat
    await message.reply(
        f"🚫 **User Banned**\n"
        f"👤 {target_user.mention}\n"
        f"📝 Reason: {reason}\n"
        f"⏰ Duration: {duration}"
    )
```

#### `/unban` - Unban User
```python
@moderator_required
async def unban_user(client, message):
    """Unban user from bot"""
    
    # Parse command
    args = message.text.split()[1:]
    if not args or not message.reply_to_message:
        await message.reply("❌ Usage: /unban @username")
        return
    
    target_user = parse_user_mention(args[0])
    
    if not target_user:
        await message.reply("❌ User not found")
        return
    
    # Remove ban from database
    await db.remove_ban(target_user.id, message.chat.id)
    
    # Notify user
    try:
        await client.send_message(
            target_user.id,
            f"✅ You have been unbanned from {message.chat.title}"
        )
    except Exception:
        pass
    
    # Notify chat
    await message.reply(
        f"✅ **User Unbanned**\n"
        f"👤 {target_user.mention}"
    )
```

#### `/promote` - Promote User
```python
@admin_required
async def promote_user(client, message):
    """Promote user to moderator or admin"""
    
    args = message.text.split()[1:]
    if not args or not message.reply_to_message:
        await message.reply("❌ Usage: /promote @username [moderator|admin]")
        return
    
    target_user = parse_user_mention(args[0])
    new_role = args[1].lower() if len(args) > 1 else "moderator"
    
    if new_role not in ["moderator", "admin"]:
        await message.reply("❌ Invalid role. Use: moderator or admin")
        return
    
    # Update user role in database
    await db.set_user_role(target_user.id, message.chat.id, new_role)
    
    # Notify user
    try:
        await client.send_message(
            target_user.id,
            f"🎉 You have been promoted to {new_role} in {message.chat.title}"
        )
    except Exception:
        pass
    
    # Notify chat
    await message.reply(
        f"🎉 **User Promoted**\n"
        f"👤 {target_user.mention}\n"
        f"🏷️ New Role: {new_role}"
    )
```

#### `/demote` - Demote User
```python
@admin_required
async def demote_user(client, message):
    """Demote user to member"""
    
    args = message.text.split()[1:]
    if not args or not message.reply_to_message:
        await message.reply("❌ Usage: /demote @username")
        return
    
    target_user = parse_user_mention(args[0])
    
    # Reset user role to member
    await db.set_user_role(target_user.id, message.chat.id, "member")
    
    # Notify user
    try:
        await client.send_message(
            target_user.id,
            f"📉 You have been demoted to member in {message.chat.title}"
        )
    except Exception:
        pass
    
    # Notify chat
    await message.reply(
        f"📉 **User Demoted**\n"
        f"👤 {target_user.mention}\n"
        f"🏷️ New Role: Member"
    )
```

### Group Management Commands

#### `/kick` - Kick User
```python
@moderator_required
async def kick_user(client, message):
    """Kick user from group"""
    
    args = message.text.split()[1:]
    if not args or not message.reply_to_message:
        await message.reply("❌ Usage: /kick @username [reason]")
        return
    
    target_user = parse_user_mention(args[0])
    reason = " ".join(args[1:]) if len(args) > 1 else "No reason"
    
    # Validate permissions
    if not can_kick_user(message.from_user.id, target_user.id):
        await message.reply("❌ Cannot kick this user")
        return
    
    # Execute kick
    await client.kick_chat_member(message.chat.id, target_user.id)
    
    # Log action
    await db.log_moderation_action({
        "action": "kick",
        "target_user": target_user.id,
        "moderator": message.from_user.id,
        "reason": reason,
        "timestamp": datetime.utcnow(),
        "chat_id": message.chat.id
    })
    
    await message.reply(
        f"👢 **User Kicked**\n"
        f"👤 {target_user.mention}\n"
        f"📝 Reason: {reason}"
    )
```

#### `/mute` - Mute User
```python
@moderator_required
async def mute_user(client, message):
    """Mute user in group"""
    
    args = message.text.split()[1:]
    if not args or not message.reply_to_message:
        await message.reply("❌ Usage: /mute @username [duration] [reason]")
        return
    
    target_user = parse_user_mention(args[0])
    duration = parse_duration(args[1]) if len(args) > 1 else 3600  # 1 hour default
    reason = " ".join(args[2:]) if len(args) > 2 else "No reason"
    
    # Execute mute
    await client.restrict_chat_member(
        message.chat.id,
        target_user.id,
        can_send_messages=False,
        until_date=datetime.utcnow() + timedelta(seconds=duration)
    )
    
    # Log action
    await db.log_moderation_action({
        "action": "mute",
        "target_user": target_user.id,
        "moderator": message.from_user.id,
        "duration": duration,
        "reason": reason,
        "timestamp": datetime.utcnow(),
        "chat_id": message.chat.id
    })
    
    await message.reply(
        f"🔇 **User Muted**\n"
        f"👤 {target_user.mention}\n"
        f"⏰ Duration: {format_duration(duration)}\n"
        f"📝 Reason: {reason}"
    )
```

#### `/unmute` - Unmute User
```python
@moderator_required
async def unmute_user(client, message):
    """Unmute user in group"""
    
    args = message.text.split()[1:]
    if not args or not message.reply_to_message:
        await message.reply("❌ Usage: /unmute @username")
        return
    
    target_user = parse_user_mention(args[0])
    
    # Execute unmute
    await client.unban_chat_member(message.chat.id, target_user.id)
    
    # Log action
    await db.log_moderation_action({
        "action": "unmute",
        "target_user": target_user.id,
        "moderator": message.from_user.id,
        "timestamp": datetime.utcnow(),
        "chat_id": message.chat.id
    })
    
    await message.reply(
        f"🔊 **User Unmuted**\n"
        f"👤 {target_user.mention}"
    )
```

## 🗄️ Database Schema

### Users Table
```sql
CREATE TABLE users (
    user_id INTEGER PRIMARY KEY,
    username TEXT NOT NULL,
    first_name TEXT,
    last_name TEXT,
    language_code TEXT DEFAULT 'en',
    is_bot BOOLEAN DEFAULT FALSE,
    is_premium BOOLEAN DEFAULT FALSE,
    is_active BOOLEAN DEFAULT TRUE,
    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    total_plays INTEGER DEFAULT 0,
    total_searches INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### User Roles Table
```sql
CREATE TABLE user_roles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    chat_id INTEGER NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('owner', 'admin', 'moderator', 'vip', 'member', 'restricted', 'banned')),
    assigned_by INTEGER NOT NULL,
    assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP NULL,  -- For temporary roles
    reason TEXT,
    FOREIGN KEY (user_id) REFERENCES users(user_id),
    FOREIGN KEY (chat_id) REFERENCES chats(chat_id),
    UNIQUE(user_id, chat_id)
);
```

### Bans Table
```sql
CREATE TABLE bans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    chat_id INTEGER NOT NULL,
    banned_by INTEGER NOT NULL,
    reason TEXT,
    duration TEXT,  -- 'permanent' or 'Xh Ym Zd'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP NULL,
    is_active BOOLEAN DEFAULT TRUE,
    FOREIGN KEY (user_id) REFERENCES users(user_id),
    FOREIGN KEY (chat_id) REFERENCES chats(chat_id),
    FOREIGN KEY (banned_by) REFERENCES users(user_id)
);
```

### Moderation Log Table
```sql
CREATE TABLE moderation_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    moderator_id INTEGER NOT NULL,
    target_user_id INTEGER NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('ban', 'unban', 'kick', 'mute', 'unmute', 'promote', 'demote')),
    reason TEXT,
    duration INTEGER,  -- For mutes (seconds)
    metadata TEXT,  -- JSON for additional data
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (chat_id) REFERENCES chats(chat_id),
    FOREIGN KEY (moderator_id) REFERENCES users(user_id),
    FOREIGN KEY (target_user_id) REFERENCES users(user_id)
);
```

### Chat Settings Table
```sql
CREATE TABLE chat_settings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER UNIQUE NOT NULL,
    setting_key TEXT NOT NULL,
    setting_value TEXT NOT NULL,
    set_by INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (chat_id) REFERENCES chats(chat_id),
    FOREIGN KEY (set_by) REFERENCES users(user_id)
);
```

### Analytics Table
```sql
CREATE TABLE analytics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    event_data TEXT,  -- JSON blob
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (chat_id) REFERENCES chats(chat_id),
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

-- Indexes for performance
CREATE INDEX idx_analytics_chat_id ON analytics(chat_id);
CREATE INDEX idx_analytics_user_id ON analytics(user_id);
CREATE INDEX idx_analytics_event_type ON analytics(event_type);
CREATE INDEX idx_analytics_created_at ON analytics(created_at);
```

## 📊 Analytics System

### Event Tracking
```python
class AnalyticsManager:
    def __init__(self):
        self.db = DatabaseManager()
    
    async def track_event(self, event_type: str, data: Dict, chat_id: int = None, user_id: int = None):
        """Track analytics event"""
        event_record = {
            "event_type": event_type,
            "event_data": json.dumps(data),
            "chat_id": chat_id,
            "user_id": user_id,
            "created_at": datetime.utcnow()
        }
        
        await self.db.create_analytics_event(event_record)
    
    async def get_user_stats(self, user_id: int, days: int = 30) -> Dict:
        """Get user statistics"""
        stats = await self.db.get_user_analytics(user_id, days)
        return {
            "total_plays": stats.get("play_count", 0),
            "total_searches": stats.get("search_count", 0),
            "favorite_genres": stats.get("favorite_genres", []),
            "avg_session_duration": stats.get("avg_session", 0),
            "most_played_songs": stats.get("top_songs", [])
        }
    
    async def get_chat_stats(self, chat_id: int, days: int = 30) -> Dict:
        """Get chat statistics"""
        stats = await self.db.get_chat_analytics(chat_id, days)
        return {
            "total_plays": stats.get("play_count", 0),
            "unique_users": stats.get("unique_users", 0),
            "peak_concurrent": stats.get("peak_users", 0),
            "most_active_hours": stats.get("active_hours", []),
            "popular_commands": stats.get("commands", {})
        }
```

### Performance Metrics
```python
class PerformanceMonitor:
    def __init__(self):
        self.metrics = {
            "command_response_times": [],
            "error_counts": {},
            "success_rates": {},
            "resource_usage": []
        }
    
    async def record_command_time(self, command: str, duration: float):
        """Record command execution time"""
        self.metrics["command_response_times"].append({
            "command": command,
            "duration": duration,
            "timestamp": datetime.utcnow()
        })
    
    def get_avg_response_time(self, command: str = None) -> float:
        """Get average response time"""
        times = [m["duration"] for m in self.metrics["command_response_times"] 
                  if command is None or m["command"] == command]
        return sum(times) / len(times) if times else 0.0
    
    def get_error_rate(self, service: str = None) -> float:
        """Get error rate for service"""
        total_errors = sum(self.metrics["error_counts"].values())
        total_requests = total_errors + sum(self.metrics["success_rates"].values())
        return (total_errors / total_requests * 100) if total_requests > 0 else 0.0
```

## 🔧 Configuration Management

### Dynamic Settings
```python
class ConfigManager:
    def __init__(self):
        self.db = DatabaseManager()
        self.cache = {}
    
    async def get_setting(self, chat_id: int, key: str, default=None):
        """Get chat setting with caching"""
        if (chat_id, key) in self.cache:
            return self.cache[(chat_id, key)]
        
        setting = await self.db.get_chat_setting(chat_id, key)
        self.cache[(chat_id, key)] = setting
        return setting if setting is not None else default
    
    async def set_setting(self, chat_id: int, key: str, value: str, user_id: int):
        """Set chat setting with validation"""
        # Validate setting
        if not self.validate_setting(key, value):
            raise ValueError(f"Invalid setting value: {key}={value}")
        
        await self.db.set_chat_setting(chat_id, key, value, user_id)
        self.cache[(chat_id, key)] = value
        
        # Log change
        await self.log_setting_change(chat_id, key, value, user_id)
    
    def validate_setting(self, key: str, value: str) -> bool:
        """Validate setting value"""
        validators = {
            "audio_quality": lambda v: v in ["low", "medium", "high", "ultra"],
            "max_volume": lambda v: 0 <= int(v) <= 200,
            "queue_limit": lambda v: 1 <= int(v) <= 100,
            "auto_leave": lambda v: v.lower() in ["true", "false"],
            "strict_mode": lambda v: v.lower() in ["true", "false"]
        }
        
        return key in validators and validators[key](value)
```

### Settings Categories

#### Audio Settings
- `audio_quality`: low/medium/high/ultra
- `max_volume`: 0-200 (percentage)
- `auto_volume`: true/false (automatic volume adjustment)
- `crossfade`: true/false (smooth transitions)

#### Queue Settings
- `queue_limit`: 1-100 (maximum tracks)
- `duplicate_prevention`: true/false (prevent duplicates)
- `auto_skip`: true/false (skip low-quality tracks)
- `shuffle_mode`: normal/reverse/random

#### Behavior Settings
- `auto_leave`: true/false (leave VC when empty)
- `welcome_message`: custom text (new user greeting)
- `goodbye_message`: custom text (user leaving)
- `strict_mode`: true/false (enforce permissions strictly)

#### Moderation Settings
- `spam_protection`: true/false (anti-spam measures)
- `max_warnings`: 1-10 (warnings before kick)
- `mute_new_users`: true/false (auto-mute new members)
- `require_verification`: true/false (new user verification)

## 🚨 Moderation Tools

### Anti-Spam System
```python
class SpamProtection:
    def __init__(self):
        self.user_message_counts = {}
        self.spam_threshold = 5  # messages per minute
        self.spam_timeout = 300  # 5 minutes
    
    async def check_message(self, message):
        """Check if message is spam"""
        user_id = message.from_user.id
        current_time = time.time()
        
        # Clean old entries
        self.cleanup_old_counts(current_time)
        
        # Update count
        if user_id not in self.user_message_counts:
            self.user_message_counts[user_id] = []
        
        self.user_message_counts[user_id].append(current_time)
        
        # Check threshold
        recent_count = len([t for t in self.user_message_counts[user_id] 
                           if current_time - t < 60])
        
        if recent_count >= self.spam_threshold:
            return await self.handle_spam(message, recent_count)
        
        return False
    
    async def handle_spam(self, message, count):
        """Handle spam detection"""
        # Delete spam messages
        await message.delete()
        
        # Warn user
        await message.reply(
            f"⚠️ Spam detected! {count} messages in 1 minute.\n"
            f"Please slow down or you will be muted."
        )
        
        # Log incident
        await self.log_spam_incident(message.from_user.id, count)
```

### Content Filter
```python
class ContentFilter:
    def __init__(self):
        self.banned_words = self.load_banned_words()
        self.banned_domains = self.load_banned_domains()
    
    async def check_message(self, message):
        """Check message for inappropriate content"""
        text = message.text.lower()
        
        # Check banned words
        for word in self.banned_words:
            if word in text:
                await self.handle_violation(message, "banned_word", word)
                return True
        
        # Check banned domains
        for domain in self.banned_domains:
            if domain in text:
                await self.handle_violation(message, "banned_domain", domain)
                return True
        
        return False
    
    async def handle_violation(self, message, violation_type, content):
        """Handle content violation"""
        # Delete message
        await message.delete()
        
        # Warn user
        await message.reply(
            f"⚠️ Content violation detected: {violation_type}\n"
            f"Message removed. Continued violations will result in a ban."
        )
        
        # Log incident
        await self.log_content_violation(message.from_user.id, violation_type, content)
```

## 🔒 Security Features

### Access Control
```python
class SecurityManager:
    def __init__(self):
        self.failed_attempts = {}
        self.max_attempts = 5
        self.lockout_duration = 900  # 15 minutes
    
    async def check_admin_access(self, user_id: int, command: str) -> bool:
        """Check if user can access admin command"""
        # Check failed attempts
        if user_id in self.failed_attempts:
            attempts = self.failed_attempts[user_id]
            if len(attempts) >= self.max_attempts:
                if time.time() - attempts[-1] < self.lockout_duration:
                    return False
        
        # Verify permission
        return await self.verify_admin_permission(user_id, command)
    
    async def record_failed_attempt(self, user_id: int):
        """Record failed admin attempt"""
        if user_id not in self.failed_attempts:
            self.failed_attempts[user_id] = []
        
        self.failed_attempts[user_id].append(time.time())
        
        # Clean old attempts
        cutoff = time.time() - self.lockout_duration
        self.failed_attempts[user_id] = [t for t in self.failed_attempts[user_id] if t > cutoff]
```

### Data Protection
```python
class DataProtection:
    def __init__(self):
        self.encryption_key = os.getenv("DB_ENCRYPTION_KEY")
    
    def encrypt_sensitive_data(self, data: str) -> str:
        """Encrypt sensitive database fields"""
        from cryptography.fernet import Fernet
        f = Fernet(self.encryption_key)
        return f.encrypt(data.encode()).decode()
    
    def anonymize_logs(self, log_data: Dict) -> Dict:
        """Remove PII from log data"""
        sensitive_fields = ["phone", "email", "real_name"]
        return {k: v for k, v in log_data.items() 
                if k not in sensitive_fields}
    
    def audit_log(self, action: str, user_id: int, details: Dict):
        """Create audit trail for sensitive actions"""
        audit_entry = {
            "action": action,
            "user_id": user_id,
            "details": details,
            "timestamp": datetime.utcnow(),
            "ip_address": self.get_client_ip()
        }
        
        # Store in secure audit log
        await self.store_audit_entry(audit_entry)
```

## 📈 Monitoring & Alerts

### Health Monitoring
```python
class HealthMonitor:
    def __init__(self):
        self.metrics = {
            "bot_uptime": time.time(),
            "last_error": None,
            "error_count": 0,
            "memory_usage": [],
            "response_times": []
        }
    
    async def check_system_health(self) -> Dict:
        """Comprehensive health check"""
        health_status = {
            "overall": "healthy",
            "bot": await self.check_bot_health(),
            "database": await self.check_database_health(),
            "wrappers": await self.check_wrapper_health(),
            "performance": await self.check_performance_health(),
            "security": await self.check_security_health()
        }
        
        # Overall status is worst component status
        statuses = [health_status[k]["status"] for k in health_status.keys()]
        if "unhealthy" in statuses:
            health_status["overall"] = "unhealthy"
        elif "degraded" in statuses:
            health_status["overall"] = "degraded"
        
        return health_status
    
    async def check_wrapper_health(self) -> Dict:
        """Check external wrapper services"""
        wrapper_health = {}
        
        # YouTube wrapper
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get("https://youtube-music-wrapper.onrender.com/", timeout=10) as resp:
                    wrapper_health["youtube"] = {
                        "status": "healthy" if resp.status == 200 else "unhealthy",
                        "response_time": resp.headers.get("X-Response-Time"),
                        "last_check": datetime.utcnow().isoformat()
                    }
        except Exception as e:
            wrapper_health["youtube"] = {
                "status": "unhealthy",
                "error": str(e),
                "last_check": datetime.utcnow().isoformat()
            }
        
        # JioSaavn wrapper
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get("https://jio-savan-music-wrapper.onrender.com/", timeout=10) as resp:
                    wrapper_health["jiosaavn"] = {
                        "status": "healthy" if resp.status == 200 else "unhealthy",
                        "response_time": resp.headers.get("X-Response-Time"),
                        "last_check": datetime.utcnow().isoformat()
                    }
        except Exception as e:
            wrapper_health["jiosaavn"] = {
                "status": "unhealthy",
                "error": str(e),
                "last_check": datetime.utcnow().isoformat()
            }
        
        return wrapper_health
```

### Alert System
```python
class AlertManager:
    def __init__(self):
        self.alert_channels = os.getenv("ALERT_CHANNELS", "").split(",")
        self.alert_thresholds = {
            "error_rate": 0.1,  # 10% error rate
            "memory_usage": 0.8,  # 80% memory usage
            "response_time": 5.0,  # 5 second response time
            "downtime": 60  # 60 seconds
        }
    
    async def check_alerts(self, metrics: Dict):
        """Check if any alerts should be triggered"""
        alerts = []
        
        # Error rate alert
        if metrics.get("error_rate", 0) > self.alert_thresholds["error_rate"]:
            alerts.append({
                "type": "error_rate",
                "severity": "warning",
                "message": f"Error rate ({metrics['error_rate']:.1%}) exceeds threshold"
            })
        
        # Memory usage alert
        if metrics.get("memory_usage", 0) > self.alert_thresholds["memory_usage"]:
            alerts.append({
                "type": "memory_usage",
                "severity": "critical",
                "message": f"Memory usage ({metrics['memory_usage']:.1%}) exceeds threshold"
            })
        
        # Send alerts
        for alert in alerts:
            await self.send_alert(alert)
    
    async def send_alert(self, alert: Dict):
        """Send alert to configured channels"""
        message = f"🚨 **{alert['severity'].upper()} ALERT**\n{alert['message']}"
        
        for channel_id in self.alert_channels:
            try:
                await client.send_message(channel_id, message)
            except Exception as e:
                logger.error(f"Failed to send alert to {channel_id}: {e}")
```

## 🧪 Testing & Validation

### Admin Command Tests
```python
import pytest
from bot.admin import admin_commands, PermissionManager

@pytest.mark.asyncio
async def test_admin_panel():
    """Test admin panel command"""
    # Mock admin user
    mock_user = MockUser(id=123456, is_admin=True)
    mock_message = MockMessage(from_user=mock_user, text="/admin")
    
    # Test command execution
    response = await admin_commands.admin_panel(None, mock_message)
    
    # Verify response contains expected sections
    assert "Current Stats" in response.text
    assert "Active Chats" in response.text
    assert "System Health" in response.text

@pytest.mark.asyncio
async def test_permission_system():
    """Test permission system"""
    perm_manager = PermissionManager()
    
    # Test owner permissions
    assert perm_manager.has_permission(OWNER_ID, "admin_panel") == True
    assert perm_manager.has_permission(OWNER_ID, "ban") == True
    
    # Test regular user permissions
    assert perm_manager.has_permission(REGULAR_USER_ID, "admin_panel") == False
    assert perm_manager.has_permission(REGULAR_USER_ID, "ban") == False
```

### Database Tests
```python
@pytest.mark.asyncio
async def test_user_management():
    """Test user management database operations"""
    db = DatabaseManager()
    
    # Test user creation
    user_data = {
        "user_id": 123456,
        "username": "testuser",
        "first_name": "Test",
        "last_name": "User"
    }
    await db.create_user(user_data)
    
    # Test user retrieval
    retrieved_user = await db.get_user(123456)
    assert retrieved_user.username == "testuser"
    
    # Test role assignment
    await db.set_user_role(123456, 789, "moderator")
    role = await db.get_user_role(123456, 789)
    assert role == "moderator"
```

### Integration Tests
```python
@pytest.mark.asyncio
async def test_admin_workflow():
    """Test complete admin workflow"""
    # 1. Setup test environment
    test_client = MockTelegramClient()
    test_db = DatabaseManager()
    
    # 2. Create test chat with admin
    admin_user = await create_test_user(role="admin")
    test_chat = await create_test_chat(admin_user)
    
    # 3. Test ban workflow
    target_user = await create_test_user(role="member")
    
    # Execute ban command
    ban_message = MockMessage(
        from_user=admin_user,
        chat=test_chat,
        text="/ban @testuser Spamming"
    )
    
    await admin_commands.ban_user(test_client, ban_message)
    
    # Verify ban in database
    ban_record = await test_db.get_active_ban(target_user.id, test_chat.id)
    assert ban_record is not None
    assert ban_record.reason == "Spamming"
```

---

*Last Updated: May 8, 2026*
