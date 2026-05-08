# YouTube Music Wrapper

A lightweight microservice that extracts audio URLs from YouTube Music/YouTube using **yt-dlp with cookies**.

**Purpose:** Bypass YouTube bot detection by using exported browser cookies to authenticate requests.

## How It Works

This wrapper uses yt-dlp with YouTube cookies exported from your browser:
- Cookies authenticate the requests as a real user
- Bypasses YouTube's bot detection
- Works with Indian music and geo-restricted content
- Requires periodic cookie refresh (when they expire)

## Setup (IMPORTANT)

### Step 1: Export YouTube Cookies

1. Install "Get cookies.txt LOCALLY" Chrome extension
2. Go to https://www.youtube.com (make sure you're logged in)
3. Click the extension → "Export" → Save as `cookies.txt`
4. Place `cookies.txt` in this directory

### Step 2: Deploy to Render

1. Push this code to GitHub (including `cookies.txt`)
2. Go to [Render Dashboard](https://dashboard.render.com/)
3. Click "New Web Service"
4. Connect your GitHub repository
5. Configure:
   - **Name:** `youtube-music-wrapper`
   - **Environment:** `Node`
   - **Build Command:** `npm install && pip install -r requirements.txt`
   - **Start Command:** `npm start`
   - **Plan:** Free
6. Click "Create Web Service"

## Deploy via Render YAML

1. Push this code to GitHub with `render.yaml`
2. Click "New" → "Blueprint" in Render dashboard
3. Connect your repo
4. Render will auto-configure from `render.yaml`

## API Endpoints

### Health Check
```
GET /
```
Response:
```json
{
  "status": "healthy",
  "service": "youtube-music-wrapper",
  "version": "1.0.0"
}
```

### Search
```
GET /search?q=<query>&limit=<n>
```
Example:
```bash
curl "https://your-service.onrender.com/search?q=mei+hun+yahaan&limit=5"
```

Response:
```json
{
  "data": [
    {
      "id": "dQw4w9WgXcQ",
      "title": "Song Title",
      "artist": "Artist Name",
      "duration": 213,
      "thumbnail": "https://i.ytimg.com/vi/dQw4w9WgXcQ/mqdefault.jpg",
      "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    }
  ],
  "total": 1,
  "query": "mei hun yahaan"
}
```

### Get Track Stream URL
```
GET /track/:video_id
```
Example:
```bash
curl "https://your-service.onrender.com/track/dQw4w9WgXcQ"
```

Response:
```json
{
  "id": "dQw4w9WgXcQ",
  "title": "Song Title",
  "artist": { "name": "Artist Name" },
  "duration": 213,
  "stream_url": "https://rr2---sn-...googlevideo.com/...",
  "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
  "thumbnail": "https://i.ytimg.com/vi/dQw4w9WgXcQ/mqdefault.jpg",
  "source": "youtube"
}
```

### Extract from URL
```
GET /extract?url=<youtube_url>
```
Example:
```bash
curl "https://your-service.onrender.com/extract?url=https://www.youtube.com/watch?v=dQw4w9WgXcQ"
```

## Configure Your Bot

Once deployed, add this environment variable to your Heroku bot:

```bash
heroku config:set YOUTUBE_API_BASE_URL=https://your-service.onrender.com -a resumedia
```

## Local Development

```bash
# Install dependencies
npm install

# Install yt-dlp
pip install -r requirements.txt

# Run locally
npm run dev
```

## Testing

```bash
# Search
curl "http://localhost:3000/search?q=test&limit=3"

# Get track
curl "http://localhost:3000/track/dQw4w9WgXcQ"
```

## Troubleshooting

**"Sign in to confirm you're not a bot" error:**
- Cookies have expired - re-export from browser
- YouTube changed their authentication - export fresh cookies

**Video unavailable:**
- Some videos are geo-blocked or age-restricted even with cookies
- Try different search queries

**yt-dlp not found:**
- Make sure `pip install -r requirements.txt` runs during build
- Or install yt-dlp manually: `pip install yt-dlp`

## How Cookies Work

This service uses your YouTube cookies to authenticate:
```
Your Bot → This Wrapper → yt-dlp (with your cookies) → YouTube
                              (appears as logged-in user)
```

**Cookie Expiration:**
- YouTube cookies expire after ~1-2 months
- When you see bot errors, re-export cookies.txt

## License

MIT
