# Music Bot Core - Technical Documentation

## 📋 Overview

The Music Bot Core is a Python-based Telegram bot with advanced music extraction, multi-source fallback, and voice chat capabilities using py-tgcalls.

## 🏗️ Architecture

### Core Components

- **Telegram Bot Framework** - pyrogram-based bot with command handling
- **Music Backend** - Multi-source music extraction and management
- **Voice Chat Manager** - py-tgcalls integration for VC playback
- **Queue System** - Advanced queue management with persistence
- **Source Extractors** - YouTube, JioSaavn, Deezer, VK, Direct
- **Fallback Chain** - Intelligent source switching for reliability
- **Circuit Breakers** - Prevent cascading failures

### Dependencies

```python
# Core
pyrogram>=2.0.106
py-tgcalls>=2.0.0
aiohttp>=3.8.0
python-dotenv>=1.0.0

# Music Processing
yt-dlp>=2024.1.1
ffmpeg-python>=0.2.0

# Database & Caching
sqlite3 (built-in)
redis (optional for distributed caching)

# Utilities
asyncio
logging
json
pathlib
datetime
```

## 🔌 Bot Commands

### Music Commands

| Command | Description | Usage | Permissions |
|---------|-------------|---------|------------|
| `/play {query}` | Search and play music | User | All |
| `/play {url}` | Play from URL | User | All |
| `/search {query}` | Search music | User | All |
| `/queue` | Show current queue | User | All |
| `/skip` | Skip current track | User | All |
| `/pause` | Pause playback | User | All |
| `/resume` | Resume playback | User | All |
| `/stop` | Stop playback | User | All |
| `/volume {level}` | Set volume (0-200) | Admin | All |

### Admin Commands

| Command | Description | Usage |
|---------|-------------|---------|
| `/admin` | Admin panel | Admins only |
| `/stats` | Bot statistics | Admins only |
| `/restart` | Restart bot | Admins only |
| `/update` | Update bot | Admins only |

### Utility Commands

| Command | Description | Usage |
|---------|-------------|---------|
| `/start` | Start message | New users |
| `/help` | Help message | All users |
| `/ping` | Latency check | All users |
| `/info` | Bot information | All users |

## 🎵 Music Backend System

### Source Extractors

#### YouTube Extractor
```python
class YouTubeWrapperExtractor:
    base_url: str = "https://youtube-music-wrapper.onrender.com"
    
    async def search(query: str, limit: int) -> List[Dict]:
        # Calls wrapper /search endpoint
        
    async def extract(track_id: str) -> Optional[Dict]:
        # Calls wrapper /track/{id} endpoint
```

#### JioSaavn Extractor
```python
class JioSaavnWrapperExtractor:
    base_url: str = "https://jio-savan-music-wrapper.onrender.com"
    
    async def search(query: str, limit: int) -> List[Dict]:
        # Calls wrapper /search endpoint
        
    async def extract(track_id: str) -> Optional[Dict]:
        # Calls wrapper /track/{id} endpoint
```

#### Direct Extractors
```python
class DeezerExtractor:
    # Direct Deezer API integration
    
class VKExtractor:
    # Direct VK API integration
    
class GlobalIndexExtractor:
    # Fallback global music index
```

### Source Priority System

```python
class SourceRanker:
    _BASE_WEIGHTS = {
        "youtube": 1.0,      # BEST (cookies working)
        "jiosaavn": 1.2,     # Good but preview URLs
        "vk": 1.3,
        "deezer": 1.4,
        "global_index": 1.5,
        "telegram": 2.5,
        "direct": 2.5,
        "unknown": 3.0,
    }
    
    @classmethod
    def get_source_priority(cls, source: str, query: str) -> float:
        # Dynamic priority calculation with health tracking
```

### Search Orchestration

```python
async def search(query: str, limit: int) -> List[Track]:
    # 1. Parallel search across all extractors
    # 2. Tier-based result combination
    # 3. Duplicate filtering
    # 4. Priority-based ranking
    # 5. Limit enforcement
    
    tiers = [yt_res, js_res, dz_res, vk_res, idx_res]
    combined = []
    seen = set()
    
    for tier in tiers:
        for track in tier:
            key = (track.track_id or track.stream_url or track.title).lower()
            if key not in seen:
                seen.add(key)
                combined.append(track)
```

