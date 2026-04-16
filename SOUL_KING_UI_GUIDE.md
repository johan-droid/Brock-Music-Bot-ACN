# 🎸 Soul King Concert-Themed Live UI

## Overview

The music bot now features a **Soul King concert-themed** Telegram interface with live progress tracking, rich visuals, and comprehensive controls. This is inspired by Brook's character from One Piece with a dark, golden aesthetic.

## Features

### 🎭 Live Progress Tracking
- **Real-time updates**: The now playing message updates **every 2-3 seconds** with live progress information
- **Animated progress bar**: Visual progress bar with gold fill effect showing song position
- **Live percentage**: Shows exactly how far through the song you are
- **Auto-cleanup**: Messages stop updating after the track ends

### 🎨 Soul King Concert Aesthetic
- **Dark theme**: Deep blue/black background with gold and purple accents
- **Skeleton artwork**: Optional images with decorative borders
- **Stage Effects**: Theater-style layout and formatting
- **Brook Quotes**: Rotates between multiple "Soul King" themed quotes based on playback state

### 📊 Rich Metadata Display
- **Song Title**: Large, prominent display
- **Artist Name**: Secondary artist/uploader info
- **Duration**: Total track length
- **Source Badge**: Visual indicator which platform the song came from:
  - 🟦 VK Music
  - 🎧 Deezer
  - ✈️ Telegram
- **Queue Position**: Shows where the track is in the queue
- **Queue Size**: Total songs waiting

### 🎮 Organized Inline Controls

#### Row 1: Playback (All Users)
- **⏸ Pause** / **▶️ Resume** - Toggle playback
- **⏭ Skip** - Jump to next song (admin only)
- **📋 Queue** - View upcoming songs
- **⚙️ More** - Additional options

#### Row 2: Effects (Admin Only)
- **🔊 / 🔉** - Volume up/down
- **🔁 Loop** - Cycle loop modes (off → current track → entire queue → off)
- **🔀 Shuffle** - Randomize queue order

#### Row 3: Info (All Users)
- **📊 Stats** - View bot statistics and current status
- **❓ Help** - Show command authority & usage guide

#### Row 4: Emergency (Admin Only)
- **🔄 Force Resume** - Clean stuck state and restart playback
- **⏹ Stop** - Halt playback and clear queue

### 🎨 Soul King Thumbnail Generation
When available, the bot generates a beautiful concert-style card with:
- Song artwork with gold border
- Track metadata on the right
- Live progress bar at the bottom
- Source and duration badges
- "Soul King FM" footer

## How to Use

### Playing Music
```
/play <song name or URL>
```
- A live now playing card appears immediately
- Card updates in real-time as your song plays
- Controls respond instantly with permission checks
- Automatically cleans up after the track ends

### Playback Controls via Inline Buttons
Simply tap the inline buttons below the now playing message:
- **Pause/Resume**: Pause the current song or resume from pause
- **Skip**: Jump to the next track (admin only)
- **Volume**: Adjust playback volume (admin only)

### Queue Management
```
/queue          - View upcoming tracks with controls
/shuffle        - Randomize track order (admin)
/clearqueue     - Remove all upcoming songs (admin)
/remove <pos>   - Remove a specific track (admin)
```

### Permission Levels

| Level | Role | Can Do |
|-------|------|--------|
| 5 | Owner | Everything + admin commands |
| 4 | Sudo User | Most admin commands |
| 3 | Group Admin | Play controls, manage queue, volume |
| 2 | VC Participant | (Reserved for future features) |
| 1 | Member | Play, pause, resume, queue view |
| 0 | Banned | Nothing (silently rejected) |

### Admin-Only Commands in UI
- ⏭ **Skip** - Jump to next song
- 🔀 **Shuffle** - Randomize queue
- 🔊/🔉 **Volume** - Adjust loudness
- 🔁 **Loop** - Toggle loop modes
- 🔄 **Force Resume** - Recovery tool for stuck playback
- ⏹ **Stop** - End playback and clear queue

## Live Update System

### How It Works
1. **Message Sent**: When you play a song, the live UI card is sent
2. **Background Loop**: A background task starts updating the message every 2-3 seconds
3. **Live Updates**: Progress bar, time, and queue position update in real-time
4. **Automatic Cleanup**: Updates stop when the track ends
5. **Flood Protection**: Respects Telegram rate limits; skips identical updates

### Why Live Updates?
- See real-time progress without refreshing
- Permission checks happen on every update (admins gain/lose buttons)
- Source changes are reflected instantly
- Queue position updates as songs are added/removed
- No message spam - only edits, no new messages

## Soul King Theme Elements

### Visual Design
```
╔════════════════════════════════════╗
║  ▶️ 🎵 LIVE PERFORMANCE 🎵        ║
╚════════════════════════════════════╝

🎸 **The Soul King is ON STAGE!** YOHOHOHO! 🎵

─ 🎸 NOW ON STAGE 🎸 ─
[Song Title]
by [Artist Name]
🟦 VK Music

─ CONCERT PROGRESS ─
[████████████░░] 50%
1:30 ▶ 3:00

─ STAGE INFO ─
🎵 Queue: 5 songs • Position: #2
```

### Quote Rotation
The interface cycles through themed quotes for different states:

