/**
 * JioSaavn Music Wrapper Microservice
 * Extracts audio URLs from JioSaavn for Indian/Bollywood music
 * Deploy to Render to bypass geo-restrictions
 */

const express = require('express');
const cors = require('cors');
const axios = require('axios');

const app = express();
const PORT = process.env.PORT || 3000;

// Middleware
app.use(cors());
app.use(express.json());

// JioSaavn API base URL
const JIOSAAVN_BASE = 'https://www.jiosaavn.com/api.php';

// Axios instance with timeout
const http = axios.create({
  timeout: 15000,
  headers: {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': 'application/json',
    'Referer': 'https://www.jiosaavn.com/'
  }
});

/**
 * Make request to JioSaavn API
 */
async function makeRequest(params) {
  try {
    const response = await http.get(JIOSAAVN_BASE, { params });
    return response.data;
  } catch (error) {
    console.error('[API] JioSaavn request failed:', error.message);
    throw error;
  }
}

/**
 * Decrypt JioSaavn encrypted media URL
 * JioSaavn uses base64 encoded URLs
 */
function decryptJioSaavnUrl(encryptedUrl) {
  if (!encryptedUrl) return null;
  
  try {
    // Decode base64 - JioSaavn URLs are base64 encoded
    let decoded = Buffer.from(encryptedUrl, 'base64').toString('utf-8');
    
    // Check if it looks like a valid URL
    if (!decoded.startsWith('http')) {
      console.log('[DECRYPT] Decoded value is not a URL, using preview URL instead');
      return null;
    }
    
    // Replace quality marker for higher quality (96->320, 160->320)
    decoded = decoded.replace(/_96\.mp4/g, '_320.mp4');
    decoded = decoded.replace(/_160\.mp4/g, '_320.mp4');
    
    // Ensure HTTPS
    if (decoded.startsWith('http://')) {
      decoded = decoded.replace('http://', 'https://');
    }
    
    return decoded;
  } catch (error) {
    console.error('[DECRYPT] Failed to decrypt URL:', error.message);
    return null;
  }
}

/**
 * Parse duration string to seconds
 */
function parseDuration(durationStr) {
  if (!durationStr) return 0;
  const parts = durationStr.split(':');
  if (parts.length === 2) {
    return parseInt(parts[0]) * 60 + parseInt(parts[1]);
  } else if (parts.length === 3) {
    return parseInt(parts[0]) * 3600 + parseInt(parts[1]) * 60 + parseInt(parts[2]);
  }
  return parseInt(durationStr) || 0;
}

/**
 * Health check endpoint
 */
app.get('/', (req, res) => {
  res.json({
    status: 'healthy',
    service: 'jiosaavn-music-wrapper',
    version: '1.0.0',
    description: 'Indian/Bollywood music extraction via JioSaavn'
  });
});

/**
 * Search JioSaavn
 * GET /search?q=<query>&limit=<n>
 */