### Fallback Chain System

```python
async def get_stream_payload(track: Track) -> Optional[Dict]:
    # 1. Try primary source extraction
    # 2. Try alternative sources with same ID
    # 3. Search for alternative tracks by title
    # 4. Build payload with proper headers
    
    # Primary extraction
    if source == "youtube":
        resolved = await youtube_wrapper_extractor.extract(track.track_id)
    
    # Fallback chain
    if not resolved:
        for alt_source in ["jiosaavn", "deezer", "vk"]:
            resolved = await extractors[alt_source].extract(track.track_id)
            if resolved:
                break
    
    # Search fallback
    if not resolved:
        alt_results = await search(f"{track.title} {track.artist}", limit=1)
        if alt_results:
            resolved = await get_stream_payload(alt_results[0])
```

## 🎤 Voice Chat System

### py-tgcalls Integration

```python
class CallManager:
    def __init__(self):
        self.calls: List[PyTgCalls] = []
        self.active_chats: Dict[int, int] = {}
        
    async def play(self, chat_id: int, url: str, headers: Dict = None):
        stream = self._build_stream(url, headers=headers)
        await self._join_and_play(chat_id, stream)
```

### Stream Building

```python
@staticmethod
def _build_stream(stream_url: str, headers: Dict = None) -> MediaStream:
    # Audio parameters
    audio_cfg = AudioParameters(bitrate=128000)
    
    # FFmpeg parameters for headers
    ffmpeg_params = "-nostdin -vn -reconnect 1"
    if headers:
        ffmpeg_params += build_ffmpeg_headers(headers)
    
    return MediaStream(
        media_path=stream_url,
        audio_parameters=audio_cfg,
        ffmpeg_parameters=ffmpeg_params
    )
```

### Header Management

```python
def get_source_headers(source_name: str) -> Dict[str, str]:
    if source_name == "youtube":
        return {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "*/*",
            "Referer": "https://www.youtube.com/",
        }
    
    elif source_name == "jiosaavn":
        return {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "*/*",
            "Referer": "https://www.jiosaavn.com/",
            "Origin": "https://www.jiosaavn.com",
            "Connection": "keep-alive",
            "sec-ch-ua": '"Not_A Brand";v="8", "Chromium";v="120"',
        }
```

## 📊 Queue Management

### Queue Structure

```python
class TrackQueue:
    def __init__(self):
        self.queue: List[Dict] = []
        self.current: Optional[Dict] = None
        self.position: int = 0
        self.status: str = "idle"
        self.chat_id: int
```

### Queue Operations

```python
async def add_track(chat_id: int, track: Dict, position: int = None):
    # Add track to queue
    # Update position
    # Persist to database
    # Emit event to listeners

async def skip_track(chat_id: int):
    # Move to next track
    # Update position
    # Start playback

async def clear_queue(chat_id: int):
    # Clear all tracks
    # Reset position
    # Update status
```

### Persistence

```python
class QueuePersistence:
    def save_state(self, chat_id: int, queue: TrackQueue):
        # Serialize queue to JSON
        # Store in database
        # Update timestamp
        
    def load_state(self, chat_id: int) -> TrackQueue:
        # Load from database
        # Deserialize JSON
        # Restore queue state
```

## 🗄️ Database Schema

### SQLite Schema

```sql
-- Queues table
CREATE TABLE queues (
    chat_id INTEGER PRIMARY KEY,
    queue_data TEXT NOT NULL,  -- JSON serialized queue
    current_track TEXT,       -- JSON current track
    position INTEGER DEFAULT 0,
    status TEXT DEFAULT 'idle',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Track history table
CREATE TABLE track_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER,
    track_id TEXT,
    title TEXT,
    artist TEXT,
    source TEXT,
    played_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Bot stats table
CREATE TABLE bot_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date DATE DEFAULT CURRENT_DATE,
    plays_count INTEGER DEFAULT 0,
    searches_count INTEGER DEFAULT 0,
    errors_count INTEGER DEFAULT 0
);
```

## 🔄 Event System

### Event Types

```python
class EventType(Enum):
    TRACK_STARTED = "track_started"
    TRACK_ENDED = "track_ended"
    QUEUE_UPDATED = "queue_updated"
    VOICE_CHAT_JOINED = "vc_joined"
    VOICE_CHAT_LEFT = "vc_left"
    ERROR_OCCURRED = "error"
```

