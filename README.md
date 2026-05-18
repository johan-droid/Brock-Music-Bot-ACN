# 🎵 Brook Music Bot

The ultimate Telegram Music Bot with multi-source extraction, intelligent fallback, and premium voice chat streaming.

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
   Create a `.env` file with your `BOT_TOKEN`, `API_ID`, and `API_HASH`.

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

- **Multi-Source**: Parallel search across VK, and Deezer.
- **Intelligent Fallback**: Automatic source switching to ensure 99.9% playback success.
- **High Fidelity**: Up to 320kbps audio with EBU R128 normalization.
- **Distributed**: Specialized wrappers to bypass regional blocks and rate limits.

---
*Built with ❤️ by the Brook Music Team.*
