# YouTube Music Wrapper

A lightweight microservice that extracts audio URLs from YouTube Music/YouTube using yt-dlp.

**Purpose:** Bypass Heroku IP blocks by running extraction on Render (different IP range).

## Deploy to Render

### Option 1: Deploy from GitHub (Recommended)

1. Push this code to a GitHub repository
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

### Option 2: Deploy via Render YAML

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

**yt-dlp not found:**
- Make sure `pip install -r requirements.txt` runs during build
- Or install yt-dlp manually: `pip install yt-dlp`

**Rate limiting (429):**
- YouTube may rate-limit Render IPs too
- Consider adding delays between requests in your bot
- Use rotating user-agents (already implemented)

**Video unavailable:**
- Some videos are geo-blocked or age-restricted
- Try different search queries

## License

MIT