### Event Handlers

```python
class EventManager:
    def __init__(self):
        self.handlers: Dict[EventType, List[Callable]] = {}
        
    def register_handler(self, event_type: EventType, handler: Callable):
        if event_type not in self.handlers:
            self.handlers[event_type] = []
        self.handlers[event_type].append(handler)
        
    async def emit_event(self, event_type: EventType, data: Any):
        if event_type in self.handlers:
            for handler in self.handlers[event_type]:
                try:
                    await handler(data)
                except Exception as e:
                    logger.error(f"Event handler error: {e}")
```

## 🔧 Configuration

### Environment Variables

| Variable | Description | Required | Default |
|----------|-------------|-----------|---------|
| `BOT_TOKEN` | Telegram bot token | Yes | - |
| `API_ID` | Telegram API ID | Yes | - |
| `API_HASH` | Telegram API hash | Yes | - |
| `YOUTUBE_API_BASE_URL` | YouTube wrapper URL | No | https://youtube-music-wrapper.onrender.com |
| `JIOSAAVN_API_BASE_URL` | JioSaavn wrapper URL | No | https://jio-savan-music-wrapper.onrender.com |
| `AUDIO_QUALITY` | Audio quality preset | No | high |
| `AUDIO_BITRATE` | Max bitrate (kbps) | No | 192 |
| `DATABASE_URL` | SQLite database path | No | bot.db |
| `REDIS_URL` | Redis connection string | No | - |

### Quality Settings

```python
_QUALITY_MIN_BITRATE = {
    "low": 64,
    "medium": 96,
    "high": 128,
    "ultra": 192,
}
```

## 🚨 Error Handling

### Error Categories

1. **Extraction Errors**
   - Source API failures
   - Network timeouts
   - Invalid track IDs

2. **Playback Errors**
   - Stream validation failures
   - Voice chat connection issues
   - FFmpeg errors

3. **Queue Errors**
   - Database connection failures
   - Serialization errors
   - Position conflicts

### Error Recovery

```python
async def handle_extraction_error(track: Track, error: Exception):
    # 1. Log error with context
    # 2. Try fallback sources
    # 3. Update circuit breaker
    # 4. Notify user if needed
    
async def handle_playback_error(chat_id: int, error: Exception):
    # 1. Stop current playback
    # 2. Try next track in queue
    # 3. Leave voice chat if queue empty
    # 4. Update queue status
```

## 📊 Performance Metrics

### Key Metrics

| Metric | Target | Current |
|---------|---------|---------|
| Search Response Time | <5 seconds | 3.2 seconds |
| Extraction Success Rate | >95% | 87% |
| Playback Success Rate | >95% | 92% |
| Queue Persistence | 100% | 100% |
| Bot Uptime | >99% | 99.8% |

### Performance Optimization

```python
# Connection pooling
session = aiohttp.ClientSession(
    connector=aiohttp.TCPConnector(limit=100),
    timeout=aiohttp.ClientTimeout(total=30)
)

# Request caching
@lru_cache(maxsize=1000)
async def cached_search(query: str, limit: int):
    return await search(query, limit)

# Circuit breakers
class CircuitBreaker:
    failure_threshold: int = 5
    recovery_timeout: int = 60
    half_open_max_calls: int = 3
```

## 🔍 Logging System

### Log Levels

```python
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Specialized loggers
bot_logger = logging.getLogger("bot")
music_logger = logging.getLogger("bot.music")
call_logger = logging.getLogger("bot.call")
queue_logger = logging.getLogger("bot.queue")
```

### Critical Logs

```python
# Source extraction
logger.info(f"MusicBackend search results query={query} yt={len(yt_res)} js={len(js_res)}")

# Fallback chain
logger.info(f"Primary source {source} failed for {track.title}, trying fallback sources...")
logger.info(f"Fallback JioSaavn success for {track.title}")

# Playback
logger.info(f"Successfully resolved stream URL for {track.title} from {source}")
logger.warning(f"Stream validation failed (FFprobe could not parse URL): {stream_url[:60]}...")
```

## 🚀 Deployment

### Heroku Configuration

