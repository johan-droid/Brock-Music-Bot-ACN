# Operational Engineering Guide
**Project:** Brook Music Bot
**Version:** 3.0.0
**Updated:** May 28, 2026

## 1. What This Guide Covers

This guide explains how to run, configure, and maintain the current bot.

The most important operational fact is simple:

**This repository deploys the Telegram bot. Your music server is deployed separately.**

If the bot cannot reach the external music server, search and playback resolution will fail even if the Telegram side is healthy.

## 2. Minimum Working Setup

For a basic working deployment, users need:

- a Telegram app `API_ID`
- a Telegram app `API_HASH`
- a BotFather `BOT_TOKEN`
- an `OWNER_ID`
- at least one assistant session
- one working external music server URL in `MUSIC_MICROSERVICE_URL`

The assistant session can be supplied as:

- `SESSION_STRING_1`
- `SESSION_FILE_PATH_1`
- `SESSION_FILE_B64_1`

Only one of those is needed for the first assistant.

## 3. Deployment Shapes

### 3.1 Smallest Local or VPS Setup

Recommended for first-time users:

- run the bot from this repo
- use SQLite for cache and database
- connect to one external track server
- use a single assistant account

This is the easiest path to a stable first deployment.

### 3.2 Cloud Bot + Separate Music Server

Recommended when the bot and music service are hosted independently:

- deploy the bot on Render, Docker, or a VPS
- deploy the track server wherever you prefer
- set `MUSIC_MICROSERVICE_URL`
- optionally add Redis and a hosted database

### 3.3 Higher-Reliability Setup

Recommended for busier groups:

- multiple assistant sessions
- Redis or Upstash Redis for faster cache behavior
- Supabase or Neon for hosted persistence
- metrics endpoint enabled

## 4. Environment Variable Strategy

The repo uses environment variables as the main source of truth.

Use the included `.env.example` as the user-facing template. It is organized into:

- required values
- choose-one authentication options
- recommended optional settings
- advanced voice and deployment options
- troubleshooting notes

Recommended workflow:

1. Copy `.env.example` to `.env`
2. Fill only the required values first
3. Confirm the bot boots
4. Add cache, metrics, webhook, and extra assistants later

## 5. Assistant Authentication

Assistant accounts are critical for voice chat playback.

For each assistant slot, the bot checks authentication in this order:

1. `SESSION_STRING_n`
2. `SESSION_FILE_PATH_n`
3. `SESSION_FILE_B64_n`

That means a string session wins if multiple methods are filled for the same slot.

Operational advice:

- use one assistant first
- only add more assistants if you actually need more concurrent chats
- keep those accounts healthy and free from Telegram restrictions

## 6. External Music Server Operations

The bot expects a remote service that responds quickly and consistently.

Recommended behavior from the server side:

- search endpoint available at `/search`
- resolve endpoint available at `/resolve`
- health endpoint available at `/health`

Bot-side controls:

- `MUSIC_MICROSERVICE_URL`

## 7. Storage and Cache Choices

### 7.1 Local-Friendly Default

If no hosted cache or database is configured, the bot can still run with:

- `SQLITE_CACHE_PATH`
- `SQLITE_DB_PATH`

That is the most forgiving setup for small deployments.

### 7.2 Faster Cache

Use one of these if you want better cache performance:

- Redis via `REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD`
- Upstash Redis via `UPSTASH_REDIS_REST_URL`, `UPSTASH_REDIS_REST_TOKEN`

### 7.3 Hosted Persistence

Use one of these when you want application state outside the bot container:

- `SUPABASE_URL` + `SUPABASE_KEY`
- `NEON_DATABASE_URL`
- `MONGO_URI` for legacy or existing deployments

## 8. Startup Modes

The bot can run in two main Telegram delivery modes:

- **Long polling**
  Easiest default for most users.

- **Webhook mode**
  Use `WEBHOOK_URL`, `WEBHOOK_PATH`, and optional `WEBHOOK_SECRET` when the deployment platform expects webhook delivery.

If webhook variables are missing, the bot falls back to polling behavior.

## 9. Health, Metrics, and Observability

### 9.1 Built-In Health

The bot includes internal runtime checks and can expose lightweight HTTP status behavior when deployed behind a platform port.

Users should monitor:

- bot startup success
- assistant login success
- external music server reachability
- voice chat join/playback behavior

### 9.2 Metrics

Optional env flags:

- `METRICS_HTTP_ENABLED`
- `METRICS_HTTP_TOKEN`
- `METRICS_PROMETHEUS_ENABLED`

These are helpful when the bot is deployed in a long-running hosted environment and you want structured insight into activity and failures.

## 10. Docker and Render Notes

### 10.1 Docker

`docker-compose.yml` in this repo is intentionally **bot-only**.

It does not launch a bundled track server. Users must point the bot at an external server they run elsewhere.

### 10.2 Render

`render.yaml` deploys the bot container and expects secrets to be filled in the Render dashboard.

Important point:

- do not expect `render.yaml` to provision the music backend for you

## 11. Common Failure Cases

### 11.1 Bot Starts but Search Fails

Likely causes:

- `MUSIC_MICROSERVICE_URL` is missing
- the music server is down
- the server path differs from the expected `/search` or `/resolve`

### 11.2 Bot Does Not Join Voice Chat

Likely causes:

- assistant session is invalid
- assistant account is restricted
- the account is not allowed in the group
- Telegram voice chat is not active and auto-start is disabled

Check:

- `SESSION_*` values
- `AUTO_START_VC`
- group permissions for the assistant account

### 11.3 Bot Runs but State Resets Often

Likely causes:

- SQLite files are not being persisted
- container filesystem is ephemeral
- no hosted database or mounted volume is configured

### 11.4 Metrics or Webhook Do Not Work

Likely causes:

- missing `PORT` in the platform environment
- incorrect webhook URL
- metrics enabled without expected routing or token usage

## 12. Upgrade Guidance

When updating the bot:

1. keep a backup of your `.env`
2. compare your current env file with the latest `.env.example`
3. review README and this guide for new required settings
4. test with one assistant and one known working search query

## 13. Practical Recommendation

For most users, the best operational path is:

- start with one assistant
- use SQLite first
- connect one stable external music server
- run in polling mode
- add Redis, Neon, Supabase, or webhooks only when the basic flow is already stable

That path keeps setup simple and reduces the number of moving parts during first deployment.
