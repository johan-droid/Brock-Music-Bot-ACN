# 🎵 VK Music Bot

A VK-first Telegram music bot with a shared FastAPI resolver, smart title detection, zero-cost deployment options, and professional audio quality.

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Docker](https://img.shields.io/badge/docker-ready-green.svg)](https://www.docker.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## ✨ Features

### 🎵 Audio Quality (Telegram 2025 Optimized)
- **Professional-grade audio**: Opus codec at 48kHz stereo
- **4 quality tiers**: Standard (128kbps), High (192kbps), Premium (256kbps), Lossless (320kbps)
- **EBU R128 loudness normalization** for consistent volume
- **FFmpeg audio filters**: Dynamic range compression, high-pass filter, limiter

### 🎵 VK + Deezer Aggregation
- **Shared backend**: FastAPI resolver exposes the same search/resolve path used by the bot.
- **Priority search order**: VK → Deezer, with cache reuse.
- **Token rotation**: Deezer access is health-scored to reduce token block risk.
- **Direct stream resolution**: Playback normalizes to stream URLs before VC streaming.
- **Telegram native**: Direct streaming support for Telegram audio files.

### 👥 Enhanced Permissions
- **VC participant access**: `/play` now works for Video Chat participants (not just admins)
- **Multi-tier system**: Owner (5) → Sudo (4) → Admin (3) → VC Participant (2) → User (1)
- **Admin-only controls**: Pause, skip, stop, volume for admins only
- **Global bans**: Ban users across all groups

### 🚀 Zero-Cost Deployment
- **No external services required**: SQLite database + cache (no Redis/MongoDB needed)
- **Free cloud deployment**: Railway, Render, Fly.io, Oracle Cloud Free Tier
- **Optional backends**: MongoDB Atlas, Redis, or Supabase if preferred
- **Docker support**: Bot and backend services can run together in compose

### 📊 Database Options
| Option | Cost | Best For |
|--------|------|----------|
| **SQLite** | Free | Zero-cost deployment, personal use |
| **MongoDB Atlas** | Free tier | Production, high concurrency |
| **Supabase** | Free tier | PostgreSQL with real-time features |

## 🚀 Quick Start

### 1. Get API Credentials

- **API_ID & API_HASH**: https://my.telegram.org
- **BOT_TOKEN**: Message @BotFather on Telegram
- **USERBOT SESSION**: Use one of `SESSION_FILE_PATH_1`, `SESSION_FILE_B64_1`, or `SESSION_STRING_1`

### 2. Configure Environment

```bash
# Clone repository
git clone https://github.com/johan-droid/Music-Bot.git
cd Music-Bot

# Copy environment template
cp .env.example .env

# Edit .env with your credentials
nano .env
```

**Required minimum `.env`:**
```bash
API_ID=your_api_id
API_HASH=your_api_hash
BOT_TOKEN=your_bot_token
# Preferred production auth (choose one):
SESSION_FILE_B64_1=your_base64_encoded_session_file
# SESSION_FILE_PATH_1=/app/sessions/userbot_1.session
# SESSION_STRING_1=your_session_string
OWNER_ID=your_telegram_user_id

# For zero-cost deployment (optional external services)
# Leave empty to use SQLite
MONGO_URI=
REDIS_HOST=

# Optional VK/Deezer backend settings
VK_API_BASE_URL=
VK_API_TOKEN=
VK_SEARCH_PATH=/search
VK_RESOLVE_PATH=/resolve
DEEZER_TOKENS=
DEEZER_RESOLVE_URL=
```

### 3. Deploy

**Option A: Docker (Recommended)**
```bash
docker-compose up -d
```

This starts both the Telegram bot and the shared FastAPI backend.

**Option B: Direct Python**
```bash
pip install -r requirements.txt
python -m bot
```

To run the backend separately:
```bash
uvicorn vk_music_backend:app --host 0.0.0.0 --port 8000
```

**Option C: Free Cloud (Railway/Render/Fly.io)**
See [DEPLOYMENT.md](DEPLOYMENT.md) for platform-specific instructions.

**Option D: Heroku (Container Registry)**
```bash
heroku login
heroku create your-app-name
heroku container:login
heroku container:push worker -a your-app-name
heroku container:release worker -a your-app-name
heroku ps:scale worker=1 -a your-app-name
heroku config:set API_ID=your_api_id API_HASH=your_api_hash BOT_TOKEN=your_bot_token OWNER_ID=your_telegram_user_id SESSION_STRING_1="your_session_string_1"
```
Heroku automatically provides `PORT` to the container, and the bot starts a health server on that port.

## 🎮 Commands

### Playback (Admin & VC Participants)
| Command | Description | Permission |
|---------|-------------|------------|
| `/play <query or URL>` | Play song or add to queue | Admin / VC Participant |
| `/vplay <query>` | Play a VK or Deezer track from a URL or search | Admin |
| `/pause` | Pause playback | Admin |
| `/resume` | Resume playback | Admin |
| `/skip` | Skip to next song | Admin |
| `/stop` | Stop and clear queue | Admin |
| `/seek <seconds>` | Seek to position | Admin |
| `/volume <1-200>` | Adjust volume | Admin |
| `/replay` | Replay current song | Admin |

### Queue Management
| Command | Description |
|---------|-------------|
| `/queue` | Show current queue |
| `/clearqueue` | Clear all songs |
| `/shuffle` | Shuffle queue order |
| `/loop [off/track/queue]` | Enable looping |
| `/move <from> <to>` | Move song position |
| `/remove <position>` | Remove specific song |

### Admin Commands
| Command | Description | Permission |
|---------|-------------|------------|
| `/addsudo <user>` | Grant sudo access | Owner |
| `/delsudo <user>` | Revoke sudo | Owner |
| `/sudolist` | List sudo users | Sudo+ |
| `/gban <user>` | Global ban | Sudo+ |
| `/ungban <user>` | Remove global ban | Sudo+ |
| `/block <user>` | Ban from group | Admin+ |
| `/unblock <user>` | Unban from group | Admin+ |
| `/stats` | Bot statistics | Sudo+ |
| `/broadcast <msg>` | Broadcast to all groups | Owner |
| `/maintenance [on/off]` | Maintenance mode | Owner |
| `/restart` | Restart bot | Owner |

## 🔧 Configuration

### Audio Quality Settings

Add to `.env`:
```bash
# Audio quality: standard, high, premium, lossless
AUDIO_QUALITY=high
AUDIO_BITRATE=192
AUDIO_LOUDNORM=true
```

### Database Selection

**SQLite (Zero-cost):**
```bash
MONGO_URI=
REDIS_HOST=
SQLITE_CACHE_PATH=./data/cache.db
SQLITE_DB_PATH=./data/bot.db
```

**MongoDB Atlas:**
```bash
MONGO_URI=mongodb+srv://user:pass@cluster.mongodb.net/musicbot
```

**Supabase:**
```bash
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-service-role-key
```

## 📁 Project Structure

```
Music-Bot/
├── bot/
│   ├── core/           # Bot, Userbot, Video Chat (py-tgcalls)
│   │   └── music_backend.py  # Shared bot-side aggregator
│   ├── plugins/        # Command handlers (/play, /pause, etc.)
│   ├── platforms/      # VK and Deezer extractors
│   └── utils/          # Database, cache, permissions, audio config
├── vk_music_backend.py # FastAPI backend service / provider API
├── config.py           # Pydantic settings
├── requirements.txt    # Python dependencies
├── docker-compose.yml  # Docker orchestration
├── Dockerfile          # Container build
├── migrate_to_supabase.py  # MongoDB → Supabase migration
├── DEPLOYMENT.md       # Deployment guide
└── README.md           # This file
```

## 🏗 Architecture

```
┌─────────────────┐      ┌─────────────────┐      ┌─────────────────┐
│  Telegram API   │◄────►│   Bot Client    │◄────►│  SQLite/Redis   │
│                 │      │   (Pyrogram)    │      │    (Cache)      │
└─────────────────┘      └─────────────────┘      └─────────────────┘
                                │
                                ▼
                       ┌─────────────────┐      ┌────────────────────┐
                       │ py-tgcalls 2.x  │◄────►│  Core backend       │
                       │  NTgCalls 1.2   │      │  VK + Deezer + cache│
                       │  (Userbot VC)   │      └────────────────────┘
                                │
                                ▼
                       ┌─────────────────┐
                       │     FFmpeg      │
                       │ PCM s16le 48kHz │
                       │   Opus 192kbps  │
                       │  + Loudnorm     │
                       └─────────────────┘
```

## Development

### Update .gitignore
- Added `bot/.env.local` to avoid leaking local credentials.
- Added `.pytest_cache/` to ignore test runtime cache.
- Keep existing ignored files: `__pycache__`, `.env`, `sessions`, `*.log`, `mongo-data`, `redis-data`.

### Local run checklist
1. Install deps: `pip install -r requirements.txt`
2. Run healthy CI commands: `flake8`, `pytest`.
3. Verify startup imports: `python -c "from bot import db, call_manager, bot_client"`.

## Migration Guide

### MongoDB → Supabase
```bash
# 1. Set environment variables
export MONGO_URI=mongodb+srv://...
export SUPABASE_URL=https://...
export SUPABASE_KEY=...

# 2. Run migration
python migrate_to_supabase.py
```

## 🐳 Docker Deployment

```bash
# Build and run
docker-compose up -d

# View logs
docker logs -f musicbot

# Stop
docker-compose down
```

## 🌐 Free Cloud Deployment

| Platform | Cost | Best For |
|----------|------|----------|
| **Railway** | $5/mo credit | No idle timeout |
| **Render** | Free | Simple setup (15min idle) |
| **Fly.io** | Free (3 VMs) | Good performance |
| **Oracle Cloud** | Always Free | 24/7 operation |

See [DEPLOYMENT.md](DEPLOYMENT.md) for detailed instructions.

## 🛠 Troubleshooting

### CI / local test workflow
- Install dependencies:
  - `python -m pip install --upgrade pip`
  - `pip install -r requirements.txt`
  - `pip install flake8 pytest`
- Run linters:
  - `flake8 bot --count --select=E9,F63,F7,F82 --show-source --statistics`
  - `flake8 bot --count --exit-zero --max-complexity=10 --max-line-length=127 --statistics`
- Validate config and core imports:
  - `python -c "from config import config; print('Config loaded')"`
  - `python -c "from bot.utils.title_detector import conflict_resolver; print('Title detector loaded')"`
  - `python -c "from bot import db, call_manager, bot_client; print('Bot imports OK')"`
- If you hit `ImportError: cannot import name 'Database'`, ensure `bot/utils/database.py` defines `class Database` and that `MongoDatabase` inherits from it.

### No audio in Video Chat
- Ensure userbot is admin with "Manage Video Chats" permission
- Check FFmpeg is installed: `ffmpeg -version`
- Verify session string is valid

### High CPU usage
- Reduce `AUDIO_QUALITY` to `standard` or `high`
- Use SQLite instead of MongoDB for small deployments

### Database locked errors (SQLite)
- This happens with high concurrency
- Switch to MongoDB Atlas free tier for production

## 📜 License

MIT License - See [LICENSE](LICENSE) file for details.

## 🙏 Credits

- [Pyrogram](https://github.com/pyrogram/pyrogram) - Telegram MTProto client
- [py-tgcalls](https://github.com/pytgcalls/pytgcalls) - Video Chat streaming
- [NTgCalls](https://github.com/telegramdesktop/tdesktop) - Native Telegram calls

---

**Made with ❤️ for the Telegram community**