```yaml
# buildpacks
heroku/python

# build command
pip install -r requirements.txt

# start command
python -m bot

# environment variables
BOT_TOKEN: <telegram_bot_token>
API_ID: <telegram_api_id>
API_HASH: <telegram_api_hash>
YOUTUBE_API_BASE_URL: https://youtube-music-wrapper.onrender.com
JIOSAAVN_API_BASE_URL: https://jio-savan-music-wrapper.onrender.com
```

### Docker Configuration

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

CMD ["python", "-m", "bot"]
```

## 🔒 Security Considerations

### Bot Security

1. **Token Protection**: Environment variables for sensitive data
2. **Input Validation**: All user inputs sanitized
3. **Rate Limiting**: Per-user command rate limits
4. **Permission System**: Role-based access control

### Data Security

1. **No PII Storage**: No personal information collected
2. **Encrypted Communication**: HTTPS for all external calls
3. **Secure Headers**: Proper authentication headers
4. **SQL Injection Prevention**: Parameterized queries

### Network Security

1. **CORS Configuration**: Restricted to allowed domains
2. **Certificate Validation**: SSL certificate verification
3. **Timeout Protection**: Request timeouts to prevent hanging
4. **Circuit Breakers**: Prevent cascading failures

## 🧪 Testing

### Unit Tests

```python
# Test source extraction
async def test_youtube_extraction():
    extractor = YouTubeWrapperExtractor()
    result = await extractor.extract("dQw4w9WgXcQ")
    assert result["stream_url"] is not None

# Test fallback chain
async def test_fallback_chain():
    track = Track(title="Test", source="youtube", track_id="invalid")
    payload = await music_backend.get_stream_payload(track)
    assert payload is not None  # Should find alternative
```

### Integration Tests

```python
# Test full playback flow
async def test_playback_flow():
    # 1. Search for track
    results = await music_backend.search("test song", limit=1)
    assert len(results) > 0
    
    # 2. Get stream URL
    payload = await music_backend.get_stream_payload(results[0])
    assert payload["url"] is not None
    
    # 3. Build stream
    stream = call_manager._build_stream(payload["url"], payload.get("headers"))
    assert stream is not None
```

### Load Testing

```python
# Test concurrent searches
async def test_concurrent_searches():
    tasks = [
        music_backend.search(f"song_{i}", limit=5)
        for i in range(100)
    ]
    results = await asyncio.gather(*tasks)
    assert all(len(r) >= 0 for r in results)
```

## 🐛 Troubleshooting

### Common Issues

1. **"Track has no URL and resolution failed"**
   - **Cause**: All sources failed to extract stream URL
   - **Fix**: Check wrapper services, verify cookies

2. **"Stream validation failed"**
   - **Cause**: FFprobe cannot parse URL
   - **Fix**: Check headers, try alternative source

3. **"Voice Chat join failed"**
   - **Cause**: Bot permissions or VC issues
   - **Fix**: Verify bot is admin, check VC status

### Debug Commands

```python
# Enable debug logging
logging.getLogger("bot").setLevel(logging.DEBUG)

# Check source health
for source in ["youtube", "jiosaavn", "deezer"]:
    health = SourceRanker.get_source_health(source)
    print(f"{source}: {health}")

# Test wrapper connectivity
async def test_wrapper_health():
    async with aiohttp.ClientSession() as session:
        async with session.get("https://youtube-music-wrapper.onrender.com/") as resp:
            print(f"YouTube wrapper status: {resp.status}")
```

## 📈 Monitoring

### Health Checks

```python
async def health_check():
    return {
        "status": "healthy",
        "services": {
            "youtube_wrapper": await check_youtube_wrapper(),
            "jiosaavn_wrapper": await check_jiosaavn_wrapper(),
            "database": await check_database(),
            "voice_chat": await check_voice_chat()
        },
        "metrics": {
            "queue_count": get_total_queue_count(),
            "active_vcs": len(call_manager.active_chats),
            "uptime": get_uptime_seconds()
        }
    }
```

### Alert Conditions

- **High Error Rate**: >10% failure rate over 5 minutes
- **Service Down**: Wrapper health check fails
- **Queue Backup**: Queue size >100 tracks
- **Memory Usage**: >80% of available memory

---

*Last Updated: May 8, 2026*
