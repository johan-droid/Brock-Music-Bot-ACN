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
            '--flat-playlist'
        ]);

        try {
            const { stdout } = await execFilePromise('yt-dlp', args, { timeout: 40000 });
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
        const streamArgs = this.getBaseArgs().concat([
            '-g',
            '-f',
            'bestaudio[ext=m4a]/bestaudio/best',
            url
        ]);

        const metadataArgs = this.getBaseArgs().concat([
            '-j',
            '--skip-download',
            url
        ]);

        try {
             const [streamUrlResult, metadataResult] = await Promise.all([
                execFilePromise('yt-dlp', streamArgs, { timeout: 45000 }),
                execFilePromise('yt-dlp', metadataArgs, { timeout: 45000 })
            ]);

            const stream_url = streamUrlResult.stdout.trim();
            const data = JSON.parse(metadataResult.stdout);

            return {
                id: videoId || data.id,
                title: data.title,
                artist: { name: data.uploader },
                duration: data.duration,
                stream_url: stream_url,
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
