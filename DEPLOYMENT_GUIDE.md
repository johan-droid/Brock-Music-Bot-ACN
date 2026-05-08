# Music Bot System - Complete Deployment & Configuration Guide

## 📋 Overview

This guide covers deployment and configuration for the complete music bot system including wrappers, core bot, and infrastructure.

## 🚀 Deployment Platforms

### Render.com (Recommended)

#### Prerequisites
- Render.com account
- GitHub repository
- Domain (optional)

#### Services Required

1. **Music Bot Core** (Heroku/Render)
2. **YouTube Wrapper** (Render)
3. **JioSaavn Wrapper** (Render)

#### Environment Setup

##### Music Bot Core
```yaml
# Environment Variables
BOT_TOKEN: <telegram_bot_token>
API_ID: <telegram_api_id>
API_HASH: <telegram_api_hash>
YOUTUBE_API_BASE_URL: https://youtube-music-wrapper.onrender.com
JIOSAAVN_API_BASE_URL: https://jio-savan-music-wrapper.onrender.com
AUDIO_QUALITY: high
AUDIO_BITRATE: 192
DATABASE_URL: bot.db

# Build Settings
Buildpacks: heroku/python
Build Command: pip install -r requirements.txt
Start Command: python -m bot
```

##### YouTube Wrapper
```yaml
# Environment Variables
PORT: 10000
YOUTUBE_COOKIES: <netscape_cookie_content>

# Build Settings
Build Command: npm install && pip install -r requirements.txt
Start Command: node index.js
```

##### JioSaavn Wrapper
```yaml
# Environment Variables
PORT: 10000

# Build Settings
Build Command: npm install
Start Command: node index.js
```

### Heroku Alternative

#### Music Bot Core on Heroku
```bash
# Create app
heroku create your-music-bot

# Set environment variables
heroku config:set BOT_TOKEN=<token>
heroku config:set API_ID=<id>
heroku config:set API_HASH=<hash>
heroku config:set YOUTUBE_API_BASE_URL=https://youtube-music-wrapper.onrender.com
heroku config:set JIOSAAVN_API_BASE_URL=https://jio-savan-music-wrapper.onrender.com

# Deploy
git subtree push --prefix bot heroku main
```

### Docker Deployment

#### Docker Compose
```yaml
version: '3.8'

services:
  music-bot:
    build: .
    environment:
      - BOT_TOKEN=${BOT_TOKEN}
      - API_ID=${API_ID}
      - API_HASH=${API_HASH}
      - YOUTUBE_API_BASE_URL=http://youtube-wrapper:10000
      - JIOSAAVN_API_BASE_URL=http://jiosaavn-wrapper:10000
    depends_on:
      - youtube-wrapper
      - jiosaavn-wrapper
    networks:
      - music-bot-network

  youtube-wrapper:
    build: ./youtube-wrapper
    environment:
      - PORT=10000
      - YOUTUBE_COOKIES=${YOUTUBE_COOKIES}
    networks:
      - music-bot-network

  jiosaavn-wrapper:
    build: ./jiosaavn-wrapper
    environment:
      - PORT=10000
    networks:
      - music-bot-network

networks:
  music-bot-network:
    driver: bridge
```

#### Dockerfile (Music Bot)
```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create non-root user
RUN useradd --create-home --shell /bin/bash app
USER app

# Expose port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Start command
CMD ["python", "-m", "bot"]
```

## ⚙️ Configuration

### Core Bot Configuration

#### Bot Token Setup
1. **Create Telegram Bot**
   - Talk to @BotFather on Telegram
   - `/newbot` → Name bot
   - Get token and username

2. **Get API Credentials**
   - Go to https://my.telegram.org/apps
   - Create app → Get API ID and Hash

#### Environment Variables
```bash
# Required
export BOT_TOKEN="123456:ABC-DEF"
export API_ID="12345678"
export API_HASH="abcdef123456789"

# Optional
export AUDIO_QUALITY="high"  # low/medium/high/ultra
export AUDIO_BITRATE="192"   # 64-320 kbps
export DATABASE_URL="bot.db"  # SQLite path
```

#### Source Configuration
```python
# bot/config.py
YOUTUBE_WRAPPER_URL = "https://youtube-music-wrapper.onrender.com"
JIOSAAVN_WRAPPER_URL = "https://jio-savan-music-wrapper.onrender.com"

# Source priorities (lower = better)
SOURCE_PRIORITIES = {
    "youtube": 1.0,
    "jiosaavn": 1.2,
    "deezer": 1.4,
    "vk": 1.5,
}
```

### YouTube Wrapper Configuration

#### Cookie Setup
1. **Export Cookies from Chrome**
   ```bash
   # Install extension
   # Go to youtube.com
   # Click extension → Export → Netscape format
   # Copy entire content
   ```

2. **Set Environment Variable**
   ```bash
   # Render Dashboard
   # YouTube Wrapper → Environment → Add Variable
   # Name: YOUTUBE_COOKIES
   # Value: <paste cookie content>
   ```

