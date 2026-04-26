# System Requirements

## External API Microservice (CRITICAL)

The bot **requires an external API microservice** for VK and Deezer music extraction. The bot itself does NOT extract music natively - it delegates this to a separate service.

### VK/Deezer API Setup

The bot makes HTTP requests to an external API to:
1. Search for tracks (GET /search)
2. Resolve track IDs to direct stream URLs (POST /resolve)

**Required Environment Variables:**
```bash
# VK API Configuration
VK_API_BASE_URL=https://your-api-service.com    # URL of your API microservice
VK_API_TOKEN=your_token_here                      # Optional: if API requires auth
VK_SEARCH_PATH=/search                           # API search endpoint path
VK_RESOLVE_PATH=/resolve                         # API resolve endpoint path
VK_TOKEN_HEADER=Authorization                    # Header name for token

# Deezer Configuration
DEEZER_API_BASE_URL=https://api.deezer.com      # Default Deezer public API
DEEZER_TOKENS=token1,token2,token3              # Optional: for rate limit rotation
```

**If VK_API_BASE_URL is empty:**
- VK search returns empty results immediately
- VK track extraction fails silently
- The bot falls back to other music sources (if configured)

### Setting Up the API Microservice

You need to deploy or host a separate service that:
1. Accepts search queries and returns track metadata
2. Accepts track IDs and returns direct HTTP stream URLs (NOT vk:// pseudo-URLs)
3. Returns URLs that FFmpeg can actually play (http:// or https://)

**Example API Response Format:**
```json
{
  "items": [
    {
      "id": "12345",
      "title": "Song Name",
      "artist": "Artist Name",
      "duration": 180,
      "stream_url": "https://actual-cdn.com/file.mp3",
      "thumbnail": "https://cdn.com/cover.jpg"
    }
  ]
}
```

**Important:** The API must return real HTTP/HTTPS URLs. Do NOT return vk:// or deezer:// pseudo-protocols - FFmpeg cannot read these and will crash.

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

### VK/Deezer Search Returns Empty Results
- **Check VK_API_BASE_URL is set** - If empty, VK extractor immediately returns []
- **Verify API microservice is running** - The bot delegates extraction to external API
- **Check API token** - If API requires auth, set VK_API_TOKEN correctly
- **Check logs** - Look for "Failed to load VK extractor" errors

### "Invalid stream URL" Error / FFmpeg Crashes
- **Ensure API returns HTTP/HTTPS URLs** - vk:// and deezer:// are NOT valid for FFmpeg
- **Check URL validation** - Only http:// and https:// are allowed (configured in call.py)
- **Verify FFmpeg is installed** - Run `ffmpeg -version` on the server

### "No active Voice Chat was found" Error
- Ensure the Assistant userbot is an admin with "Manage Video Chats" permission
- The bot cannot create voice chats without this permission

### Streams fail to play / silent hang
- Verify FFmpeg is installed: `ffmpeg -version`
- Check bot logs for FFmpeg errors
- Ensure stream URLs are valid HTTP/HTTPS (not vk:// or deezer:// pseudo-protocols)

### Extractors failing to load
- Check logs for "Failed to load VK extractor: ..." or "Failed to load Deezer extractor: ..."
- Ensure all dependencies are installed: `pip install -r requirements.txt`
- yt-dlp is now included in requirements.txt for media extraction
