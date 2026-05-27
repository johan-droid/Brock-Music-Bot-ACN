# 🎵 Brook Music Bot

Telegram Voice Chat music bot that now runs as a **pure microservice client** for music discovery/resolution.

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
   Create a `.env` file with `BOT_TOKEN`, `API_ID`, `API_HASH`, and `MUSIC_MICROSERVICE_URL`.

4. **Run System**
   ```bash
   supervisord -n -c supervisor.conf
   ```

## 📖 Technical Documentation

The project follows strict IEEE documentation standards. Please refer to the following documents for deep technical details:

1. **[System Design Specification](SYSTEM_DESIGN_SPECIFICATION.md)**: Architecture, Music Engine, and VC Integration.
2. **[Operational Engineering Guide](OPERATIONAL_ENGINEERING_GUIDE.md)**: Deployment, Configuration, and Maintenance.
3. **[Research & Performance Analysis](RESEARCH_AND_PERFORMANCE_ANALYSIS.md)**: Stability metrics and research findings.

## 🛠️ Key Features

- **Microservice-first architecture**: Bot never calls Jamendo or provider APIs directly.
- **Endpoint failover**: Supports multiple music microservice URLs for resilience.
- **High Fidelity**: Up to 320kbps audio with EBU R128 normalization.
- **Command-safe refactor**: `/play`, `/vibe`, playlists, and Song Hunter all run through shared backend resolution.

---
*Built with ❤️ by the Brook Music Team.*
