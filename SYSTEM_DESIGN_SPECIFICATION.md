# SYSTEM DESIGN SPECIFICATION: MUSIC BOT INFRASTRUCTURE
**Standard Reference: IEEE Std 1016-2009 / IEEE Std 1233-1998**
**Version: 2.0.0**
**Date: May 14, 2026**

---

## 1. INTRODUCTION

### 1.1 Purpose
This document specifies the technical design and architectural requirements for the Brook Music Bot system. It serves as a definitive technical reference for developers and system administrators.

### 1.2 Scope
The system is an autonomous Telegram-based music delivery platform capable of real-time multi-source extraction, intelligent fallback orchestration, and high-fidelity Voice Chat (VC) streaming.

### 1.3 System Overview
The architecture is comprised of a primary Python-based controller and specialized Node.js wrappers. The system utilizes `pyrogram` for Telegram signaling and `py-tgcalls` for WebRTC voice streaming.

---

## 2. SYSTEM ARCHITECTURE

### 2.1 Component Decomposition
The system follows a micro-service inspired modular design, orchestrated via **Supervisord**.

| Component | Responsibility | Technology Stack |
|-----------|----------------|------------------|
| **Core Bot** | Command parsing, Session management, UI | Python (Pyrogram) |
| **Music Backend** | Search orchestration, Deduplication, Fallback | Python (Asyncio) |
| **VC Manager** | WebRTC stream injection, FFmpeg piping | Py-tgcalls |
| **Wrappers** | Platform-specific extraction (YT/JS) | Node.js (Express) |
| **Storage** | Persistence and Metadata caching | SQLite / MongoDB |

### 2.2 Process Orchestration
Processes are managed as a group to ensure atomic state transitions:
- `musicbot`: The primary controller and userbot manager.
- `youtube-wrapper`: Dedicated YouTube/YT-Music extraction engine.
- `jiosaavn-wrapper`: Dedicated JioSaavn/Direct extraction engine.

---

## 3. MUSIC EXTRACTION ENGINE

### 3.1 Multi-Source Search Orchestration
The engine executes parallel asynchronous searches across five primary tiers:
1. **YouTube Music Wrapper**: High-fidelity metadata and stream resolution.
2. **JioSaavn Wrapper**: Localized regional music support.
3. **VK Music / Deezer**: Fallback for restricted or high-quality audio.
4. **Supabase Index**: Global pre-indexed track repository.
5. **Direct Extraction**: On-the-fly `yt-dlp` parsing.

### 3.2 Intelligent Fallback Chain
To ensure 99.9% playback success, the system implements a recursive fallback algorithm:
1. **Source Hit**: Attempt extraction from the primary source metadata.
2. **Alternative Resolution**: If primary fails, resolve the track using secondary extractors via Title/Artist matching.
3. **Stream Preservation**: Preserve YouTube stream IDs if direct extraction fails to prevent dead links.
4. **Circuit Breaking**: Automatically disable failing extractors for 60 seconds after 5 consecutive timeouts.

---

## 4. VOICE CHAT INTEGRATION

### 4.1 Stream Engineering
Audio is delivered via `FFmpeg` pipes with specialized parameters:
- **Bitrate**: Adaptive (64kbps to 320kbps based on `AUDIO_QUALITY`).
- **Bit-depth**: 16-bit PCM.
- **Normalization**: EBU R128 Loudness Normalization enabled by default.
- **Parameters**: `-nostdin -vn -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5`.

### 4.2 WebRTC Signaling
The `CallManager` handles PyTgCalls sessions across multiple userbots (Assistants). It manages:
- Concurrent group calls (Load balanced).
- Automatic join/leave on queue state transitions.
- Health monitoring of voice sessions with 20s watchdog timers.

---

## 5. DATA MANAGEMENT & PERSISTENCE

### 5.1 Storage Hierarchy
1. **Hot Cache (Redis)**: Search results and active session metadata (TTL: 5.5h).
2. **Warm Storage (SQLite)**: Local queue persistence and temporary session files.
3. **Cold Storage (MongoDB/Supabase)**: User statistics, global settings, and track history.

### 5.2 Search Deduplication
Tracks are deduplicated using a composite key: `(lowercase(title) + artist)`.
This ensures search results across YouTube and JioSaavn are merged into a clean, unified list for the user.

---

## 6. SYSTEM RELIABILITY

### 6.1 Cold-Start Mitigation
For serverless-style deployments (Render Free Tier), the system implements a 65-second "Warmup" timeout on initial searches to allow downstream wrappers to spin up.

### 6.2 Error Diagnostics
The system utilizes a structured `summarize_exception` utility to provide actionable one-line diagnostics in production logs, suppressing verbose stack traces for known network failures.

---
*END OF SPECIFICATION*
