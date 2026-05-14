const express = require('express');
const axios = require('axios');
const CryptoJS = require('crypto-js');
const cors = require('cors');

const app = express();
const PORT = process.env.PORT || 3000;

app.use(cors());
app.use(express.json());

// JioSaavn DES-ECB Decryption logic
function decryptJioSaavnUrl(encryptedUrl) {
    if (!encryptedUrl) return null;

    try {
        const key = '38346b346c336d31';
        const keyHex = CryptoJS.enc.Utf8.parse(key);
        
        // Decode base64
        const ciphertext = CryptoJS.enc.Base64.parse(encryptedUrl);
        
        // Decrypt using DES-ECB
        const decrypted = CryptoJS.DES.decrypt(
            { ciphertext: ciphertext },
            keyHex,
            {
                mode: CryptoJS.mode.ECB,
                padding: CryptoJS.pad.Pkcs7
            }
        );

        let decoded = decrypted.toString(CryptoJS.enc.Utf8);
        if (!decoded || !decoded.startsWith('http')) return null;

        // Map quality to 320kbps
        decoded = decoded.replace('_96.mp4', '_320.mp4')
                         .replace('_160.mp4', '_320.mp4')
                         .replace('_96.m4a', '_320.m4a')
                         .replace('_160.m4a', '_320.m4a');
        
        // Ensure HTTPS
        if (decoded.startsWith('http://')) {
            decoded = decoded.replace('http://', 'https://');
        }

        return decoded;
    } catch (error) {
        console.error('[DECRYPT] Decryption failed:', error.message);
        return null;
    }
}

// Health check endpoint
app.get('/health', (req, res) => {
    res.json({ status: 'ok', service: 'jiosaavn-wrapper' });
});

// Search endpoint
app.get('/search', async (req, res) => {
    const query = req.query.q;
    if (!query) {
        return res.status(400).json({ error: 'Missing search query' });
    }

    try {
        const response = await axios.get('https://www.jiosaavn.com/api.php', {
            params: {
                __call: 'autocomplete.get',
                query: query,
                _format: 'json',
                _marker: 0,
                ctx: 'web6dot0'
            },
            timeout: 10000
        });

        const data = response.data;
        if (!data || !data.songs) {
            return res.json({ data: [] });
        }

        const songs = data.songs.data || data.songs;
        const results = songs.map(song => ({
            id: song.id,
            title: (song.title || '').replace(/&quot;/g, '"'),
            artist: song.more_info?.primary_artists || 'Unknown Artist',
            thumbnail: (song.image || '').replace('50x50', '500x500'),
            url: song.url || '',
            source: 'jiosaavn'
        }));

        res.json({ data: results });
    } catch (error) {
        console.error('[SEARCH] Search failed:', error.message);
        res.status(500).json({ error: 'Search failed' });
    }
});

// Track details and extraction endpoint
app.get('/track/:id', async (req, res) => {
    const trackId = req.params.id;
    
    try {
        const response = await axios.get('https://www.jiosaavn.com/api.php', {
            params: {
                __call: 'song.getDetails',
                pids: trackId,
                _format: 'json',
                _marker: 0,
                ctx: 'web6dot0'
            },
            timeout: 10000
        });

        const result = response.data;
        if (!result || !result.songs || result.songs.length === 0) {
            return res.status(404).json({ error: 'Track not found' });
        }

        const song = result.songs[0];

        // PRIORITY: Decrypted encrypted URL (Full quality) > media_preview_url (often preview)
        let streamUrl = null;
        
        // Get encrypted URL from all possible locations
        const encUrl = song.encrypted_media_url || song.more_info?.encrypted_media_url;
        if (encUrl) {
            console.log(`[TRACK] Found encrypted URL for: ${song.title}`);
            streamUrl = decryptJioSaavnUrl(encUrl);
        }
        
        if (!streamUrl) {
            streamUrl = song.media_preview_url || song.more_info?.media_preview_url;
            if (streamUrl) console.log(`[TRACK] Falling back to preview URL for: ${song.title}`);
        }

        if (!streamUrl) {
            return res.status(404).json({ error: 'No stream URL found' });
        }

        res.json({
            id: trackId,
            title: (song.song || song.title || 'Unknown').replace(/&quot;/g, '"'),
            artist: song.primary_artists || song.more_info?.primary_artists || 'Unknown Artist',
            duration: parseInt(song.duration || 0),
            stream_url: streamUrl,
            thumbnail: (song.image || '').replace('150x150', '500x500'),
            url: song.perma_url || '',
            source: 'jiosaavn'
        });

    } catch (error) {
        console.error('[TRACK] Extraction failed:', error.message);
        res.status(500).json({ error: 'Extraction failed' });
    }
});

app.listen(PORT, () => {
    console.log(`JioSaavn wrapper listening on port ${PORT}`);
});