**Playing:**
- "🎸 **The Soul King is ON STAGE!** YOHOHOHO! 🎵"
- "🎼 **Violin strings SINGING!** Feel the music flow! 💀"
- "🎭 **LIVE CONCERT** — Let this melody be eternal! ✨"

**Paused:**
- "⏸ **Intermission!** The Soul King takes a breath... 💀"
- "🎭 **Stage goes dark...** Waiting for the encore! 🌙"

**Idle:**
- "🎭 **The stage awaits a performer...** Use /play to summon the Soul King! 🎸"

## Advanced Features

### Queue Display
The `/queue` command shows:
- Current track with progress
- Next 20 upcoming tracks with durations
- Total queue duration
- Inline controls to shuffle or clear

### Status Check
Tap the 📊 **Stats** button to see:
- Current playback status
- Active voice chats
- Admin status of bot and users
- Multi-bot load balancing info
- Globally banned and sudo user counts

### Force Resume
If playback gets stuck:
1. Tap **🔄 Force Resume** button
2. Bot cleanly stops current stream
3. Clears stuck state
4. Restarts the queue from the next track

### Loop Modes
Cycle through three modes with the **🔁 Loop** button:
1. **❌ Loop OFF** - Play once and move to next
2. **🔂 Looping Track** - Repeat current song endlessly
3. **🔁 Looping Queue** - Repeat entire queue

## Performance & Reliability

### Update Efficiency
- Skips identical updates (MessageNotModified)
- Dynamically adjusts update frequency based on song length
- Handles Telegram rate limits gracefully (FloodWait backoff)
- Session cleanup prevents memory leaks

### Failover Behavior
- If live updates fail, UI remains functional
- Manual button clicks work even during update failure
- Auto-fallback to text-only cards if thumbnail generation fails
- Graceful degradation for low-bandwidth connections

## Customization

### Colors (Soul King Palette)
Edit `bot/utils/live_ui.py` to customize:
- **bg_dark**: `(15, 15, 35)` - Dark blue background
- **accent_gold**: `(255, 215, 0)` - Gold highlights
- **accent_purple**: `(138, 43, 226)` - Purple accents
- **text_main**: `(255, 255, 255)` - Main text (white)
- **bar_filled**: `(255, 215, 0)` - Progress bar gold

### Update Interval
In `SoulKingLiveUI.__init__()`:
```python
self.update_interval = 2.5  # seconds (adjust as needed)
```

### Quote Pool
Add more quotes to `SOUL_KING_VIBES` in `live_ui.py`:
```python
SOUL_KING_VIBES = {
    "playing": [
        "🎸 Your custom quote here! 💀",
        # ...
    ],
    # ...
}
```

## Troubleshooting

### Live Updates Not Working
1. Check that the bot has permission to edit messages
2. Ensure the message isn't in read-only mode
3. Verify the chat allows message edits

### Missing Thumbnails
- Ensure artwork URLs are accessible
- Check your firewall/proxy settings
- Thumbnails are optional; the text UI works without them

### Button Permissions Not Updating
- Live updates should reflect your current role
- If stuck, use `/status` to refresh
- Manually refreshing the GUI may be needed in some clients

### "Force Resume" Not Working
- Ensure there are songs in the queue
- Check that you're an admin
- Try `/stop` followed by `/play` if issues persist

## Implementation Details

### Files Modified
- **bot/utils/live_ui.py** - Core live UI system
- **bot/utils/soul_king_thumbnail.py** - Concert-style thumbnail generation
- **bot/plugins/play.py** - Integration with play commands
- **bot/plugins/callbacks.py** - Enhanced button handlers

### Architecture
```
┌─ Live UI System ─────────────────────┐
│                                       │
│  ┌─ SoulKingLiveUI ───────────────┐ │
│  │ • Format display text          │ │
│  │ • Create inline controls       │ │
│  │ • Background update loop       │ │
│  │ • Session management           │ │
│  └────────────────────────────────┘ │
│                                       │
│  ┌─ Thumbnail Generator ──────────┐ │
│  │ • Download song artwork        │ │
│  │ • Generate styled cards        │ │
│  │ • Add progress/metadata        │ │
│  └────────────────────────────────┘ │
│                                       │
│  ┌─ Play Command ─────────────────┐ │
│  │ • Send live card on /play      │ │
│  │ • Start update session         │ │
│  │ • Handle track changes         │ │
│  └────────────────────────────────┘ │
│                                       │
└───────────────────────────────────────┘
```

## Performance Notes

- **Live Updates**: ~2.5 seconds per update (configurable)
- **Memory**: Each active chat session uses ~1KB for state tracking
- **Network**: ~1 API call per 2-3 seconds per active chat
- **CPU**: Minimal impact; mostly async operations

## Future Enhancements

Potential additions:
- [ ] Now playing animation effects
- [ ] Seek position slider in keyboard
- [ ] Inline search integration
- [ ] User reaction badges (👍 👎)
- [ ] Voting/skip threshold system
- [ ] Song history replay
- [ ] Cross-group relay display

---

**Version**: 2.0+  
**Theme**: Brook (One Piece Soul King)  
**Last Updated**: 2026-04-15  
**YOHOHOHO!** 🎸💀🎵
