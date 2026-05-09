# YouTube Music Wrapper - Technical Documentation

## 📋 Overview

The YouTube Music Wrapper is a Node.js/Express service that provides REST API endpoints for YouTube music extraction using yt-dlp with cookie-based authentication.

## 🏗️ Architecture

### Core Components

- **Express.js Server** - REST API framework
- **yt-dlp** - YouTube video/audio extraction engine
- **Cookie Authentication** - Bypasses bot detection and geo-restrictions
- **FFmpeg Integration** - Audio format conversion and optimization
- **Circuit Breaker** - Prevents cascading failures

### Dependencies

```json
{
  "express": "^4.18.2",
  "cors": "^2.8.5",
  "yt-dlp": "^2024.1.1",
  "child_process": "built-in",
  "fs": "built-in",
  "path": "built-in"
}
```

## 🔌 API Endpoints

### Health Check
```
GET /
```
**Response:**
```json
{
  "status": "healthy",
  "service": "youtube-music-wrapper",
  "version": "1.0.0"
}
```

### Search
```
GET /search?q={query}&limit={limit}
```
**Parameters:**
- `q` (required): Search query string
- `limit` (optional, default: 5): Maximum results (1-20)

**Response:**
```json
{
  "data": [
    {
      "id": "dQw4w9WgXcQ",
      "title": "Rick Astley - Never Gonna Give You Up",
      "artist": "Rick Astley",
      "duration": 213,
      "thumbnail": "https://i.ytimg.com/vi/dQw4w9WgXcQ/mqdefault.jpg",
      "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    }
  ],
  "total": 1,
  "query": "rick roll"
}
```

### Track Extraction
```
GET /track/{videoId}
```
**Parameters:**
- `videoId` (required): 11-character YouTube video ID

**Response:**
```json
{
  "id": "dQw4w9WgXcQ",
  "title": "Rick Astley - Never Gonna Give You Up",
  "artist": {
    "name": "Rick Astley"
  },
  "duration": 213,
  "stream_url": "https://rr3---sn-nx57ynsr.googlevideo.com/videoplayback?...",
  "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
  "thumbnail": "https://i.ytimg.com/vi/dQw4w9WgXcQ/maxresdefault.jpg",
  "source": "youtube"
}
```

### Full URL Extraction
```
GET /extract?url={youtubeUrl}
```
**Parameters:**
- `url` (required): Full YouTube video URL

**Response:** Same format as `/track/{videoId}`

## 🔐 Authentication System

### Cookie-Based Authentication

The wrapper uses YouTube cookies to bypass bot detection and geo-restrictions:

#### Cookie Sources
1. **Environment Variable** (Primary)
   ```
   YOUTUBE_COOKIES=<netscape_cookie_content>
   ```

2. **File-Based** (Fallback)
   ```
   cookies.txt (Netscape format)
   ```

#### Cookie Format
```
# Netscape HTTP Cookie File
.youtube.com	TRUE	/	FALSE	1735689600	SAPISID	<value>
.youtube.com	TRUE	/	TRUE	1735689600	__Secure-3PSID	<value>
```

#### Required Cookie Fields
- `SAPISID` - Session API identifier
- `APISID` - API session identifier
- `__Secure-3PSID` - Secure session identifier
- `HSID` - Host session identifier
- `SSID` - Session identifier
- `LOGIN_INFO` - Authentication tokens

### Cookie Loading Process

```javascript
// 1. Check environment variable
const COOKIES_ENV = process.env.YOUTUBE_COOKIES;

// 2. Write to file if provided
if (COOKIES_ENV) {
  fs.writeFileSync(COOKIES_PATH, COOKIES_ENV);
}

// 3. Verify cookies exist
const hasCookies = fs.existsSync(COOKIES_PATH);

// 4. Build yt-dlp command with cookies
const cookiesArg = hasCookies ? `--cookies "${COOKIES_PATH}"` : '';
```

## 🛠️ yt-dlp Integration

### Command Building

```javascript
function buildYtdlpCommand(args) {
  const cookiesArg = hasCookies ? `--cookies "${COOKIES_PATH}"` : '';
  return `yt-dlp ${cookiesArg} ${args}`;
}
```

### Search Command
```bash
yt-dlp --cookies "cookies.txt" "ytsearch10:{query}" --dump-json
```

### Extraction Command
```bash
yt-dlp --cookies "cookies.txt" -g -f "bestaudio[ext=m4a]/bestaudio/best" "{url}"
```

### Metadata Command
```bash
yt-dlp --cookies "cookies.txt" -j --skip-download "{url}"
```

## 🔧 Configuration

### Environment Variables

| Variable | Description | Required | Default |
|----------|-------------|-----------|---------|
| `PORT` | Server port | No | 10000 |
| `YOUTUBE_COOKIES` | Netscape cookie content | No | null |

### Runtime Requirements