app.get('/search', async (req, res) => {
  try {
    const query = req.query.q;
    const limit = parseInt(req.query.limit) || 10;

    if (!query) {
      return res.status(400).json({ error: 'Missing query parameter' });
    }

    console.log(`[SEARCH] Query: "${query}", Limit: ${limit}`);

    const params = {
      __call: 'search.getResults',
      q: query,
      n: limit,
      p: 1,
      _format: 'json',
      _marker: 0,
      api_version: 4,
      ctx: 'web6dot0',
      cat: 'songs'
    };

    const result = await makeRequest(params);

    if (!result || !result.results) {
      return res.json({ data: [], total: 0, query });
    }

    const tracks = result.results.map(item => {
      // Fix URL - perma_url might be full URL or just path
      let songUrl = item.perma_url || `https://www.jiosaavn.com/song/${item.id}`;
      if (!songUrl.startsWith('http')) {
        songUrl = `https://www.jiosaavn.com${songUrl.startsWith('/') ? '' : '/'}${songUrl}`;
      }
      
      return {
        id: String(item.id),
        title: item.title || 'Unknown',
        artist: item.primary_artists || item.singers || 'Unknown Artist',
        album: item.album || '',
        duration: parseDuration(item.duration),
        thumbnail: item.image ? item.image.replace('150x150', '500x500') : '',
        url: songUrl,
        stream_url: item.media_preview_url || item.more_info?.media_preview_url || null,
        source: 'jiosaavn'
      };
    });

    console.log(`[SEARCH] Found ${tracks.length} results`);

    res.json({
      data: tracks,
      total: tracks.length,
      query
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
 * Get track details by ID
 * GET /track/:id
 */
app.get('/track/:id', async (req, res) => {
  try {
    const songId = req.params.id;

    if (!songId) {
      return res.status(400).json({ error: 'Missing song ID' });
    }

    console.log(`[TRACK] ID: ${songId}`);

    const params = {
      __call: 'song.getDetails',
      pids: songId,
      _format: 'json',
      _marker: 0,
      api_version: 4,
      ctx: 'web6dot0'
    };

    const result = await makeRequest(params);

    if (!result || !result.songs || !result.songs[0]) {
      return res.status(404).json({ error: 'Track not found' });
    }

    const song = result.songs[0];

    // Get best quality stream URL from multiple possible locations
    // PRIORITY: Decrypted encrypted URL > preview URL > other sources
    let streamUrl = null;
    
    console.log(`[TRACK] Looking for stream URL for: ${song.title}`);
    console.log(`[TRACK] encrypted_media_url exists: ${!!song.more_info?.encrypted_media_url}`);
    console.log(`[TRACK] media_preview_url exists: ${!!song.media_preview_url}`);
    
    // Try to decrypt encrypted media URL first (best quality, no geo-restriction)
    if (song.more_info?.encrypted_media_url) {
      const encrypted = song.more_info.encrypted_media_url;
      console.log(`[TRACK] Attempting to decrypt, encrypted length: ${encrypted.length}`);
      streamUrl = decryptJioSaavnUrl(encrypted);
      console.log(`[TRACK] Decryption result: ${streamUrl ? 'SUCCESS' : 'FAILED'}`);
      if (streamUrl) {
        console.log(`[TRACK] Decrypted URL starts with: ${streamUrl.substring(0, 50)}...`);
      }
    }
    
    // Fallback to preview URL if decryption failed
    if (!streamUrl) {
      console.log(`[TRACK] Falling back to preview URL`);
      streamUrl = song.media_preview_url || 
                  song.more_info?.media_preview_url ||
                  song.media_url ||
                  song.more_info?.vlink ||
                  null;
    }
    
    console.log(`[TRACK] Final stream URL: ${streamUrl ? streamUrl.substring(0, 60) + '...' : 'NONE'}`);

    if (!streamUrl) {
      console.log(`[TRACK] No stream URL for: ${song.title}`);
      return res.status(404).json({ error: 'No stream URL available', id: songId });
    }

    // Fix URL construction
    let songUrl = song.perma_url || `https://www.jiosaavn.com/song/${songId}`;
    if (!songUrl.startsWith('http')) {
      songUrl = `https://www.jiosaavn.com${songUrl.startsWith('/') ? '' : '/'}${songUrl}`;
    }

    console.log(`[TRACK] Success: ${song.title}`);

    res.json({
      id: String(songId),
      title: song.title || 'Unknown',
      artist: song.primary_artists || song.singers || 'Unknown Artist',
      album: song.album || '',
      duration: parseDuration(song.duration),
      stream_url: streamUrl,
      thumbnail: song.image ? song.image.replace('150x150', '500x500') : '',
      url: songUrl,
      source: 'jiosaavn'
    });

  } catch (error) {
    console.error('[TRACK] Error:', error.message);
    res.status(500).json({
      error: 'Extraction failed',
      message: error.message
    });
  }
});

/**
 * Get album details
 * GET /album/:id
 */
app.get('/album/:id', async (req, res) => {
  try {
    const albumId = req.params.id;

    if (!albumId) {
      return res.status(400).json({ error: 'Missing album ID' });
    }

    console.log(`[ALBUM] ID: ${albumId}`);

    const params = {
      __call: 'content.getAlbumDetails',
      albumid: albumId,
      _format: 'json',
      _marker: 0,
      api_version: 4,
      ctx: 'web6dot0'
    };

    const result = await makeRequest(params);

    if (!result || !result.songs) {
      return res.status(404).json({ error: 'Album not found' });
    }

    const tracks = result.songs.map(song => ({
      id: String(song.id),
      title: song.title || 'Unknown',
      artist: song.primary_artists || song.singers || 'Unknown Artist',
      duration: parseDuration(song.duration),
      thumbnail: song.image ? song.image.replace('150x150', '500x500') : '',
      stream_url: song.media_preview_url || null,
      source: 'jiosaavn'
    }));

    res.json({
      id: albumId,
      title: result.title || 'Unknown Album',
      artist: result.primary_artists || 'Unknown Artist',
      tracks: tracks,
      total: tracks.length
    });

  } catch (error) {
    console.error('[ALBUM] Error:', error.message);
    res.status(500).json({ error: 'Failed to get album', message: error.message });
  }
});

// Error handling
app.use((err, req, res, next) => {
  console.error('[ERROR]', err);
  res.status(500).json({ error: 'Internal server error' });
});

app.listen(PORT, () => {
  console.log(`🎵 JioSaavn Music Wrapper running on port ${PORT}`);
  console.log(`🎼 Specialized in Indian/Bollywood music`);
  console.log('');
  console.log('Endpoints:');
  console.log('  GET /                    - Health check');
  console.log('  GET /search?q=<query>    - Search songs');
  console.log('  GET /track/:id           - Get song by ID');
  console.log('  GET /album/:id           - Get album details');
});
