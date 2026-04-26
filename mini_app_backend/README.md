# Soul King Mini App Backend

This package is a dedicated backend surface for the Telegram Mini App.

## Start locally

```bash
pip install -r requirements.txt
uvicorn mini_app_backend:app --host 0.0.0.0 --port 8001 --reload
```

## Endpoints

- Health: `GET /health`
- Search: `GET /api/v1/search`
- Stream resolve/proxy: `POST /api/v1/stream/resolve`, `GET /api/v1/stream/proxy`
- Lobby: `/api/v1/lobby/*`
- Sessions: `/api/v1/sessions/*`
- Socket.IO: `/socket.io`

## Notes

- Uses existing `MusicBackend`, queue manager, and cache abstractions.
- Validates Telegram `initData` on API calls and socket handshake.
- Stream proxy URLs are short-lived and HMAC-signed.

## Mini App URL guidance

- The Telegram Mini App URL must be a valid HTTPS page URL, not the SDK script URL.
- Do not enter `https://telegram.org/js/telegram-web-app.js` as the Mini App URL.
- Use your deployed frontend URL instead, for example:
  - `https://your-domain.com/mini_app_frontend/index.html`

The page should load this script inside `<head>`:

```html
<script src="https://telegram.org/js/telegram-web-app.js"></script>
```

