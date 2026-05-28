# System Design Specification
**Project:** Brook Music Bot
**Version:** 3.0.0
**Updated:** May 28, 2026

## 1. Purpose

This document describes the current architecture of Brook Music Bot as it exists today.

The bot is no longer a bundled "everything in one repo" music stack. It now runs as a **Telegram client bot** that talks to a **separate external track server** for music search and track resolution. That split is the most important architectural change in the current stage of the project.

## 2. Product Summary

Brook Music Bot is a Telegram voice chat music bot with a Brook / Soul King themed user experience. It is designed to:

- respond to Telegram bot commands
- join voice chats with one or more assistant accounts
- fetch track results from an external server
- resolve playable track metadata before streaming
- manage queues, setlists, mood search, and radio-style playback
- store state in lightweight local storage or optional hosted backends

## 3. High-Level Architecture

The running system has five main parts:

1. **Telegram Bot Layer**
   Handles commands, replies, menus, inline buttons, themed messaging, and group-facing user interaction.

2. **Assistant / Userbot Layer**
   One or more Pyrogram assistant sessions join voice chats and help the bot manage playback.

3. **Playback Layer**
   `py-tgcalls` and FFmpeg are used to inject audio into Telegram voice chats.

4. **External Music Service Layer**
   A separate server provides `/search`, `/resolve`, and `/health` style endpoints. The bot uses this service instead of embedding provider-specific music extraction logic in the bot runtime.

5. **Persistence and Cache Layer**
   The bot can use SQLite by default and optionally Redis, Supabase, Neon, or MongoDB depending on deployment needs.

## 4. Runtime Components

### 4.1 Core Bot

The core bot is responsible for:

- loading configuration
- starting the Telegram bot client
- registering command handlers
- exposing optional health and metrics endpoints
- coordinating shutdown and recovery behavior

Primary technologies:

- Python
- Pyrogram
- asyncio

### 4.2 Music Backend Client

The internal music backend no longer acts like a local multi-provider extractor. Its current role is to:

- call the configured external music service
- send search requests
- resolve stored track references back into playable metadata

Important configuration:

- `MUSIC_MICROSERVICE_URL`

### 4.3 Voice Chat Manager

The voice layer is responsible for:

- joining and leaving Telegram voice chats
- creating FFmpeg playback pipelines
- managing queue transitions
- enforcing playback timeouts
- supporting features like previous track, auto-start voice chat, and live now-playing updates

Important behavior controls:

- `AUDIO_QUALITY`
- `AUDIO_BITRATE`
- `AUDIO_LOUDNORM`
- `VC_PLAY_TIMEOUT`
- `AUTO_START_VC`
- `ASSISTANT_MAX_ACTIVE_CHATS`

### 4.4 Storage

The storage model is intentionally flexible.

Default local-friendly setup:

- SQLite cache
- SQLite database

Optional hosted or scaled setup:

- Redis or Upstash Redis for cache
- Supabase for application data
- Neon Postgres for database-backed persistence
- MongoDB where legacy deployments still use it

This lets users start with a low-friction local or single-container setup and move upward later without changing how the bot is used.

## 5. External Music Service Contract

The bot expects a music server that can support the following operations:

- **Search**: find tracks from a text query
- **Resolve**: turn a saved track reference or track ID into a playable result
- **Health**: confirm the external server is available

The bot is tolerant of a few response shapes, including payloads that return:

- `items`
- `results`
- `tracks`
- `data`

For resolve operations it also accepts nested keys such as:

- `track`
- `item`
- `result`
- `data`

This makes the bot easier to pair with custom external services without forcing one exact JSON format.

## 6. User-Facing Feature Areas

The current application stage includes:

- core play / pause / resume / skip queue controls
- Brook-themed `/start` and `/help`
- mood-based search and discovery
- saved playlists framed as setlists
- external server health checks
- radio show style playback and scheduled music behavior
- Brook-themed media and animated start experience

## 7. Configuration Model

The bot is configured almost entirely through environment variables.

There are four configuration groups users should care about most:

1. **Telegram credentials**
2. **Assistant session authentication**
3. **External music service connection**
4. **Optional storage and cache backends**

The repository now includes a detailed `.env.example` intended to be copied directly by users and filled in step by step.

## 8. Deployment Model

The current repo is designed around **bot-only deployment**.

That means:

- the bot container runs from this repository
- the music server is deployed separately
- `docker-compose.yml` does not start a bundled extractor service
- `render.yaml` deploys the bot only

This keeps the bot smaller, easier to maintain, and easier to point at a user-owned track service.

## 9. Reliability Approach

The current reliability model focuses on:

- external service failover through multiple base URLs
- graceful local fallback storage when Redis is absent
- optional long polling or webhook operation
- session credential normalization from several supported env names
- defensive parsing of external track server payloads

The bot also preserves some legacy database field names for compatibility, even though the runtime behavior is now generic and no longer Jamendo-specific.

## 10. Known Boundaries

The current system intentionally does **not** include:

- a bundled first-party extractor server in this repo
- automatic provisioning of the external music server
- a database migration that renames all old legacy track column names

Those are separate concerns from the current bot runtime and deployment model.

## 11. Recommended Mental Model

The cleanest way to think about the application today is:

> Brook Music Bot is a Telegram voice-chat client bot with a strong themed UX, powered by assistant accounts for playback and an external track server for search and resolution.

That is the current stage of the app, and all operational documentation should be read from that model.
