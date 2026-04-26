# System Requirements

## Required System Dependencies

### FFmpeg (CRITICAL)

**FFmpeg MUST be installed on the host operating system.** This is required for py-tgcalls to transcode audio streams.

While NTgCalls (used by py-tgcalls v2.x) handles internal FFmpeg routing, the bot passes custom FFmpeg parameters (like audio filters) which require FFmpeg to be available at the system level.

#### Installation

**Ubuntu/Debian:**
```bash
sudo apt-get update
sudo apt-get install ffmpeg
```

**CentOS/RHEL/Fedora:**
```bash
sudo yum install ffmpeg
# or
sudo dnf install ffmpeg
```

**macOS:**
```bash
brew install ffmpeg
```

**Windows:**
1. Download from https://ffmpeg.org/download.html
2. Add to PATH environment variable

**Docker:**
FFmpeg is already included in the provided Dockerfile:
```dockerfile
RUN apt-get update && apt-get install -y \
    ffmpeg \
    build-essential \
    libssl-dev \
    libffi-dev \
    python3-dev
```

**Heroku:**
Add the FFmpeg buildpack:
```bash
heroku buildpacks:add --index 1 https://github.com/jonathanong/heroku-buildpack-ffmpeg-latest.git
```

**Railway:**
FFmpeg is pre-installed in Railway's environment.

### Verification

Check FFmpeg installation:
```bash
ffmpeg -version
```

## Python Dependencies

All Python packages are listed in `requirements.txt`. Key dependencies include:

- `pyrogram` - Telegram client library
- `py-tgcalls` - Voice chat streaming (requires system FFmpeg)
- `yt-dlp` - Media extraction from various platforms
- `pydantic` - Configuration management
- `motor` / `pymongo` - MongoDB async driver

Install with:
```bash
pip install -r requirements.txt
```

## Telegram Requirements

### Bot Account
- Create a bot via @BotFather
- Obtain BOT_TOKEN

### Userbot Account (Assistant)
- A real Telegram user account (not a bot)
- Must be promoted to **Administrator** in groups where voice chat is used
- Required permission: **"Manage Video Chats"**

To set permissions:
1. Go to Group → Administrators → Add Administrator
2. Select the Assistant account
3. Enable "Manage Video Chats" permission

## Database Options

Choose one of the following:

1. **MongoDB** (Recommended) - Set `MONGO_URI`
2. **Redis** - Set `REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD`
3. **Supabase** - Set `SUPABASE_URL`, `SUPABASE_KEY`
4. **SQLite** - Fallback option (no configuration needed)

## Troubleshooting

### "No active Voice Chat was found" Error
- Ensure the Assistant userbot is an admin with "Manage Video Chats" permission
- The bot cannot create voice chats without this permission

### Streams fail to play / silent hang
- Verify FFmpeg is installed: `ffmpeg -version`
- Check bot logs for FFmpeg errors
- Ensure stream URLs are valid HTTP/HTTPS (not vk:// or deezer:// pseudo-protocols)

### Extractors failing to load
- Check logs for missing dependencies (yt-dlp is now included in requirements.txt)
- Run `pip install -r requirements.txt` to ensure all packages are installed
