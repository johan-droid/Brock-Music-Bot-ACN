/**
 * YouTube Music Wrapper Microservice
 * Extracts audio URLs from YouTube Music/YouTube for Telegram bot
 * Deploy to Render to bypass Heroku IP blocks
 */

const express = require('express');
const cors = require('cors');
const { exec } = require('child_process');
const { promisify } = require('util');
const path = require('path');

const execAsync = promisify(exec);
const app = express();
const PORT = process.env.PORT || 3000;

// Middleware
app.use(cors());
app.use(express.json());

// yt-dlp binary path (will be installed via requirements.txt or npm postinstall)
const YTDLP_PATH = process.env.YTDLP_PATH || 'yt-dlp';

/**
 * Health check endpoint
 */
app.get('/', (req, res) => {
  res.json({
    status: 'healthy',
    service: 'youtube-music-wrapper',
    version: '1.0.0'
  });
});

/**
 * Search YouTube Music
 * GET /search?q=<query>&limit=<n>
 */
app.get('/search', async (req, res) => {
  try {
    const query = req.query.q;
    const limit = parseInt(req.query.limit) || 5;

    if (!query) {
      return res.status(400).json({ error: 'Missing query parameter' });
    }

    console.log(`[SEARCH] Query: "${query}", Limit: ${limit}`);

    // Use yt-dlp to search
    const searchQuery = `ytsearch${limit}:${query}`;
    const cmd = `${YTDLP_PATH} -j --flat-playlist --extractor-args "youtube:lang=en" "${searchQuery}"`;

    const { stdout, stderr } = await execAsync(cmd, { timeout: 30000 });

    if (stderr) {
      console.error('[SEARCH] stderr:', stderr);
    }

    // Parse JSON lines
    const lines = stdout.trim().split('\n').filter(line => line.trim());
    const results = [];

    for (const line of lines) {
      try {
        const data = JSON.parse(line);
        if (data.id && data.title) {
          results.push({
            id: data.id,
            title: data.title,
            artist: data.uploader || data.channel || 'Unknown Artist',
            duration: data.duration || 0,
            thumbnail: data.thumbnail || `https://i.ytimg.com/vi/${data.id}/mqdefault.jpg`,
            url: `https://www.youtube.com/watch?v=${data.id}`
          });
        }
      } catch (e) {
        console.error('[SEARCH] Failed to parse line:', e.message);
      }
    }

    console.log(`[SEARCH] Found ${results.length} results`);

    res.json({
      data: results,
      total: results.length,
      query: query
    });

  } catch (error) {
    console.error('[SEARCH] Error:', error.message);
    res.status(500).json({
      error: 'Search failed',
      message: error.message,
      data: [],
      total: 0
    });
  }
});

/**
 * Get track stream URL
 * GET /track/:id
 */
app.get('/track/:id', async (req, res) => {
  try {
    const videoId = req.params.id;

    if (!videoId || !/^[a-zA-Z0-9_-]{11}$/.test(videoId)) {
      return res.status(400).json({ error: 'Invalid video ID' });
    }

    console.log(`[TRACK] ID: ${videoId}`);

    const videoUrl = `https://www.youtube.com/watch?v=${videoId}`;

    // Get best audio format URL
    // -g: get URL, -f: format selector (best audio only)
    const cmd = `${YTDLP_PATH} -g -f "bestaudio[ext=m4a]/bestaudio/best" --extractor-args "youtube:player_client=web" "${videoUrl}"`;

    const { stdout, stderr } = await execAsync(cmd, { timeout: 30000 });

    if (stderr) {
      console.error('[TRACK] stderr:', stderr);
    }

    const streamUrl = stdout.trim();

    if (!streamUrl) {
      return res.status(404).json({ error: 'Could not extract stream URL' });
    }

    // Get video info for metadata
    const infoCmd = `${YTDLP_PATH} -j --skip-download "${videoUrl}"`;
    let title = 'Unknown';
    let artist = 'Unknown Artist';
    let duration = 0;
    let thumbnail = '';

    try {
      const { stdout: infoStdout } = await execAsync(infoCmd, { timeout: 15000 });
      const info = JSON.parse(infoStdout);
      title = info.title || 'Unknown';
      artist = info.uploader || info.channel || 'Unknown Artist';
      duration = info.duration || 0;
      thumbnail = info.thumbnail || `https://i.ytimg.com/vi/${videoId}/mqdefault.jpg`;
    } catch (e) {
      console.error('[TRACK] Failed to get metadata:', e.message);
      thumbnail = `https://i.ytimg.com/vi/${videoId}/mqdefault.jpg`;
    }

    console.log(`[TRACK] Success: ${title}`);

    res.json({
      id: videoId,
      title: title,
      artist: { name: artist },
      duration: duration,
      stream_url: streamUrl,
      url: videoUrl,
      thumbnail: thumbnail,
      source: 'youtube'
    });

  } catch (error) {
    console.error('[TRACK] Error:', error.message);

    // Check for specific errors
    if (error.message.includes('Video unavailable')) {
      return res.status(404).json({ error: 'Video unavailable or private' });
    }
    if (error.message.includes('Sign in')) {
      return res.status(403).json({ error: 'Age restricted - requires sign in' });
    }

    res.status(500).json({
      error: 'Extraction failed',
      message: error.message
    });
  }
});

/**
 * Extract from full URL
 * GET /extract?url=<youtube_url>
 */
app.get('/extract', async (req, res) => {
  try {
    const url = req.query.url;

    if (!url) {
      return res.status(400).json({ error: 'Missing URL parameter' });
    }

    console.log(`[EXTRACT] URL: ${url}`);

    // Get stream URL
    const cmd = `${YTDLP_PATH} -g -f "bestaudio[ext=m4a]/bestaudio/best" "${url}"`;
    const { stdout } = await execAsync(cmd, { timeout: 30000 });
    const streamUrl = stdout.trim();

    if (!streamUrl) {
      return res.status(404).json({ error: 'Could not extract stream URL' });
    }

    // Get metadata
    const infoCmd = `${YTDLP_PATH} -j --skip-download "${url}"`;
    const { stdout: infoStdout } = await execAsync(infoCmd, { timeout: 15000 });
    const info = JSON.parse(infoStdout);

    res.json({
      id: info.id,
      title: info.title || 'Unknown',
      artist: { name: info.uploader || 'Unknown Artist' },
      duration: info.duration || 0,
      stream_url: streamUrl,
      url: url,
      thumbnail: info.thumbnail || '',
      source: 'youtube'
    });

  } catch (error) {
    console.error('[EXTRACT] Error:', error.message);
    res.status(500).json({
      error: 'Extraction failed',
      message: error.message
    });
  }
});

// Error handling
app.use((err, req, res, next) => {
  console.error('[ERROR]', err);
  res.status(500).json({ error: 'Internal server error' });
});

app.listen(PORT, () => {
  console.log(`🎵 YouTube Music Wrapper running on port ${PORT}`);
  console.log(`📺 yt-dlp path: ${YTDLP_PATH}`);
  console.log('');
  console.log('Endpoints:');
  console.log('  GET /                    - Health check');
  console.log('  GET /search?q=<query>    - Search YouTube');
  console.log('  GET /track/:id           - Get stream URL by video ID');
  console.log('  GET /extract?url=<url>   - Extract from full URL');
});