3. **Cookie Format Validation**
   ```
   # Must start with:
   # Netscape HTTP Cookie File
   
   # Must contain:
   .youtube.com	TRUE	/	TRUE	1735689600	SAPISID	<value>
   .youtube.com	TRUE	/	TRUE	1735689600	__Secure-3PSID	<value>
   ```

### JioSaavn Wrapper Configuration

#### API Configuration
```javascript
// index.js
const JIOSAAVN_API_BASE = 'https://www.jiosaavn.com/api.php';

// No authentication required
// Rate limiting handled internally
```

#### URL Decryption
```javascript
// Automatic decryption of encrypted URLs
function decryptJioSaavnUrl(encryptedUrl) {
  // Base64 decode → quality upgrade → HTTPS
  // Falls back to preview if fails
}
```

## 🔌 SSL/HTTPS Setup

### Custom Domain Setup

#### Cloudflare (Recommended)
1. **Add Domain to Cloudflare**
   - DNS → Add domain
   - Point to Render IP

2. **SSL Certificate**
   - Enable SSL/TLS encryption mode
   - Full (strict) mode recommended

3. **Bot Webhook Setup**
   ```python
   # Update bot configuration
   app = Client(
       "bot_token",
       api_id=api_id,
       api_hash=api_hash,
       webhook_url="https://yourdomain.com/webhook"
   )
   ```

#### Self-Signed Certificate
```bash
# Generate SSL certificate
openssl req -x509 -newkey rsa:2048 -keyout key.pem -out cert.pem -days 365

# Configure bot with certificate
app = Client(
    "bot_token",
    api_id=api_id,
    api_hash=api_hash,
    webhook_url="https://yourdomain.com:8443/webhook",
    certificate="cert.pem",
    private_key="key.pem"
)
```

## 📊 Monitoring Setup

### Health Checks

#### Bot Health Endpoint
```python
@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
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

#### Wrapper Health Endpoints
```javascript
// YouTube Wrapper
app.get('/health', (req, res) => {
  res.json({
    status: 'healthy',
    service: 'youtube-music-wrapper',
    version: '1.0.0'
  });
});

// JioSaavn Wrapper
app.get('/health', (req, res) => {
  res.json({
    status: 'healthy',
    service: 'jiosaavn-music-wrapper',
    version: '1.0.0'
  });
});
```

### Logging Configuration

#### Structured Logging
```python
import logging
import json
from datetime import datetime

class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno
        }
        
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
            
        return json.dumps(log_entry)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bot.log")
    ]
)

logger = logging.getLogger("bot")
logger.handlers[0].setFormatter(JSONFormatter())
```

### Metrics Collection

#### Prometheus Metrics
```python
from prometheus_client import Counter, Histogram, Gauge

# Define metrics
search_counter = Counter('music_bot_searches_total', 'Total searches', ['source'])
playback_counter = Counter('music_bot_playbacks_total', 'Total playbacks', ['source'])
search_duration = Histogram('music_bot_search_duration_seconds', 'Search duration')
active_vcs = Gauge('music_bot_active_voice_chats', 'Active voice chats')

# Use metrics
@app.on_message(filters.command("play"))
async def play_command(client, message):
    search_counter.labels(source='youtube').inc()
    with search_duration.time():
        results = await search(message.text)
```

## 🔒 Security Configuration

### Environment Security

#### Secure Variables
```bash
# Use Render's encrypted environment variables
# Never commit secrets to git
# Rotate tokens regularly

# Required secrets
BOT_TOKEN=🔒
API_ID=🔒
API_HASH=🔒
YOUTUBE_COOKIES=🔒
```

#### Network Security
```python
# Configure secure headers
app = Client(
    "bot_token",
    api_id=api_id,
    api_hash=api_hash,
    in_memory=True,  # Don't save session
    drop_pending_updates=True,  # Ignore updates when offline
    max_concurrent_transmissions=5  # Rate limit
)
```

### Access Control

#### Admin System
```python
# bot/config.py
ADMINS = [123456789, 987654321]  # User IDs

# Permission decorator
def admin_required(func):
    async def wrapper(client, message):
        if message.from_user.id not in ADMINS:
            await message.reply("❌ Admin access required")
            return
        return await func(client, message)
    return wrapper

# Usage
@app.on_message(filters.command("admin") & admin_required)
async def admin_panel(client, message):
    await message.reply("🔧 Admin panel")
```

## 🔄 CI/CD Pipeline

### GitHub Actions

#### Automated Deployment
```yaml
# .github/workflows/deploy.yml
name: Deploy Music Bot

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install pytest
      - name: Run tests
        run: pytest tests/

  deploy:
    needs: test
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main'
    steps:
      - uses: actions/checkout@v3
      - name: Deploy to Render
        run: |
          curl -X POST \
            -H "Authorization: Bearer ${{ secrets.RENDER_API_KEY }}" \
            -H "Content-Type: application/json" \
            -d '{"serviceId": "srv-xxxxxxxx"}' \
            https://api.render.com/v1/services/srv-xxxxxxxx/deploys
