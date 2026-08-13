# Brook Music Bot API Documentation

## Overview

The bot exposes an HTTP server (FastAPI) for health checks, metrics, Telegram webhooks, and a protected admin panel. The server runs on the port in the `PORT` environment variable (skipped entirely in worker mode when `PORT` is not set).

## Server

The FastAPI server is started by `app/core/bot.py::start_health_server()` and bound to `0.0.0.0:<PORT>`.

## Endpoints

| Method | Path                      | Auth                        | Description                          |
| ------ | ------------------------- | --------------------------- | ------------------------------------ |
| GET    | `/`                       | None                        | Health check (returns `OK`)          |
| GET    | `/health`                 | None                        | Health check (returns `OK`)          |
| POST   | `/webhook`                | None                        | Telegram update webhook (optional)   |
| GET    | `/metrics`                | Bearer token (optional)     | JSON metrics                        |
| GET    | `/metrics/prometheus`     | None                        | Prometheus metrics                   |
| GET    | `/admin/`                 | HTTP Basic (`admin`)        | Admin dashboard (HTML)               |
| GET    | `/admin/api/stats`        | HTTP Basic (`admin`)        | System + bot statistics              |
| GET    | `/admin/api/queues`       | HTTP Basic (`admin`)        | Live queues for active voice chats   |
| POST   | `/admin/api/action`       | HTTP Basic (`admin`)        | Perform forced action                |

---

## 1. Health Check

```
GET /health
```

Returns HTTP 200 with body `OK`. Used by platform health checks (Docker `HEALTHCHECK`, Heroku).

`GET /` behaves identically.

---

## 2. Telegram Webhook (optional)

```
POST /webhook
```

Only registered when `WEBHOOK_URL` is configured. The path can be changed via `WEBHOOK_PATH` (default `/webhook`). The bot forwards Telegram update payloads to its Pyrogram client.

---

## 3. JSON Metrics (optional)

```
GET /metrics
```

Enabled only when `METRICS_HTTP_ENABLED=true`.

**Authentication:**

- If `METRICS_HTTP_TOKEN` is set, a token is required in either:
  - `Authorization: Bearer <token>` header
  - `?token=<token>` query parameter

**Response (JSON):**
```json
{
  "timestamp": "2026-08-13T12:00:00.000000",
  "uptime_seconds": 86400.0,
  "total_samples": 205,
  "stats_by_action": {
    "play": {
      "count": 120,
      "total_time_ms": 40824.0,
      "avg_time_ms": 340.2,
      "min_time_ms": 10,
      "max_time_ms": 900,
      "cache_hits": 0,
      "cache_misses": 120,
      "cache_hit_rate": 0.0
    }
  },
  "recent_metrics": [
    {
      "action": "play",
      "response_time_ms": 340.2,
      "cache_hit": false,
      "db_time_ms": 2.1
    }
  ]
}
```

Note: `stats_by_action` and `recent_metrics` are empty until callbacks are recorded. Fields such as `total_time_ms`, `min_time_ms`, `max_time_ms`, `cache_hits`, and `cache_misses` are present on every action entry.

---

## 4. Prometheus Metrics (optional)

```
GET /metrics/prometheus
```

Enabled only when `METRICS_PROMETHEUS_ENABLED=true`. Returns `text/plain` in Prometheus exposition format:

```
# HELP musicbot_callback_total Total callbacks received per action
# TYPE musicbot_callback_total counter
musicbot_callback_total{action="play"} 120
musicbot_callback_avg_ms{action="play"} 340.2
musicbot_total_samples 205
```

Note: the `musicbot_callback_avg_ms` line has no `# HELP`/`# TYPE` entry and the `# TYPE musicbot_callback_total counter` line is emitted even when no samples exist yet.

---

## 5. Admin Panel

The admin panel is mounted at `/admin`. All admin routes require **HTTP Basic Auth** with username `admin` and password set by `ADMIN_PASSWORD`.

> If `ADMIN_PASSWORD` is not configured, admin routes return `503` (disabled).

### 5.1 Dashboard

```
GET /admin/
```

Returns an HTML dashboard page.

### 5.2 Statistics

```
GET /admin/api/stats
```

