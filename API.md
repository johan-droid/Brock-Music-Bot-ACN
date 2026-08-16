# Brook Music Bot API Documentation

## Overview

Brook Music Bot exposes an HTTP server for health checks, Prometheus / JSON metrics, Telegram webhooks, and an administrative dashboard.

The server is supported across both engines:
- **Rust Engine** (`rust_backend/src/api/mod.rs`): Powered by **Axum** 0.7 & Tokio.
- **Python Engine** (`backend/app/api.py`): Powered by **FastAPI** & Uvicorn.

The server runs on the port specified in the `PORT` environment variable (skipped entirely in worker mode when `PORT` is omitted or unset).

---

## Server Initialization

- **Rust**: Spawns an asynchronous Axum HTTP service bound to `0.0.0.0:<PORT>` in `rust_backend/src/main.rs`.
- **Python**: Started by `backend/app/core/bot.py::start_health_server()` and bound to `0.0.0.0:<PORT>`.

---

## Endpoints Summary

| Method | Path                      | Auth                        | Description                          |
| ------ | ------------------------- | --------------------------- | ------------------------------------ |
| GET    | `/`                       | None                        | Health check (returns `OK`)          |
| GET    | `/health`                 | None                        | Liveness probe check (returns `OK`)  |
| POST   | `/webhook`                | None                        | Telegram update webhook (optional)   |
| GET    | `/metrics`                | Bearer token (optional)     | JSON metrics payload                |
| GET    | `/metrics/prometheus`     | None                        | Prometheus exposition format text    |
| GET    | `/admin/`                 | HTTP Basic (`admin`)        | Admin dashboard (HTML)               |
| GET    | `/admin/api/stats`        | HTTP Basic (`admin`)        | System + bot statistics              |
| GET    | `/admin/api/queues`       | HTTP Basic (`admin`)        | Live queues for active voice chats   |
| POST   | `/admin/api/action`       | HTTP Basic (`admin`)        | Perform forced action                |

---

## 1. Health Check

```http
GET /health
```

Returns HTTP `200 OK` with body `OK`. Used by platform liveness checks (Docker `HEALTHCHECK`, Kubernetes probes, Render, Railway, Heroku).

`GET /` behaves identically.

---

## 2. Telegram Webhook (Optional)

```http
POST /webhook
```

Only registered when `WEBHOOK_URL` is configured. The endpoint path can be customized via `WEBHOOK_PATH` (default `/webhook`). The bot processes incoming Telegram webhook update payloads.

---

## 3. JSON Metrics (Optional)

```http
GET /metrics
```

Enabled when `METRICS_HTTP_ENABLED=true`.

### Authentication

If `METRICS_HTTP_TOKEN` is set, requests must pass the token via:
- `Authorization: Bearer <token>` header, OR
- `?token=<token>` query parameter

### Response (JSON)
```json
{
  "timestamp": "2026-08-16T12:00:00.000000Z",
  "uptime_seconds": 86400.0,
  "active_vcs": 3,
  "status": "healthy"
}
```

---

## 4. Prometheus Metrics (Optional)

```http
GET /metrics/prometheus
```

Enabled when `METRICS_PROMETHEUS_ENABLED=true`. Returns `text/plain` formatted for Prometheus scraper collection:

```prometheus
# HELP musicbot_active_voice_chats Number of active voice chats
# TYPE musicbot_active_voice_chats gauge
musicbot_active_voice_chats 3
musicbot_uptime_seconds 86400
```

---

## 5. Admin Panel & API

The admin dashboard is mounted at `/admin/`. All admin endpoints require **HTTP Basic Authentication**:
- **Username**: `admin`
- **Password**: Set via `ADMIN_PASSWORD` environment variable

> ⚠️ If `ADMIN_PASSWORD` is not configured, admin endpoints return `503 Service Unavailable` or `401 Unauthorized`.

### 5.1 Dashboard UI
```http
GET /admin/
```
Returns an HTML dashboard page for managing active calls and system health.

### 5.2 System Statistics
```http
GET /admin/api/stats
```

**Response (JSON):**
```json
{
  "uptime": 86400,
  "memory_percent": 15.4,
  "cpu_percent": 2.1,
  "active_vcs": 2,
  "engine": "Rust (Tokio / Axum / Teloxide)",
  "music_microservice": {
    "configured": true,
    "healthy": true
  }
}
```

### 5.3 Live Voice Chat Queues
```http
GET /admin/api/queues
```

Returns a map of active chat IDs to their currently playing track and queued setlist:

```json
{
  "-100123456789": {
    "current": {
      "title": "Binks' Sake",
      "url": "https://...",
      "duration": 210,
      "source": "youtube",
      "requested_by": 123456
    },
    "queue_len": 4,
    "loop_mode": "Off",
    "is_paused": false
  }
}
```

### 5.4 Forced Administrative Actions
```http
POST /admin/api/action
```

**Request Body (JSON):**
```json
{
  "action": "leave_vc",
  "chat_id": -100123456789,
  "message": "Maintenance restart"
}
```

**Supported Actions:**

| Action          | Fields | Description |
| --------------- | ----------- | ---------------------------------- |
| `restart`       | - | Restart the bot process |
| `clear_caches`  | - | Clear in-memory Moka / Redis caches |
| `leave_vc`      | `chat_id` | Force-leave a voice chat session |
| `broadcast`     | `message` | Trigger owner message broadcast |

---

## Configuration Reference

| Environment Variable | Default | Description |
| :--- | :--- | :--- |
| `PORT` | (unset) | Port for the HTTP server. Unset = worker mode (server skipped). |
| `ADMIN_PASSWORD` | (unset) | HTTP Basic Auth password for `/admin/*`. Unset = admin disabled. |
| `METRICS_HTTP_ENABLED` | `false` | Enable `GET /metrics` JSON endpoint. |
| `METRICS_HTTP_TOKEN` | (unset) | Bearer token requirement for `GET /metrics`. |
| `METRICS_PROMETHEUS_ENABLED` | `false` | Enable `GET /metrics/prometheus` endpoint. |
| `WEBHOOK_URL` | (unset) | Register Telegram webhook endpoint URL. |
| `WEBHOOK_PATH` | `/webhook` | Path for the webhook endpoint. |

---

## Code & Usage Examples

### cURL

```bash
# Health check
curl http://localhost:8000/health

# Admin statistics (Basic Auth)
curl -u admin:supersecret http://localhost:8000/admin/api/stats

# Force clear caches
curl -u admin:supersecret \
  -X POST http://localhost:8000/admin/api/action \
  -H "Content-Type: application/json" \
  -d '{"action":"clear_caches"}'
```

### Rust (`reqwest`)

```rust
use reqwest::Client;

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let client = Client::new();
    let res = client
        .get("http://localhost:8000/admin/api/stats")
        .basic_auth("admin", Some("supersecret"))
        .send()
        .await?;
    println!("Stats: {}", res.text().await?);
    Ok(())
}
```
