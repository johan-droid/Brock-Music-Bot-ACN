const fs = require('fs');
const path = require('path');

class CookieManager {
    constructor() {
        this.cookiesPath = path.join(__dirname, '..', 'cookies.txt');
        this.hasCookies = false;
    }

    init() {
        const cookiesEnv = process.env.YOUTUBE_COOKIES;
        if (cookiesEnv) {
            fs.writeFileSync(this.cookiesPath, cookiesEnv);
        }
        this.hasCookies = fs.existsSync(this.cookiesPath);
        return this.hasCookies;
    }

    getCookiesPath() {
        return this.cookiesPath;
    }
}

module.exports = CookieManager;