**Response:**
```json
{
  "uptime": 86400,
  "memory_percent": 45.2,
  "cpu_percent": 12.5,
  "active_vcs": 1,
  "total_users": 14,
  "total_tracks_played": 0,
  "music_microservice": {
    "configured": true,
    "healthy": true,
    "endpoints": [
      {
        "url": "https://music.example.com/health",
        "ok": true,
        "status": 200
      }
    ]
  },
  "errors": []
}
```

### 5.3 Live Queues

```
GET /admin/api/queues
```

Returns a map of active voice chat IDs to their current track and queue:

```json
{
  "-100123456789": {
    "current": { "title": "Never Gonna Give You Up", "url": "https://...", "duration": 212, "source": "youtube" },
    "queue": [
      { "title": "Together Forever", "url": "https://...", "duration": 180, "source": "youtube" }
    ]
  }
}
```

### 5.4 Forced Actions

```
POST /admin/api/action
```

**Request body:**
```json
{
  "action": "leave_vc",
  "chat_id": -100123456789,
  "message": "optional"
}
```

**Supported actions:**

| Action          | Extra field | Description                        |
| --------------- | ----------- | ---------------------------------- |
| `restart`       | -           | Restart the bot process            |
| `clear_caches`  | -           | Clear cache keys                   |
| `leave_vc`      | `chat_id`   | Force-leave a voice chat           |
| `broadcast`     | `message`   | Trigger a broadcast                |

Returns `400` with `{"detail": "Invalid action"}` for unknown actions.

---

## Error Responses

Standard FastAPI error format:

```json
{
  "detail": "Error description"
}
```

### Common Error Codes

- `400 Bad Request` - Invalid action or request
- `401 Unauthorized` - Invalid or missing authentication credentials
- `503 Service Unavailable` - Admin panel disabled (`ADMIN_PASSWORD` not set)

---

## Configuration Reference

| Env var                     | Default      | Effect                                         |
| --------------------------- | ------------ | ---------------------------------------------- |
| `PORT`                      | (unset)      | Port for the HTTP server. Unset = worker mode (server skipped) |
| `ADMIN_PASSWORD`            | (unset)      | Password for `/admin/*`. Unset = admin disabled |
| `METRICS_HTTP_ENABLED`      | `false`      | Enable `GET /metrics`                          |
| `METRICS_HTTP_TOKEN`        | (unset)      | Bearer token for `GET /metrics`                |
| `METRICS_PROMETHEUS_ENABLED`| `false`      | Enable `GET /metrics/prometheus`               |
| `WEBHOOK_URL`               | (unset)      | Register the Telegram webhook endpoint         |
| `WEBHOOK_PATH`              | `/webhook`   | Path for the webhook endpoint                  |

---

## Usage Examples

### cURL

```bash
# Health check
curl https://your-bot-url/health

# Admin stats (Basic auth)
curl -u admin:your-password https://your-bot-url/admin/api/stats

# JSON metrics (Bearer token)
curl -H "Authorization: Bearer your-token" https://your-bot-url/metrics

# Leave a voice chat
curl -u admin:your-password \
  -X POST https://your-bot-url/admin/api/action \
  -H "Content-Type: application/json" \
  -d '{"action":"leave_vc","chat_id":-100123456789}'
```

### Python

```python
import requests

BASE_URL = "https://your-bot-url"
ADMIN_PASSWORD = "your-password"

# Health check
print(requests.get(f"{BASE_URL}/health").text)

# Admin stats
stats = requests.get(f"{BASE_URL}/admin/api/stats", auth=("admin", ADMIN_PASSWORD))
print(stats.json())
```

### JavaScript

```javascript
const BASE_URL = "https://your-bot-url";

// Admin stats
const stats = await fetch(`${BASE_URL}/admin/api/stats`, {
  headers: { Authorization: `Basic ${btoa("admin:your-password")}` }
});
console.log(await stats.json());
```

---

## Notes

- The HTTP server is **optional**: in worker mode (no `PORT` env var) it is skipped entirely.
- The health check returns plain text `OK` and is the canonical liveness probe.
- All admin endpoints are disabled until `ADMIN_PASSWORD` is set.
- Metrics endpoints are disabled by default; enable them via the config flags above.
