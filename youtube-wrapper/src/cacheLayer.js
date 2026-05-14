const { LRUCache } = require('lru-cache');

class CacheLayer {
    constructor() {
        this.searchCache = new LRUCache({ max: 500, ttl: 1000 * 60 * 5 }); // 5 mins
        this.trackCache = new LRUCache({ max: 1000, ttl: 1000 * 60 * 45 }); // 45 mins
    }

    async getSearch(query, limit) {
        return this.searchCache.get(`${query}:${limit}`);
    }

    async setSearch(query, limit, results) {
        this.searchCache.set(`${query}:${limit}`, results);
    }

    async getTrack(videoId) {
        return this.trackCache.get(videoId);
    }

    async setTrack(videoId, result) {
        this.trackCache.set(videoId, result);
    }

    async invalidate() {
        this.searchCache.clear();
        this.trackCache.clear();
    }

    async close() {
        await this.invalidate();
    }
}

module.exports = CacheLayer;
