# 🎵 Brook Music Bot

<p align="center">
  <img src="assets/brook_readme_banner.svg" alt="Brook Music Bot animated banner" width="100%" />
</p>

<p align="center">
  <img src="assets/brook_start.png" alt="Brook Music Bot artwork" width="420" />
</p>

Brook Music Bot brings a full Soul King vibe to Telegram voice chats.  
Built around **Brook from One Piece**: stylish stage energy, playful setlist language, and a music-first group experience that feels more like a live show than a utility bot.

Now features a **high-performance, low-latency Rust Engine** ([rust_backend/](file:///home/ashutoshsahoo/Downloads/Nico%20Robin%20Management%20Bot/Brock-Music-Bot-ACN/rust_backend)) powered by Tokio, Teloxide, Axum, SQLx, Moka, and FFmpeg!

---

## ⚡ Key Highlights

- **Soul King Vibe**: Concert-style responses, Brook-inspired stage language, and setlists instead of plain queues.
- **Rust Core Engine (`rust_backend/`)**: Ultra-low memory footprint (<30 MB RAM), zero GIL lock contention, and high-throughput async processing via `tokio`.
- **Teloxide Bot Dispatcher**: Pure Rust Telegram Bot API framework with type-safe command routing and inline callback handlers.
- **Axum HTTP REST & Health API**: Integrated web server exposing `/health`, `/metrics`, `/metrics/prometheus`, and HTTP Basic Auth protected `/admin/*` dashboard.
- **Multi-Tier Caching & Persistence**: Fast in-memory caching (`moka`) backed by `sqlx` async database storage (SQLite / Neon Postgres).
- **Flexible Music Backend**: Multi-source resolution (YouTube, Deezer, VK, direct streams) with external microservice integration support.

---

## 🚀 Quick Setup

### Option 1: Rust Engine (Recommended for Performance)

1. **Clone the repository**
   ```bash
   git clone https://github.com/johan-droid/Brock-Music-Bot-ACN
   cd Brock-Music-Bot-ACN
   ```

2. **Configure Environment Variables**
   Copy `.env.example` to `.env.local` and add your credentials:
   ```bash
   cp backend/.env.example .env.local
   ```
   Add your `BOT_TOKEN`, `API_ID`, `API_HASH`, and optional `PORT`:
   ```env
   BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyZ
   API_ID=123456
   API_HASH=your_api_hash_here
   PORT=8000
   ADMIN_PASSWORD=supersecret
   ```

3. **Build & Run the Rust Bot**
   ```bash
   cargo run --release
   ```

### Option 2: Python Backend

1. Install Python dependencies:
   ```bash
   cd backend
   pip install -r requirements.txt
   ```

2. Start the Python bot:
   ```bash
   python -m app
   ```

---

## 🎵 Commands

### 🎵 Playback Controls

| Command | Description |
|---------|-------------|
| `/play [song]` | Search and play a track in the voice chat |
| `/pause` | Pause current live performance |
| `/resume` | Resume paused playback |
| `/skip` | Skip to the next track in setlist (alias: `/next`) |
| `/prev` | Play previous track from history |
| `/replay` | Restart current track from beginning |
| `/stop` | Stop playback and clear the stage (aliases: `/end`, `/cleanup`, `/off`) |
| `/volume [0-200]` | Set playback volume |

### 📋 Queue & Setlist Management

| Command | Description |
|---------|-------------|
| `/queue` | View current concert setlist (alias: `/q`) |
| `/now` | Display currently performing track & progress bar (aliases: `/np`, `/nowplaying`) |
| `/shuffle` | Randomize queued tracks |
| `/loop [off\|track\|queue]` | Toggle loop mode (Off, Repeat Track, Repeat Setlist) |

### 🔍 Music Discovery & Vibe

| Command | Description |
|---------|-------------|
| `/vibe [mood]` | Let Brook pick tracks by feeling |
| `/moodsearch [description]` | Search by mood tags |

### 🔧 Utility & Admin

| Command | Description |
|---------|-------------|
| `/help` | Show full command list and setlist instructions |
| `/ping` | Check bot stage latency |
| `/stats` | Display bot engine statistics & microservice health |
| `/addsudo [user]` | Promote user to Sudo (Owner only) |

---

## 🛠️ Architecture & Documentation

- [API Documentation](API.md) - Complete documentation for Axum / FastAPI HTTP endpoints (`/health`, `/metrics`, `/admin/*`).
- [Rust Backend README](rust_backend/README.md) - Rust crate documentation, build flags, and developer instructions.

---
*Yohohoho! Built for crews who like their music bots with a little more soul.*
