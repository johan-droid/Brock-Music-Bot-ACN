# JioSaavn Music Wrapper

A lightweight microservice that extracts audio URLs from JioSaavn for Indian/Bollywood music.

**Purpose:** Provide Indian music access for Telegram bots without YouTube bot detection issues.

## Features

- Search songs, albums, artists
- Get direct audio stream URLs
- Specialized in Indian/Bollywood music
- No API keys required
- No bot detection issues

## Deploy to Render

### Option 1: Deploy from GitHub

1. Push this code to a GitHub repository
2. Go to [Render Dashboard](https://dashboard.render.com/)
3. Click "New Web Service"
4. Connect your GitHub repository
5. Configure:
   - **Name:** `jiosaavn-music-wrapper`
   - **Environment:** `Node`
   - **Build Command:** `npm install`
   - **Start Command:** `npm start`
   - **Plan:** Free
6. Click "Create Web Service"

### Option 2: Deploy via Render Blueprint

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
  "service": "jiosaavn-music-wrapper",
  "version": "1.0.0"
}
```

### Search Songs
```
GET /search?q=QUERY&limit=10
```
Response:
```json
{
  "data": [
    {
      "id": "123456",
      "title": "Song Name",
      "artist": "Artist Name",
      "album": "Album Name",
      "duration": 240,
      "thumbnail": "https://...",
      "url": "https://www.jiosaavn.com/song/...",
      "stream_url": "https://...",
      "source": "jiosaavn"
    }
  ],
  "total": 1,
  "query": "search query"
}
```

### Get Track by ID
```
GET /track/:id
```
Response:
```json
{
  "id": "123456",
  "title": "Song Name",
  "artist": "Artist Name",
  "album": "Album Name",
  "duration": 240,
  "stream_url": "https://...",
  "thumbnail": "https://...",
  "url": "https://www.jiosaavn.com/song/...",
  "source": "jiosaavn"
}
```

### Get Album
```
GET /album/:id
```

## Testing

```bash
# Search
curl "https://your-service.onrender.com/search?q=arijit+singh&limit=5"

# Get track
curl "https://your-service.onrender.com/track/123456"
```

## Integration with Music Bot

Set environment variable in Heroku:
```bash
heroku config:set JIOSAAVN_API_BASE_URL=https://your-service.onrender.com -a your-app
```

## How It Works

Uses the unofficial JioSaavn API endpoints:
```
Your Bot → This Wrapper → JioSaavn API → Audio Stream
                              (Indian music specialist)
```

## Advantages Over YouTube

- ✅ No bot detection
- ✅ No cookies needed
- ✅ Specialized in Indian music
- ✅ Bollywood songs readily available
- ✅ No IP blocking
- ✅ Geo-restriction free for Indian content

## License

MIT
