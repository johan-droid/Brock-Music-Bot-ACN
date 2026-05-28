# 🎵 Brook Music Bot

Telegram Voice Chat music bot that runs as a **client for an external track server**.

## 🚀 Quick Start

1. **Clone the repo**
   ```bash
   git clone https://github.com/johan-droid/Music-Bot
   cd Music-Bot
   ```

2. **Install Dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure Environment**
   Create a `.env` file with `BOT_TOKEN`, `API_ID`, `API_HASH`, and your external server URL in `MUSIC_MICROSERVICE_URL`.

4. **Run System**
   ```bash
   supervisord -n -c supervisor.conf
   ```

## 🔌 External Server Contract

The bot expects a separate HTTP service that can search and resolve tracks.

- `GET /search?q=<query>&limit=<n>`
- `POST /resolve`
- `GET /health`

Accepted search response shapes:

```json
{"items":[{"id":"123","title":"Song","artist":"Artist","source":"vk"}]}
```

or

```json
{"results":[{"track_id":"123","title":"Song","artist":"Artist","stream_url":"https://..."}]}
```

Accepted resolve response shapes:

```json
{"id":"123","title":"Song","artist":"Artist","url":"https://cdn.example/track.mp3","source":"vk"}
```

or

```json
{"track":{"track_id":"123","title":"Song","artist":"Artist","stream_url":"https://cdn.example/track.mp3"}}
```

Minimum useful fields:

- `id` or `track_id`
- `title`
- `artist` or `uploader`
- `url`, `stream_url`, `audio_url`, or `audio`
- optional: `duration`, `thumbnail`, `headers`, `source`

## 📖 Technical Documentation

The project follows strict IEEE documentation standards. Please refer to the following documents for deep technical details:

1. **[System Design Specification](SYSTEM_DESIGN_SPECIFICATION.md)**: Architecture, Music Engine, and VC Integration.
2. **[Operational Engineering Guide](OPERATIONAL_ENGINEERING_GUIDE.md)**: Deployment, Configuration, and Maintenance.
3. **[Research & Performance Analysis](RESEARCH_AND_PERFORMANCE_ANALYSIS.md)**: Stability metrics and research findings.

## 🛠️ Key Features

- **External-server client architecture**: playback, discovery, playlists, and mood search all fetch from your configured track service.
- **Endpoint failover**: Supports multiple music microservice URLs for resilience.
- **Track management**: collaborative playlists, queueing, radio shows, and cached lookup all work through stored track references.
- **Service diagnostics**: `/serverhealth` checks whether the configured remote endpoints are reachable.
- **High Fidelity**: Up to 320kbps audio with EBU R128 normalization.
- **Command-safe refactor**: `/play`, `/vibe`, playlists, and Song Hunter all run through shared backend resolution.

## 🧭 Notes

- This repo now treats the music server as external infrastructure.
- `docker-compose.yml` is bot-only by default.
- `render.yaml` deploys only the bot service and expects you to supply `MUSIC_MICROSERVICE_URL`.
- `vk_music_backend.py` can still be kept around as a reference implementation, but the bot no longer depends on it locally.

---
*Built with ❤️ by the Brook Music Team.*
