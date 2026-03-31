# 🎵 Telegram Music Bot

A high-quality music streaming bot for Telegram Video Chats (formerly Voice Chats) with smart title detection, zero-cost deployment options, and professional audio quality.

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Docker](https://img.shields.io/badge/docker-ready-green.svg)](https://www.docker.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## ✨ Features

### � Audio Quality (Telegram 2025 Optimized)
- **Professional-grade audio**: Opus codec at 48kHz stereo
- **4 quality tiers**: Standard (128kbps), High (192kbps), Premium (256kbps), Lossless (320kbps)
- **EBU R128 loudness normalization** for consistent volume
- **FFmpeg audio filters**: Dynamic range compression, high-pass filter, limiter

### 🎵 Smart Music Discovery
- **Multi-platform support**: YouTube Music, YouTube, JioSaavn, SoundCloud, Audiomack, Spotify, Telegram files
- **Optimized Search Waterfall**: Parallel search across all platforms (YT Music > YouTube > JioSaavn > SoundCloud > Audiomack)
- **Smart title detection**: Handles Cyrillic (Russian) text and similar titles
- **Conflict resolution**: Shows selection options when multiple matches are found
- **High-quality extraction**: Prioritizes 320kbps streams (JioSaavn/YTM) and Opus codecs

### 👥 Enhanced Permissions
- **VC participant access**: `/play` now works for Video Chat participants (not just admins)
- **Multi-tier system**: Owner (5) → Sudo (4) → Admin (3) → VC Participant (2) → User (1)
- **Admin-only controls**: Pause, skip, stop, volume for admins only
- **Global bans**: Ban users across all groups

### 🚀 Zero-Cost Deployment
- **No external services required**: SQLite database + cache (no Redis/MongoDB needed)
- **Free cloud deployment**: Railway, Render, Fly.io, Oracle Cloud Free Tier
- **Optional backends**: MongoDB Atlas, Redis, or Supabase if preferred
- **Docker support**: Single container with everything included

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
- **SESSION_STRING**: Run userbot session generator (see below)

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
SESSION_STRING_1=your_session_string
OWNER_ID=your_telegram_user_id

# For zero-cost deployment (optional external services)
# Leave empty to use SQLite
MONGO_URI=
REDIS_HOST=
```

### 3. Deploy

**Option A: Docker (Recommended)**
```bash
docker-compose up -d
```

**Option B: Direct Python**
```bash
pip install -r requirements.txt
python -m bot
```

**Option C: Free Cloud (Railway/Render/Fly.io)**
See [DEPLOYMENT.md](DEPLOYMENT.md) for platform-specific instructions.

## 🎮 Commands

### Playback (Admin & VC Participants)
| Command | Description | Permission |
|---------|-------------|------------|
| `/play <query>` | Play song or add to queue | Admin / VC Participant |
| `/vplay <query>` | Play with video (if supported) | Admin |
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
│   ├── plugins/        # Command handlers (/play, /pause, etc.)
│   ├── platforms/      # YouTube Music, YouTube, JioSaavn, SoundCloud, Audiomack
│   └── utils/          # Database, cache, permissions, audio config
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
                       ┌─────────────────┐
                       │ py-tgcalls 2.x  │
                       │  NTgCalls 1.2   │
                       │  (Userbot VC)   │
                       └─────────────────┘
                                │
                                ▼
                       ┌─────────────────┐
                       │     FFmpeg      │
                       │ PCM s16le 48kHz │
                       │   Opus 192kbps  │
                       │  + Loudnorm     │
                       └─────────────────┘
```

## � Development

### Update .gitignore
- Added `bot/.env.local` to avoid leaking local credentials.
- Added `.pytest_cache/` to ignore test runtime cache.
- Keep existing ignored files: `__pycache__`, `.env`, `sessions`, `*.log`, `mongo-data`, `redis-data`.

### Local run checklist
1. Install deps: `pip install -r requirements.txt`
2. Run healthy CI commands: `flake8`, `pytest`.
3. Verify startup imports: `python -c "from bot import db, call_manager, bot_client"`.

## �🔄 Migration Guide

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
- **JioSaavn issues**: The bot uses `-user_agent` and `-referer` flags to bypass CDN blocks. If you still hear silence, ensure your server IP is not globally banned by JioSaavn.
- Check FFmpeg is installed: `ffmpeg -version`
- Verify session string is valid

### High CPU usage
- Reduce `AUDIO_QUALITY` to `standard` or `high`
- Lower `concurrent_fragments` in `bot/platforms/youtube.py`
- Use SQLite instead of MongoDB for small deployments

### Database locked errors (SQLite)
- This happens with high concurrency
- Switch to MongoDB Atlas free tier for production

## 📜 License

MIT License - See [LICENSE](LICENSE) file for details.

## 🙏 Credits

- [Pyrogram](https://github.com/pyrogram/pyrogram) - Telegram MTProto client
- [py-tgcalls](https://github.com/pytgcalls/pytgcalls) - Video Chat streaming
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) - Media extraction
- [NTgCalls](https://github.com/telegramdesktop/tdesktop) - Native Telegram calls

---

**Made with ❤️ for the Telegram community**