```

### Testing Pipeline
```yaml
# .github/workflows/test.yml
name: Test Suite

on: [push, pull_request]

jobs:
  unit-tests:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: [3.9, 3.10, 3.11]
    
    steps:
      - uses: actions/checkout@v3
      - name: Set up Python ${{ matrix.python-version }}
        uses: actions/setup-python@v4
        with:
          python-version: ${{ matrix.python-version }}
      
      - name: Cache dependencies
        uses: actions/cache@v3
        with:
          path: ~/.cache/pip
          key: ${{ runner.os }}-pip-${{ hashFiles('**/requirements.txt') }}
      
      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install pytest pytest-cov
      
      - name: Run tests
        run: |
          pytest --cov=bot --cov-report=xml tests/
      
      - name: Upload coverage
        uses: codecov/codecov-action@v3
        with:
          file: ./coverage.xml
```

## 📈 Performance Optimization

### Caching Strategy

#### Redis Caching
```python
# bot/cache.py
import redis
import json
from typing import Optional

class RedisCache:
    def __init__(self):
        self.redis_client = redis.Redis(
            host='localhost',
            port=6379,
            decode_responses=True
        )
    
    async def get_search_results(self, query: str) -> Optional[List]:
        cached = self.redis_client.get(f"search:{query}")
        if cached:
            return json.loads(cached)
        return None
    
    async def set_search_results(self, query: str, results: List, ttl: int = 300):
        self.redis_client.setex(
            f"search:{query}",
            ttl,
            json.dumps(results)
        )
```

#### Memory Caching
```python
# bot/memory_cache.py
from functools import lru_cache
from datetime import datetime, timedelta

@lru_cache(maxsize=1000)
def cached_search(query: str, limit: int):
    # Cache search results in memory
    return search_function(query, limit)

# Cache invalidation
CACHE_TTL = timedelta(minutes=5)
last_cache_clear = datetime.now()

def should_clear_cache():
    global last_cache_clear
    return datetime.now() - last_cache_clear > CACHE_TTL
```

### Database Optimization

#### SQLite Optimization
```sql
-- Create indexes for performance
CREATE INDEX idx_queues_chat_id ON queues(chat_id);
CREATE INDEX idx_track_history_chat_id ON track_history(chat_id);
CREATE INDEX idx_track_history_played_at ON track_history(played_at);

-- Optimize queue queries
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA cache_size = 10000;
```

## 🐛 Troubleshooting Deployment

### Common Issues

#### Bot Not Starting
```bash
# Check logs
heroku logs --tail

# Verify environment variables
heroku config:get BOT_TOKEN
heroku config:get API_ID
heroku config:get API_HASH

# Test bot token
curl -X POST "https://api.telegram.org/bot<token>/getMe"
```

#### Wrapper Connection Issues
```bash
# Test wrapper health
curl https://youtube-music-wrapper.onrender.com/
curl https://jio-savan-music-wrapper.onrender.com/

# Check network connectivity
ping youtube-music-wrapper.onrender.com
ping jio-savan-music-wrapper.onrender.com

# Test with curl
curl -v "https://youtube-music-wrapper.onrender.com/search?q=test"
```

#### SSL Certificate Issues
```bash
# Check certificate
openssl s_client -connect yourdomain.com:443 -servername yourdomain.com

# Test webhook
curl -X POST \
  -H "Content-Type: application/json" \
  -d '{"update_id": 0}' \
  https://yourdomain.com/webhook

# Check Cloudflare status
curl -I https://yourdomain.com
```

### Debug Mode

#### Enable Debug Logging
```bash
# Set environment variable
export LOG_LEVEL=DEBUG

# Or in code
import logging
logging.getLogger().setLevel(logging.DEBUG)
```

#### Health Monitoring
```bash
# Monitor bot status
watch -n 5 'curl -s https://yourdomain.com/health | jq'

# Monitor wrapper services
watch -n 10 'curl -s https://youtube-music-wrapper.onrender.com/ && echo "YouTube OK"'
watch -n 10 'curl -s https://jio-savan-music-wrapper.onrender.com/ && echo "JioSaavn OK"'
```

## 📋 Deployment Checklist

### Pre-Deployment
- [ ] Bot token configured
- [ ] API credentials set
- [ ] Wrapper URLs configured
- [ ] Database initialized
- [ ] SSL certificates ready
- [ ] Domain DNS configured
- [ ] Environment variables set
- [ ] Health endpoints working
- [ ] Tests passing

### Post-Deployment
- [ ] Health checks passing
- [ ] Bot responding to commands
- [ ] Music search working
- [ ] Voice chat joining
- [ ] Playback functioning
- [ ] Queue system working
- [ ] Error monitoring active
- [ ] Performance metrics collected
- [ ] Backup strategy in place

---

*Last Updated: May 8, 2026*
