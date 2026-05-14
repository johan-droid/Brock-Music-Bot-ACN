const { execFile } = require('child_process');
const util = require('util');
const execFilePromise = util.promisify(execFile);

class YtdlpEngine {
    constructor(cookieManager) {
        this.cookieManager = cookieManager;
    }

    getBaseArgs() {
        if (this.cookieManager.hasCookies) {
            return ['--cookies', this.cookieManager.getCookiesPath()];
        }
        return [];
    }

    async search(query, limit) {
        const args = this.getBaseArgs().concat([
            `ytsearch${limit}:${query}`,
            '--dump-json',
            '--flat-playlist',
            '--no-check-certificates',
            '--prefer-free-formats'
        ]);

        try {
            const { stdout } = await execFilePromise('yt-dlp', args, { timeout: 150000 });
            const lines = stdout.split('\n').filter(line => line.trim().length > 0);
            return lines.map(line => {
                const data = JSON.parse(line);
                return {
                    id: data.id,
                    title: data.title,
                    artist: data.uploader,
                    duration: data.duration,
                    thumbnail: data.thumbnail,
                    url: data.webpage_url
                };
            });
        } catch (error) {
            this.handleError(error);
        }
    }

    async extract(url, videoId) {
        // Optimization: Use a single call to get both metadata and stream URL
        // -j (dump-json) includes the direct stream URL in the 'url' field for simple extractions
        const args = this.getBaseArgs().concat([
            '-j',
            '--skip-download',
            '-f', 'bestaudio[ext=m4a]/bestaudio/best',
            '--no-playlist',
            '--no-check-certificates',
            '--prefer-free-formats',
            url
        ]);

        try {
            const { stdout } = await execFilePromise('yt-dlp', args, { timeout: 150000 });
            const data = JSON.parse(stdout);

            return {
                id: videoId || data.id,
                title: data.title,
                artist: { name: data.uploader },
                duration: data.duration,
                stream_url: data.url, // This is the direct stream URL
                url: data.webpage_url || url,
                thumbnail: data.thumbnail,
                source: "youtube"
            };
        } catch (error) {
            this.handleError(error);
        }
    }

    handleError(error) {
        const errMsg = error.message || '';
        const customError = new Error('Extraction failed');
        customError.status = 500;

        if (errMsg.includes('Sign in to confirm you\'re not a bot')) {
            customError.status = 403;
            customError.is403 = true;
            customError.message = 'Age restricted - requires sign in / Bot detection triggered';
        } else if (errMsg.includes('Video unavailable')) {
            customError.status = 404;
            customError.message = 'Video unavailable or private';
        } else {
             customError.message = errMsg;
        }

        throw customError;
    }
}

module.exports = YtdlpEngine;