- **Node.js**: >=18.0.0
- **Python**: 3.14.3 (for yt-dlp)
- **yt-dlp**: >=2024.1.1
- **FFmpeg**: For audio processing

## 🚨 Error Handling

### HTTP Status Codes

| Code | Description | Response |
|-------|-------------|----------|
| 200 | Success | JSON data |
| 400 | Bad Request | `{"error": "Invalid video ID"}` |
| 403 | Forbidden | `{"error": "Age restricted - requires sign in"}` |
| 404 | Not Found | `{"error": "Video unavailable or private"}` |
| 500 | Internal Error | `{"error": "Extraction failed", "message": "..."}` |

### Error Categories

1. **Bot Detection** (403)
   - Cookies expired or invalid
   - YouTube anti-bot measures
   - Solution: Refresh cookies

2. **Video Unavailable** (404)
   - Video deleted/private
   - Geo-restricted
   - Solution: Try alternative video

3. **Extraction Failed** (500)
   - yt-dlp execution error
   - Network issues
   - Solution: Check logs, retry

## 📊 Performance Metrics

### Request Flow

```
Client Request → Express Router → yt-dlp Execution → Response Parsing → JSON Response
```

### Timeout Configuration

- **Search**: 25 seconds (cold start), 10 seconds (warm)
- **Track Extraction**: 30 seconds
- **Metadata**: 15 seconds

### Circuit Breaker

- **Failure Threshold**: 5 consecutive failures
- **Open Duration**: 60 seconds
- **Half-Open**: Test every 10 seconds

## 🔍 Logging

### Log Levels

```javascript
console.log('[INIT] ...');     // Initialization
console.log('[SEARCH] ...');   // Search operations
console.log('[TRACK] ...');    // Track extraction
console.log('[EXTRACT] ...');  // URL extraction
console.error('[ERROR] ...');   // Errors
```

### Critical Logs

```javascript
// Cookie status
console.log(`[INIT] Cookies file ${hasCookies ? 'found' : 'NOT found'}`);

// Extraction success/failure
console.log(`[TRACK] Success: ${title}`);
console.error(`[TRACK] yt-dlp error: ${error.message}`);

// Stream URL extraction
console.log(`[TRACK] Stream URL extracted: ${streamUrl ? 'YES' : 'NO'}`);
```

## 🚀 Deployment

### Render.com Configuration

```yaml
# build command
npm install && pip install -r requirements.txt

# start command
node index.js

# environment variables
PORT: 10000
YOUTUBE_COOKIES: <netscape_cookies>
```

### Health Check

Render uses `/` endpoint for health monitoring:
- Returns 200 OK with service status
- Monitors service availability
- Auto-restarts on failure

## 🔒 Security Considerations

### Cookie Security

1. **Environment Variables**: Cookies stored in encrypted env vars
2. **File Permissions**: cookies.txt with restricted access
3. **No Logging**: Cookie content never logged
4. **HTTPS Only**: All communications over HTTPS

### Input Validation

- Video ID validation: `/^[a-zA-Z0-9_-]{11}$/`
- Query sanitization: Strip special characters
- Rate limiting: Built-in Express middleware

## 🧪 Testing

### Unit Tests

```bash
# Health check
curl https://youtube-music-wrapper.onrender.com/

# Search test
curl "https://youtube-music-wrapper.onrender.com/search?q=tum%20hi%20ho&limit=3"

# Track test
curl https://youtube-music-wrapper.onrender.com/track/dQw4w9WgXcQ
```

### Integration Tests

```javascript
// Test with cookies
const response = await fetch('/track/dQw4w9WgXcQ');
const data = await response.json();
assert(data.stream_url); // Stream URL should exist
```

## 🐛 Troubleshooting

### Common Issues

1. **"Sign in to confirm you're not a bot"**
   - **Cause**: Expired or invalid cookies
   - **Fix**: Re-export fresh cookies from Chrome

2. **"No supported JavaScript runtime"**
   - **Cause**: yt-dlp needs JS for some videos
   - **Fix**: Install Node.js runtime (already included)

3. **"Video unavailable"**
   - **Cause**: Video deleted or geo-restricted
   - **Fix**: Try alternative video/source

### Debug Commands

```javascript
// Check cookie status
console.log(`[INIT] Environment check: COOKIES_ENV present=${hasCookiesEnv}`);

// Verify cookies file
const written = fs.readFileSync(COOKIES_PATH, 'utf8');
console.log(`[INIT] Cookies file verified: ${written.length} bytes`);
```

## 📈 Monitoring

### Key Metrics

- **Response Time**: <5 seconds for search, <30 seconds for extraction
- **Success Rate**: >95% with valid cookies
- **Uptime**: 99.9% with auto-restart
- **Error Rate**: <5% (mostly bot detection)

### Alert Conditions

- **High Error Rate**: >10% failure rate over 5 minutes
- **Cookie Expiry**: 403 errors >5 per minute
- **Service Down**: Health check fails >3 consecutive checks

---

*Last Updated: May 8, 2026*
