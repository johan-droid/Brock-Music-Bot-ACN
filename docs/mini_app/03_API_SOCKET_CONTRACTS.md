# Mini App API + Socket Contracts

Base URL examples:

- Backend API: `https://<railway-service>/api/v1`
- Socket.IO: `https://<railway-service>/socket.io`

Auth for every API/socket call:

- Header: `X-Telegram-Init-Data: <window.Telegram.WebApp.initData>`
- Or: `Authorization: tma <initData>`

## REST API

### `GET /health`

Purpose: infra health check.

### `GET /api/v1/search?query=<q>&limit=<n>`

Returns:

```json
{
  "query": "blinding lights",
  "limit": 20,
  "count": 3,
  "items": [
    {
      "title": "Blinding Lights",
      "artist": "The Weeknd",
      "duration": 200,
      "source": "vk",
      "stream_url": "vk://12345",
      "thumbnail": "https://..."
    }
  ]
}
```

### `POST /api/v1/stream/resolve`

Body:

```json
{
  "title": "Blinding Lights",
  "artist": "The Weeknd",
  "duration": 200,
  "source": "vk",
  "track_id": "12345",
  "stream_url": "vk://12345"
}
```

Returns resolved payload + signed proxy URL:

```json
{
  "url": "https://cdn.example/file.m3u8",
  "stream_url": "https://cdn.example/file.m3u8",
  "source": "vk",
  "proxy_url": "/api/v1/stream/proxy?url=...&exp=...&sig=...",
  "proxy_expires_at": 1760000000
}
```

### `GET /api/v1/stream/proxy?url=<encoded>&exp=<unix>&sig=<hmac>`

Purpose: byte-range compatible passthrough stream proxy.

- Supports `Range` request header.
- Forwards `Content-Range`, `Accept-Ranges`, `Content-Length`, `Content-Type`, `ETag`, `Last-Modified`.

### `GET /api/v1/lobby/{chat_id}`

Returns current lobby snapshot:

```json
{
  "chat_id": -1001234567890,
  "now_playing": {},
  "queue": [],
  "position": 0,
  "status": "idle",
  "participants": [],
  "version": 1,
  "updated_at": 1760000000
}
```

### `POST /api/v1/lobby/{chat_id}/queue/add`

Body:

```json
{
  "track": {
    "title": "Track A",
    "artist": "Artist A",
    "duration": 180,
    "source": "deezer",
    "track_id": "abc",
    "stream_url": "deezer://abc"
  },
  "play_next": false
}
```

### `POST /api/v1/lobby/{chat_id}/seek`

Body:

```json
{
  "position": 93
}
```

### `POST /api/v1/lobby/{chat_id}/track/change`

Body:

```json
{
  "track": {
    "title": "Track B",
    "artist": "Artist B",
    "duration": 210,
    "source": "vk",
    "track_id": "def",
    "stream_url": "vk://def"
  },
  "position": 0
}
```

### `GET /api/v1/sessions/me`

Returns per-user session document:

```json
{
  "user_id": 123456,
  "recent_tracks": [],
  "preferences": {},
  "updated_at": 1760000000
}
```

### `POST /api/v1/sessions/me/recent`

Body: same track payload shape as `/stream/resolve`.

### `PATCH /api/v1/sessions/me/preferences`

Body:

```json
{
  "autoplay": true,
  "visualizer_enabled": true,
  "theme": "soul-king-dark",
  "equalizer_preset": "pop"
}
```

## Socket.IO contracts

Namespace: default `/`

Handshake auth:

```json
{
  "initData": "<window.Telegram.WebApp.initData>"
}
```

### Client -> Server events

1. `join_lobby`

```json
{
  "chat_id": -1001234567890
}
```

2. `leave_lobby`

```json
{
  "chat_id": -1001234567890
}
```

3. `queue_update`

```json
{
  "chat_id": -1001234567890,
  "track": { "title": "Track A", "source": "vk", "stream_url": "vk://x" },
  "play_next": false
}
```

4. `track_change`

```json
{
  "chat_id": -1001234567890,
  "track": { "title": "Track B", "source": "deezer", "stream_url": "deezer://y" },
  "position": 0
}
```

5. `seek`

```json
{
  "chat_id": -1001234567890,
  "position": 42
}
```

### Server -> Client events

1. `lobby_state`

- Full snapshot broadcast after each mutation.
- Contains `version` for optimistic UI reconciliation.

## Versioning guidance

- Add `client_event_id` on mutating requests/events to support idempotency.
- Reject stale updates when `incoming.version < current.version`.
- Return `409` for REST conflicts; include latest server snapshot.

