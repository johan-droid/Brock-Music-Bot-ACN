const express = require('express');
const cors = require('cors');
const helmet = require('helmet');
const pinoHttp = require('pino-http');
const pino = require('pino');
const { query, param, validationResult } = require('express-validator');

const CookieManager = require('./src/cookieManager');
const YtdlpEngine = require('./src/ytdlpEngine');
const CacheLayer = require('./src/cacheLayer');
const CircuitBreaker = require('./src/circuitBreaker');
const { limiters, errorHandler, metrics, register, activeRequestsMiddleware } = require('./src/middleware');

const logger = pino({ name: 'App', level: process.env.LOG_LEVEL || 'info' });
const pinoMiddleware = pinoHttp({ logger });

const app = express();
app.set('trust proxy', 1);
const PORT = process.env.PORT || 3000;

// Security & Parsing Middleware
app.use(helmet());
app.use(cors());
app.use(express.json());
app.use(pinoMiddleware);
app.use(activeRequestsMiddleware);

// Initialize Core Services
const cookieManager = new CookieManager();
const hasCookies = cookieManager.init();

const ytdlpEngine = new YtdlpEngine(cookieManager);
const cacheLayer = new CacheLayer();
const circuitBreaker = new CircuitBreaker({
    failureThreshold: 5,
    resetTimeout: 30000 // 30s
});

// Graceful Shutdown Hook
let server;
const shutdown = async (signal) => {
    logger.info(`Received ${signal}, shutting down gracefully...`);
    if (server) {
        server.close(async () => {
            logger.info('HTTP server closed.');
            await cacheLayer.close();
            process.exit(0);
        });

        // Force exit after 10s if connections are hanging
        setTimeout(() => {
            logger.warn('Forcing shutdown after 10s timeout.');
            process.exit(1);
        }, 10000).unref();
    } else {
        process.exit(0);
    }
};

process.on('SIGTERM', () => shutdown('SIGTERM'));
process.on('SIGINT', () => shutdown('SIGINT'));

const validateRequest = (req, res, next) => {
    const errors = validationResult(req);
    if (!errors.isEmpty()) {
        const err = new Error('Validation failed');
        err.status = 400;
        err.details = errors.array();
        return next(err);
    }
    next();
};

/**
 * Health check endpoint
 */
app.get('/', (req, res) => {
  res.json({
    status: 'healthy',
    service: 'youtube-music-wrapper',
    version: '1.1.0',
    cookies_available: cookieManager.hasCookies,
    circuit_state: circuitBreaker.state
  });
});

app.get('/health', (req, res) => {
  res.status(200).send('OK');
});

/**
 * Prometheus Metrics Endpoint
 */
app.get('/metrics', async (req, res) => {
    try {
        res.set('Content-Type', register.contentType);
        res.end(await register.metrics());
    } catch (ex) {
        res.status(500).end(ex);
    }
});

/**
 * Cache Invalidation Endpoint (Admin)
 */
app.post('/flush-cache', async (req, res, next) => {
    try {
        await cacheLayer.invalidate();
        res.json({ status: 'success', message: 'Caches invalidated' });
    } catch (err) {
        next(err);
    }
});

/**
 * Search YouTube Music
 * GET /search?q=<query>&limit=<n>
 */
app.get('/search',
    limiters.search,
    [
        query('q').notEmpty().withMessage('Missing query parameter').trim(),
        query('limit').optional().isInt({ min: 1, max: 20 }).toInt()
    ],
    validateRequest,
    async (req, res, next) => {
        try {
            const query = req.query.q;
            const limit = req.query.limit || 5;

            // 1. Check Cache
            const cachedResult = await cacheLayer.getSearch(query, limit);
            if (cachedResult) {
                metrics.cacheHits.labels('search').inc();
                res.set('Cache-Control', 'public, max-age=300'); // 5m
                return res.json({
                    data: cachedResult,
                    total: cachedResult.length,
                    query: query,
                    cached: true
                });
            }

            // 2. Execute via Circuit Breaker
            const timer = metrics.ytSearchDuration.startTimer();
            const results = await circuitBreaker.execute(
                ytdlpEngine.search.bind(ytdlpEngine),
                [query, limit],
                { maxRetries: 2 }
            );
            timer();

            // 3. Set Cache
            if (results && results.length > 0) {
                 await cacheLayer.setSearch(query, limit, results);
            }

            res.set('Cache-Control', 'public, max-age=300'); // 5m
            res.json({
                data: results,
                total: results.length,
                query: query,
                cached: false
            });

        } catch (error) {
            if (error.is403) {
                 await cacheLayer.invalidate();
            }
            next(error);
        }
});

/**
 * Get track stream URL
 * GET /track/:id
 */
app.get('/track/:id',
    limiters.track,
    [
        param('id').matches(/^[a-zA-Z0-9_-]{11}$/).withMessage('Invalid video ID')
    ],
    validateRequest,
    async (req, res, next) => {
        try {
            const videoId = req.params.id;

            // 1. Check Cache
            const cachedResult = await cacheLayer.getTrack(videoId);
            if (cachedResult) {
                metrics.cacheHits.labels('track').inc();
                res.set('Cache-Control', 'public, max-age=2700'); // 45m
                return res.json({ ...cachedResult, cached: true });
            }

            const videoUrl = `https://www.youtube.com/watch?v=${videoId}`;

            // 2. Execute via Circuit Breaker
            const result = await circuitBreaker.execute(
                ytdlpEngine.extract.bind(ytdlpEngine),
                [videoUrl, videoId],
                { maxRetries: 3 }
            );

            // 3. Set Cache
            await cacheLayer.setTrack(videoId, result);
            metrics.ytExtractionSuccess.inc();

            res.set('Cache-Control', 'public, max-age=2700'); // 45m
            res.json({ ...result, cached: false });

        } catch (error) {
            if (error.is403) {
                await cacheLayer.invalidate();
           }
            next(error);
        }
});

/**
 * Extract from full URL
 * GET /extract?url=<youtube_url>
 */
app.get('/extract',
    limiters.extract,
    [
        query('url').isURL().withMessage('Invalid URL parameter')
    ],
    validateRequest,
    async (req, res, next) => {
        try {
            const url = req.query.url;

            const result = await circuitBreaker.execute(
                ytdlpEngine.extract.bind(ytdlpEngine),
                [url, null],
                { maxRetries: 2 }
            );

            metrics.ytExtractionSuccess.inc();
            res.json(result);

        } catch (error) {
             if (error.is403) {
                await cacheLayer.invalidate();
            }
            next(error);
        }
});

// Global Error Handler
app.use(errorHandler);

server = app.listen(PORT, () => {
  logger.info(`🎵 YouTube Music Wrapper running on port ${PORT}`);
  logger.info(`🍪 Cookies available: ${hasCookies}`);
});
