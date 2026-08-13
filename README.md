# 🎵 Brook Music Bot

<p align="center">
  <img src="assets/brook_readme_banner.svg" alt="Brook Music Bot animated banner" width="100%" />
</p>

<p align="center">
  <img src="assets/brook_start.png" alt="Brook Music Bot artwork" width="420" />
</p>

Brook Music Bot brings a full Soul King vibe to Telegram voice chats.  
It is built around **Brook from One Piece**: stylish stage energy, playful setlist language, and a music-first group experience that feels more like a live show than a utility bot.

## Why People Like It

- Brook-themed personality across commands, queue messages, and concert prompts
- Smooth voice chat playback for groups and communities
- Mood search, saved setlists, and collaborative playlist-style flows
- Works with your own external music server, so you can decide where tracks come from
- Designed to feel lively, fun, and easy to run

## What It Does

Brook can:

- play songs into Telegram voice chats
- manage queues and encore-style looping
- search by vibe or mood
- save and replay setlists
- check whether your music server is awake and reachable

## Quick Setup

1. Clone the repo
   ```bash
   git clone https://github.com/johan-droid/Brock-Music-Bot-ACN
   cd Brock-Music-Bot-ACN
   ```

2. Install dependencies
   ```bash
   cd backend
   pip install -r requirements.txt
   ```

3. Copy `.env.example` to `.env.local`, then add your Telegram credentials, assistant session, and music server URL

4. Start the bot
   ```bash
   python -m app
   ```

## Commands

### 🎵 Playback

| Command | Description |
|---------|-------------|
| `/play [song]` | Search and play a track |
| `/vplay [query]` | Play from VK / Deezer sources |
| `/pause` | Pause the current performance |
| `/resume` | Resume paused playback |
| `/forceresume` | Force-resume (admin, clears stuck state) |
| `/stop` | Stop playback and leave voice chat (aliases: `/end`, `/cleanup`, `/off`) |
| `/replay` | Restart the current track from the beginning |
| `/seek [time]` | Jump to a position (e.g. `/seek 1:30`) |
| `/volume [0-200]` | Set playback volume |

### 📋 Queue Management

| Command | Description |
|---------|-------------|
| `/queue` | View the current setlist (alias: `/q`) |
| `/now` | Show the currently playing track (aliases: `/np`, `/nowplaying`) |
| `/skip` | Skip to the next track (alias: `/next`) |
| `/prev` | Play the previous track (alias: `/previous`) |
| `/shuffle` | Randomize the queue order |
| `/loop [off\|track\|queue]` | Toggle loop mode |
| `/remove [position]` | Remove a track by queue number (alias: `/rm`) |
| `/move [from] [to]` | Move a track to a new position |
| `/clearqueue` | Clear all queued tracks (admin) |

### 🔍 Music Discovery

| Command | Description |
|---------|-------------|
| `/vibe [mood]` | Let Brook pick tracks by feeling |
| `/moodsearch [description]` | Search by mood tags |
| `/mooddiscovery` | Browse Soul King-curated mood suggestions |

### 🗂 Setlists (Playlists)

| Command | Description |
|---------|-------------|
| `/plcreate [name]` | Create a new setlist archive |
| `/pladd [playlist] [query]` | Add a track to a setlist |
| `/plremove [playlist] [pos]` | Remove a track from a setlist |
| `/pllist` | List your saved setlists |
| `/plplay [playlist]` | Perform a saved setlist |
| `/plcollab [playlist]` | Toggle collaborative mode |
| `/plshare [playlist]` | Share a setlist with the group |
| `/plsync [playlist]` | Sync setlist changes across devices |

### 📻 Radio Shows

| Command | Description |
|---------|-------------|
| `/showcreate [name] [day] [time] [genre]` | Create a radio show slot (admin) |
| `/showadd [show_id] [query]` | Add a track to a show |
| `/showlist` | List all scheduled shows |
| `/showpreview [show_id]` | Preview a show's tracklist |
| `/showcancel [show_id]` | Cancel a scheduled show (admin) |
| `/showhistory` | View past show broadcasts |
| `/showtalk` | Open the show talk/live chat segment |

### 🎮 Song Hunter (Music Game)

| Command | Description |
|---------|-------------|
| `/starthunter` | Start a song-guessing game (alias: `/sh`) |
| `/stophunter` | End the current game (alias: `/stopsh`) |
| `/hunterboard` | View the leaderboard (alias: `/shboard`) |

### 🗳 Anonymous & Voting

| Command | Description |
|---------|-------------|
| `/votemode [on\|off]` | Toggle voting mode for the group (admin) |
| `/anonplay [song]` | Request a song anonymously |

### 🎛 Effects & Timers

| Command | Description |
|---------|-------------|
| `/effects` | Open the audio effects menu (admin) |
| `/sleep [duration]` | Set a sleep timer (e.g. `/sleep 30m`) (admin) |
| `/cancelsleep` | Cancel the active sleep timer (admin) |
| `/setaggressive [on\|off]` | Toggle aggressive play mode (admin) |
| `/uptime` | Show bot uptime and scheduler status |

### 🔧 Utility

| Command | Description |
|---------|-------------|
| `/help` | Show the full command list |
| `/ping` | Check bot latency |
| `/serverhealth` | Check external music server status |
| `/userbotjoin` | Force assistant to join/create voice chat (admin) |
| `/vcdebug` | Inspect voice chat connection state (admin) |
| `/metrics` | View callback performance metrics (DM) |

### ⚔️ Administration

| Command | Description |
|---------|-------------|
| `/addsudo [user]` | Promote to sudo (owner) |
| `/delsudo [user]` | Revoke sudo access (owner) |
| `/sudolist` | List sudo users (sudo) |
| `/block [user]` | Block a user in this group (admin) |
| `/unblock [user]` | Unblock a user (admin) |
| `/gban [user]` | Globally ban across all groups (sudo) |
| `/ungban [user]` | Remove a global ban (sudo) |
| `/broadcast [message]` | Broadcast to all groups (owner) |
| `/stats` | Show bot statistics (sudo) |
| `/maintenance [on\|off]` | Toggle maintenance mode (sudo) |
| `/restart` | Restart the bot process (owner) |
| `/prunedb` | Clean stale database entries (sudo) |
| `/health` | System health report (owner DM) |
| `/lasterrors` | View recent error log (owner DM) |

## Theme

This bot leans hard into the Soul King mood:

- concert-style responses
- Brook-inspired stage language
- setlists instead of plain playlists
- a more playful group music experience overall

## Notes

- The bot expects a separate music server URL in `MUSIC_MICROSERVICE_URL`
- All backend code lives under `backend/` (`backend/app`), with deployment configs in `backend/deploy/`
- The docs in this repo now match the current client-bot stage of the project:
  - [API Documentation](API.md)
- There is also a more detailed `.env.example` now, so users can follow the setup step by step instead of guessing env names

---
*Yohohoho! Built for crews who like their music bots with a little more soul.*
