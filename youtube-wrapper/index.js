/**
 * YouTube Music Wrapper Microservice
 * Uses yt-dlp with cookies to bypass YouTube bot detection
 * Deploy to Render to bypass Heroku IP blocks
 */

const express = require('express');
const cors = require('cors');
const { exec } = require('child_process');
const { promisify } = require('util');
const path = require('path');
const fs = require('fs');

const execAsync = promisify(exec);
const app = express();
const PORT = process.env.PORT || 3000;

// Middleware
app.use(cors());
app.use(express.json());

// Check for cookies file or environment variable
const COOKIES_PATH = path.join(__dirname, 'cookies.txt');
const COOKIES_ENV = process.env.YOUTUBE_COOKIES;
const hasCookiesFile = fs.existsSync(COOKIES_PATH);
const hasCookiesEnv = !!COOKIES_ENV;

console.log(`[INIT] Environment check: COOKIES_ENV present=${hasCookiesEnv}, length=${COOKIES_ENV ? COOKIES_ENV.length : 0}`);
console.log(`[INIT] Cookies file exists: ${hasCookiesFile}`);

// Always update cookies from env if provided (allows cookie refresh)
if (hasCookiesEnv) {
  try {
    fs.writeFileSync(COOKIES_PATH, COOKIES_ENV);
    console.log('[INIT] Cookies written from environment variable');
    // Verify write
    const written = fs.readFileSync(COOKIES_PATH, 'utf8');
    console.log(`[INIT] Cookies file verified: ${written.length} bytes, starts with: ${written.substring(0, 50)}...`);
  } catch (e) {
    console.error('[INIT] Failed to write cookies:', e.message);
  }
}

const hasCookies = fs.existsSync(COOKIES_PATH) && fs.statSync(COOKIES_PATH).size > 0;
console.log(`[INIT] Final cookies status: ${hasCookies ? 'AVAILABLE' : 'NOT AVAILABLE'}`);

// Build yt-dlp command with cookies
function buildYtdlpCommand(args) {
  const cookiesArg = hasCookies ? `--cookies "${COOKIES_PATH}"` : '';
  return `yt-dlp ${cookiesArg} ${args}`;
}

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
 * Search YouTube Music using yt-dlp with cookies
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

    try {
      // Use yt-dlp with cookies to search
      const searchQuery = `ytsearch${limit}:${query}`;
      const cmd = buildYtdlpCommand(`-j --flat-playlist "${searchQuery}"`);

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

      console.log(`[SEARCH] Found ${results.length} results via yt-dlp`);

      res.json({
        data: results,
        total: results.length,
        query: query
      });

    } catch (execError) {
      console.error('[SEARCH] yt-dlp error:', execError.message);
      res.status(500).json({
        error: 'Search failed',
        message: execError.message,
        data: [],
        total: 0
      });
    }

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
 * Get track stream URL using yt-dlp with cookies
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

    try {
      // Get best audio format URL using yt-dlp with cookies
      // -g: get URL, -f: format selector (best audio only)
      const cmd = buildYtdlpCommand(`-g -f "bestaudio[ext=m4a]/bestaudio/best" "${videoUrl}"`);
      console.log(`[TRACK] Executing: ${cmd.replace(/cookies ".*?"/, 'cookies "***"')}`);
      console.log(`[TRACK] Cookies available: ${hasCookies}`);

      const { stdout, stderr } = await execAsync(cmd, { timeout: 30000 });

      if (stderr) {
        console.error('[TRACK] stderr:', stderr);
      }

      const streamUrl = stdout.trim();
      console.log(`[TRACK] Stream URL extracted: ${streamUrl ? 'YES' : 'NO'}`);

      if (!streamUrl) {
        return res.status(404).json({ error: 'Could not extract stream URL' });
      }

      // Get video info for metadata
      const infoCmd = buildYtdlpCommand(`-j --skip-download "${videoUrl}"`);
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

    } catch (execError) {
      console.error('[TRACK] yt-dlp error:', execError.message);
      console.error('[TRACK] Full error:', execError.stderr || 'No stderr');

      // Check for specific errors
      if (execError.message.includes('Video unavailable')) {
        return res.status(404).json({ error: 'Video unavailable or private' });
      }
      if (execError.message.includes('Sign in') || execError.message.includes('confirm you')) {
        return res.status(403).json({ error: 'Bot detection - cookies may be expired or invalid' });
      }

      res.status(500).json({
        error: 'Extraction failed',
        message: execError.message,
        stderr: execError.stderr
      });
    }

  } catch (error) {
    console.error('[TRACK] Error:', error.message);
    res.status(500).json({
      error: 'Extraction failed',
      message: error.message
    });
  }
});

/**
 * Extract from full URL using yt-dlp with cookies
 * GET /extract?url=<youtube_url>
 */
app.get('/extract', async (req, res) => {
  try {
    const url = req.query.url;

    if (!url) {
      return res.status(400).json({ error: 'Missing URL parameter' });
    }

    console.log(`[EXTRACT] URL: ${url}`);

    try {
      // Get stream URL using yt-dlp with cookies
      const cmd = buildYtdlpCommand(`-g -f "bestaudio[ext=m4a]/bestaudio/best" "${url}"`);
      const { stdout } = await execAsync(cmd, { timeout: 30000 });
      const streamUrl = stdout.trim();

      if (!streamUrl) {
        return res.status(404).json({ error: 'Could not extract stream URL' });
      }

      // Get metadata
      const infoCmd = buildYtdlpCommand(`-j --skip-download "${url}"`);
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

    } catch (execError) {
      console.error('[EXTRACT] yt-dlp error:', execError.message);
      res.status(500).json({
        error: 'Extraction failed',
        message: execError.message
      });
    }

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
  console.log(`📺 Using yt-dlp with cookies to bypass bot detection`);
  console.log(`🍪 Cookies file: ${hasCookies ? 'YES' : 'NO'}`);
  console.log('');
  console.log('Endpoints:');
  console.log('  GET /                    - Health check');
  console.log('  GET /search?q=<query>    - Search YouTube');
  console.log('  GET /track/:id           - Get stream URL by video ID');
  console.log('  GET /extract?url=<url>   - Extract from full URL');
});
