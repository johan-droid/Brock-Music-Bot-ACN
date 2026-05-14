const rateLimit = require('express-rate-limit');
const promClient = require('prom-client');

// Rate Limiters
const limiters = {
    search: rateLimit({
        windowMs: 15 * 60 * 1000, // 15 minutes
        max: 100, // limit each IP to 100 requests per windowMs
        message: { error: 'Too many search requests, please try again later.' }
    }),
    track: rateLimit({
        windowMs: 15 * 60 * 1000, // 15 minutes
        max: 200, // limit each IP to 200 requests per windowMs
        message: { error: 'Too many track requests, please try again later.' }
    }),
    extract: rateLimit({
        windowMs: 15 * 60 * 1000, // 15 minutes
        max: 100, // limit each IP to 100 requests per windowMs
        message: { error: 'Too many extract requests, please try again later.' }
    })
};

// Error Handler
const errorHandler = (err, req, res, next) => {
    const status = err.status || 500;
    const message = err.message || 'Internal Server Error';
    const details = err.details || undefined;

    res.status(status).json({
        error: message,
        details: details
    });
};

// Prometheus Metrics
const register = new promClient.Registry();
promClient.collectDefaultMetrics({ register });

const metrics = {
    cacheHits: new promClient.Counter({
        name: 'youtube_wrapper_cache_hits_total',
        help: 'Total number of cache hits',
        labelNames: ['type'],
        registers: [register]
    }),
    ytExtractionSuccess: new promClient.Counter({
        name: 'youtube_wrapper_extraction_success_total',
        help: 'Total number of successful yt-dlp extractions',
        registers: [register]
    }),
    ytSearchDuration: new promClient.Histogram({
        name: 'youtube_wrapper_search_duration_seconds',
        help: 'Duration of yt-dlp search execution',
        registers: [register]
    })
};

const activeRequestsMiddleware = (req, res, next) => {
    next();
};

module.exports = {
    limiters,
    errorHandler,
    metrics,
    register,
    activeRequestsMiddleware
};
