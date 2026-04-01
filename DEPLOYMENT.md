# Telegram Music Bot - Zero-Cost Deployment Guide

This guide shows how to deploy the music bot completely free using various cloud platforms.

## Architecture for Zero-Cost Deployment

```
┌─────────────────┐      ┌─────────────────┐      ┌─────────────────┐
│   Telegram API  │◄────►│   Bot Service   │◄────►│   SQLite Cache  │
│                 │      │   (Python)      │      │   (Local File)  │
└─────────────────┘      └─────────────────┘      └─────────────────┘
                                │
                                ▼
                         ┌─────────────────┐
                         │   SQLite/JSON   │
                         │   Data Store    │
                         │ (YT Music / AM) │
                         └─────────────────┘
```

**Changes for zero-cost:**
- **Removed**: Redis dependency (replaced with SQLite)
- **Removed**: MongoDB requirement (can use SQLite, but MongoDB Atlas free tier still recommended)
- **Fallback**: All cache operations use SQLite if Redis not configured
- **Storage**: Local filesystem for SQLite database

## Free Deployment Options

### 1. Railway.app (Recommended - $5/month free credit)

**Pros:**
- No sleep/idle timeout
- Persistent storage
- Easy deployment from GitHub

**Steps:**
1. Fork this repository to your GitHub
2. Sign up at [railway.app](https://railway.app) with GitHub
3. Click "New Project" → "Deploy from GitHub repo"
4. Select your forked repo
5. Add environment variables in Railway dashboard:
   ```
   API_ID=your_api_id
   API_HASH=your_api_hash
   BOT_TOKEN=your_bot_token
   SESSION_FILE_B64_1=your_base64_encoded_session_file
   # or SESSION_FILE_PATH_1=/app/sessions/userbot_1.session
   # or SESSION_STRING_1=your_session_string
   OWNER_ID=your_user_id
   MONGO_URI=mongodb+srv://... (optional - uses SQLite if not set)
   ```
6. Deploy!

### 2. Render.com (Free Tier)

**Pros:**
- Simple deployment
- Good for testing

**Cons:**
- 15-minute idle timeout (bot will sleep after inactivity)
- Spin-up delay after idle

**Steps:**
1. Fork repo to GitHub
2. Sign up at [render.com](https://render.com)
3. Click "New Web Service"
4. Connect your GitHub repo
5. Use existing `render.yaml` (Blueprint)
6. Set environment variables
7. Deploy

**Note:** For Render free tier, consider using a ping service (like UptimeRobot) to keep the bot awake.

### 3. Fly.io (Free Tier)

**Pros:**
- Generous free tier
- 3 shared-cpu-1 256MB VMs always free
- Good performance

**Steps:**
```bash
# Install flyctl
powershell -Command "iwr https://fly.io/install.ps1 -useb | iex"

# Login
flyctl auth login

# Launch app
flyctl launch

# Set secrets
flyctl secrets set API_ID=your_api_id
flyctl secrets set API_HASH=your_api_hash
flyctl secrets set BOT_TOKEN=your_bot_token
flyctl secrets set SESSION_FILE_B64_1=your_base64_encoded_session_file
flyctl secrets set OWNER_ID=your_user_id

# Deploy
flyctl deploy
```

**Create a volume for persistent data:**
```bash
flyctl volumes create data --size 1 --region sin
```

### 4. Oracle Cloud Free Tier (Always Free)

**Pros:**
- Truly always free (never expires)
- 2 AMD-based Compute VMs (1/8 OCPU, 1GB RAM each)
- 1 ARM-based Ampere A1 Compute VM (4 OCPUs, 24GB RAM)
- Good for 24/7 operation

**Steps:**
1. Sign up at [oracle.com/cloud/free](https://www.oracle.com/cloud/free/)
2. Create a VM instance (Ubuntu 22.04)
3. SSH into the instance
4. Install Docker:
   ```bash
   sudo apt update
   sudo apt install docker.io docker-compose
   ```
5. Clone repo and deploy:
   ```bash
   git clone <your-repo>
   cd musicbot
   # Edit .env file
   sudo docker-compose up -d
   ```

### 5. Self-Hosting (Raspberry Pi / Home Server)

**Pros:**
- Complete control
- No usage limits
- Learn self-hosting

**Steps:**
```bash
# On Raspberry Pi or any Linux machine
git clone <repo>
cd musicbot

# Install dependencies
pip3 install -r requirements.txt

# Create .env file
cp .env.example .env
nano .env  # Edit with your values

# Run directly (no Docker needed)
python3 -m bot
```

## Database Options

### Option 1: SQLite (Zero-config, Zero-cost)
Just don't set `MONGO_URI` - the bot will use SQLite automatically.

**Pros:**
- No external service needed
- File-based, zero cost
- Works everywhere

**Cons:**
- Not ideal for high concurrency
- Single-writer limitations

### Option 2: MongoDB Atlas Free Tier (Recommended)
Sign up at [mongodb.com/atlas](https://www.mongodb.com/atlas) - M0 cluster is free forever (512MB storage).

```
MONGO_URI=mongodb+srv://username:password@cluster.mongodb.net/musicbot
```

## Required Environment Variables

| Variable | Description | How to Get |
|----------|-------------|------------|
| `API_ID` | Telegram API ID | https://my.telegram.org |
| `API_HASH` | Telegram API Hash | https://my.telegram.org |
| `BOT_TOKEN` | Bot token | @BotFather on Telegram |
| `SESSION_FILE_B64_1` | Userbot session file (preferred) | Run `python generate_session.py` |
| `SESSION_FILE_PATH_1` | Mounted `.session` file path | e.g. `/app/sessions/userbot_1.session` |
| `SESSION_STRING_1` | Userbot session string (legacy) | Run `python generate_session.py` |
| `OWNER_ID` | Your Telegram user ID | @userinfobot on Telegram |
| `MONGO_URI` | MongoDB URL (optional) | MongoDB Atlas or omit for SQLite |

## Getting Userbot Session

To generate a production-ready userbot session file + base64 value:

```bash
python generate_session.py
```

Use the output `SESSION_FILE_B64_1=...` in cloud environment variables.

## Troubleshooting

### Bot doesn't respond
- Check logs: `docker logs musicbot` or platform-specific logs
- Verify BOT_TOKEN is correct
- Ensure bot is added to group and has admin rights

### No audio in voice chat
- Check userbot session is valid
- Ensure userbot is admin with "Manage Voice Chats" permission
- **JioSaavn / CDNs**: The bot uses `-user_agent` and `-referer` flags to bypass 403 Forbidden errors. Ensure your server's IP is not rate-limited.
- Check FFmpeg is installed: `ffmpeg -version`

### SQLite locked errors
- This happens with high concurrency
- Consider using MongoDB Atlas free tier instead
- Or reduce worker threads

### Platform-specific issues

**Railway:**
- Check deployment logs in dashboard
- Ensure all env vars are set

**Render:**
- Free tier sleeps after 15 min - use UptimeRobot to ping
- Check "Events" tab for startup errors

**Fly.io:**
- Check `flyctl logs`
- Ensure volume is created and mounted

**Oracle Cloud:**
- Open ports in security list (TCP 80, 443 if using webhooks)
- Check instance is running

## Cost Comparison

| Platform | Cost | Limitations |
|----------|------|-------------|
| Railway | $5/mo credit | Spins down after idle (use cron job to wake) |
| Render | Free | 15-min idle timeout |
| Fly.io | Free | 3 VMs, 3GB volumes |
| Oracle Cloud | Always Free | Requires credit card verification |
| Self-hosted | Electricity only | Your own hardware |

## Recommendations

1. **For testing:** Use Render.com free tier
2. **For production (small scale):** Railway.app with $5 credit
3. **For production (24/7):** Oracle Cloud Free Tier or Fly.io
4. **For learning:** Self-host on Raspberry Pi

## Support

For issues specific to this zero-cost setup:
1. Check the platform's documentation
2. Review bot logs
3. Open an issue on GitHub

**Note:** Free tiers may have limitations. If you need 24/7 reliable operation with high concurrent usage, consider upgrading to paid tiers or using Oracle Cloud Always Free tier.
