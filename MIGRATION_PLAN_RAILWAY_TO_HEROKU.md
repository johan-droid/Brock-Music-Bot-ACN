# Migration Plan: Railway to Heroku

This document outlines the steps to migrate the Brook Music Bot from Railway to Heroku.

## Overview

The current deployment uses Railway with a Dockerfile-based build. Heroku supports both buildpack-based deployments and container registry deployments. We'll use the Container Registry approach since the project already has a Dockerfile.

## Current Architecture (Railway)

- **Build Method:** Dockerfile (Python 3.12-slim)
- **Health Check:** Port 8080, `/health` endpoint
- **System Dependencies:** FFmpeg, build-essential, libssl-dev, libffi-dev, python3-dev
- **Database Options:** MongoDB, Redis/Upstash Redis, Supabase
- **Session Storage:** Local filesystem (`/app/sessions/`)

## Target Architecture (Heroku)

- **Build Method:** Heroku Container Registry (Dockerfile)
- **Health Check:** Heroku's health check system
- **System Dependencies:** Same (via Dockerfile)
- **Database Options:** MongoDB Atlas, Heroku Redis, or Heroku Postgres (via Supabase)
- **Session Storage:** **IMPORTANT** - Heroku has ephemeral filesystem, sessions won't persist across restarts

## Pre-Migration Checklist

### 1. Database Selection

Choose one of the following:

**Option A: MongoDB Atlas (Recommended)**
- Free tier available
- Compatible with existing MongoDB code
- Set `MONGO_URI` in Heroku config vars

**Option B: Heroku Redis**
- Free tier available
- Compatible with existing Redis code
- Set `REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD` in Heroku config vars
- **OR** use Upstash Redis with `UPSTASH_REDIS_REST_URL`, `UPSTASH_REDIS_REST_TOKEN`

**Option C: Supabase (PostgreSQL)**
- Free tier available
- Requires running migration script
- Set `SUPABASE_URL`, `SUPABASE_KEY` in Heroku config vars

### 2. Session String Migration

Since Railway and Heroku use different variable naming, ensure you have:
- `SESSION_STRING_1` (required)
- `SESSION_STRING_2-5` (optional, for scaling)

Generate session strings using: `python generate_session.py`

## Environment Variable Mapping

| Railway Variable | Heroku Config Var | Required | Notes |
|------------------|-------------------|----------|-------|
| `API_ID` | `API_ID` | Yes | From my.telegram.org |
| `API_HASH` | `API_HASH` | Yes | From my.telegram.org |
| `BOT_TOKEN` | `BOT_TOKEN` | Yes | From @BotFather |
| `BOT_USERNAME` | `BOT_USERNAME` | No | Optional |
| `OWNER_ID` | `OWNER_ID` | Yes | Your Telegram user ID |
| `SESSION_STRING_1` | `SESSION_STRING_1` | Yes | Generate with generate_session.py |
| `SESSION_STRING_2` | `SESSION_STRING_2` | No | Optional |
| `SESSION_STRING_3` | `SESSION_STRING_3` | No | Optional |
| `SESSION_STRING_4` | `SESSION_STRING_4` | No | Optional |
| `SESSION_STRING_5` | `SESSION_STRING_5` | No | Optional |
| `MONGO_URI` | `MONGO_URI` | Yes* | *Or use Supabase |
| `REDIS_HOST` | `REDIS_HOST` | No* | *Or use Upstash Redis |
| `REDIS_PORT` | `REDIS_PORT` | No* | *Or use Upstash Redis |
| `REDIS_PASSWORD` | `REDIS_PASSWORD` | No* | *Or use Upstash Redis |
| `UPSTASH_REDIS_REST_URL` | `UPSTASH_REDIS_REST_URL` | No* | *Or use regular Redis |
| `UPSTASH_REDIS_REST_TOKEN` | `UPSTASH_REDIS_REST_TOKEN` | No* | *Or use regular Redis |
| `SUPABASE_URL` | `SUPABASE_URL` | Yes* | *Or use MongoDB |
| `SUPABASE_KEY` | `SUPABASE_KEY` | Yes* | *Or use MongoDB |
| `GENIUS_TOKEN` | `GENIUS_TOKEN` | No | Optional |
| `LOG_GROUP_ID` | `LOG_GROUP_ID` | No | Optional |

## Migration Steps

### Step 1: Create Heroku App

```bash
# Install Heroku CLI if not already installed
# Windows: winget install Heroku.HerokuCLI
# Mac: brew tap heroku/brew && brew install heroku
# Linux: snap install heroku --classic

# Login to Heroku
heroku login

# Create a new app
heroku create your-app-name

# Or specify region
heroku create your-app-name --region us
```

### Step 2: Set Up Database

#### Option A: MongoDB Atlas
1. Create account at https://www.mongodb.com/cloud/atlas
2. Create a free cluster
3. Get connection string (replace `<password>` with actual password)
4. Add to Heroku:
```bash
heroku config:set MONGO_URI="mongodb+srv://user:password@cluster.mongodb.net/musicbot?retryWrites=true&w=majority"
```

#### Option B: Heroku Redis
```bash
heroku addons:create heroku-redis:mini
heroku config:get REDIS_URL
# Extract host, port, password from REDIS_URL
heroku config:set REDIS_HOST=host REDIS_PORT=port REDIS_PASSWORD=password
```

#### Option C: Supabase
1. Create account at https://supabase.com
2. Create a new project
3. Get project URL and anon key
4. Run migration script:
```bash
heroku config:set SUPABASE_URL="https://xyz.supabase.co"
heroku config:set SUPABASE_KEY="your-anon-key"
```
5. Run migration (if using Supabase):
```bash
python init_supabase_tables.py
```

### Step 3: Set Environment Variables

```bash
# Telegram API credentials
heroku config:set API_ID=your_api_id
heroku config:set API_HASH=your_api_hash

# Bot token
heroku config:set BOT_TOKEN=your_bot_token
heroku config:set BOT_USERNAME=your_bot_username

# Owner ID
heroku config:set OWNER_ID=your_telegram_user_id

# Session strings
heroku config:set SESSION_STRING_1="your_session_string_1"
heroku config:set SESSION_STRING_2="your_session_string_2"  # optional
heroku config:set SESSION_STRING_3="your_session_string_3"  # optional
heroku config:set SESSION_STRING_4="your_session_string_4"  # optional
heroku config:set SESSION_STRING_5="your_session_string_5"  # optional

# Optional: Genius (for lyrics)
heroku config:set GENIUS_TOKEN=your_genius_token

# Optional: Log group
heroku config:set LOG_GROUP_ID=your_log_group_id
```

### Step 4: Deploy to Heroku Container Registry

```bash
# Login to Heroku Container Registry
heroku container:login

# Build and push the Docker image
heroku container:push web -a your-app-name

# Release the image
heroku container:release web -a your-app-name
```

### Step 5: Verify Deployment

```bash
# View logs
heroku logs --tail -a your-app-name

# Check if bot is running
heroku ps -a your-app-name

# Open the app (if web interface exists)
heroku open -a your-app-name
```

### Step 6: Set Up Health Check (Optional)

Heroku has built-in health checks. The Dockerfile already includes a health check. Heroku will automatically use it.

To customize:
```bash
heroku features:runtime-health-checks:enable -a your-app-name
```

### Step 7: Configure Scaling

```bash
# Scale to 1 dyno (free tier)
heroku ps:scale web=1 -a your-app-name

# For production, consider Standard-1X or higher
heroku ps:scale web=standard-1x -a your-app-name
```

## Important Considerations

### 1. Ephemeral Filesystem

**Problem:** Heroku's filesystem is ephemeral. Files written to disk are lost when the dyno restarts.

**Impact:** 
- Session files in `/app/sessions/` won't persist
- SQLite cache may be lost (but this is acceptable for cache)

**Solution:** 
- The bot already uses session strings (not files), so this is not an issue
- SQLite cache is acceptable to lose on restart

### 2. FFmpeg Requirement

The Dockerfile includes FFmpeg, which is required for audio processing. This is handled by the Dockerfile and will work with Heroku Container Registry.

### 3. Database Migration

If moving from Railway MongoDB to a different database:

**From Railway MongoDB to MongoDB Atlas:**
- Export data from Railway MongoDB
- Import to MongoDB Atlas
- Update `MONGO_URI` in Heroku config

**From Railway MongoDB to Supabase:**
- Run migration script: `python migrate_to_supabase.py`
- Update config to use Supabase

### 4. Redis Migration

If using Upstash Redis on Railway, you can:
- Continue using Upstash Redis (add `UPSTASH_REDIS_REST_URL` and `UPSTASH_REDIS_REST_TOKEN` to Heroku config)
- Or migrate to Heroku Redis (add Heroku Redis addon and set `REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD`)

### 5. Cost Comparison

| Service | Railway | Heroku |
|---------|---------|--------|
| App Runtime | Free tier ($5/mo after trial) | Free tier (Eco dynos) |
| MongoDB | Free tier included | Free tier via Atlas |
| Redis | Free tier included | Free tier via Heroku Redis |
| Supabase | Not available | Free tier available |

**Heroku Free Tier Limitations:**
- Eco dynos sleep after 30 minutes of inactivity
- Cold start on first request (~10-30 seconds)
- 512MB RAM, 1 CPU

**Heroku Paid Tier (Basic/Standard):**
- No sleep
- More RAM/CPU
- Better performance for music bot

## Post-Migration Tasks

### 1. Test the Bot

- Send `/start` to verify bot responds
- Test `/play` command with a song
- Verify voice chat functionality
- Check database operations (queue, settings)

### 2. Monitor Logs

```bash
heroku logs --tail -a your-app-name
```

### 3. Set Up Error Tracking (Optional)

Consider adding Sentry or similar for production error tracking.

### 4. Configure Auto-Restart

Heroku automatically restarts crashed dynos. The Dockerfile includes `restartPolicyType: ALWAYS` which is handled by Heroku.

### 5. Backup Database

Set up regular backups for your chosen database:
- MongoDB Atlas: Enable automated backups
- Supabase: Built-in daily backups
- Heroku Redis: Data is ephemeral (acceptable for cache)

## Rollback Plan

If migration fails:

```bash
# Rollback to previous release
heroku rollback -a your-app-name

# Or redeploy previous Docker image
heroku container:rollback web -a your-app-name
```

To revert to Railway:
- Delete Heroku app: `heroku apps:destroy -a your-app-name`
- Railway deployment remains unchanged

## Troubleshooting

### Bot Won't Start

**Check logs:**
```bash
heroku logs --tail -a your-app-name
```

**Common issues:**
- Missing environment variables
- Incorrect database connection string
- Session string invalid

### Voice Chat Not Working

**Check:**
- `SESSION_STRING_1` is set and valid
- Userbot account is not a bot
- FFmpeg is installed (handled by Dockerfile)

### Database Connection Errors

**Check:**
- Database URL is correct
- Database allows connections from anywhere (0.0.0.0/0)
- Credentials are correct

### Memory Issues

Heroku free tier has 512MB RAM. If you encounter memory errors:
- Upgrade to Standard-1X dyno (512MB-1GB RAM)
- Or optimize the bot (reduce concurrent operations)

## Deployment Commands Summary

```bash
# Initial setup
heroku login
heroku create your-app-name

# Database setup (choose one)
# Option A: MongoDB Atlas
heroku config:set MONGO_URI="mongodb+srv://..."

# Option B: Heroku Redis
heroku addons:create heroku-redis:mini

# Option C: Supabase
heroku config:set SUPABASE_URL="https://..."
heroku config:set SUPABASE_KEY="..."

# Environment variables
heroku config:set API_ID=... API_HASH=... BOT_TOKEN=... OWNER_ID=...
heroku config:set SESSION_STRING_1="..."

# Deploy
heroku container:login
heroku container:push web -a your-app-name
heroku container:release web -a your-app-name

# Monitor
heroku logs --tail -a your-app-name
heroku ps -a your-app-name
```

## Additional Resources

- [Heroku Container Registry](https://devcenter.heroku.com/articles/container-registry-and-runtime)
- [Heroku Redis](https://devcenter.heroku.com/articles/heroku-redis)
- [MongoDB Atlas](https://www.mongodb.com/docs/atlas/getting-started/)
- [Supabase](https://supabase.com/docs)
- [Heroku CLI](https://devcenter.heroku.com/articles/heroku-cli)

## Support

If you encounter issues:
1. Check Heroku logs: `heroku logs --tail -a your-app-name`
2. Verify all environment variables: `heroku config -a your-app-name`
3. Ensure database is accessible
4. Check session string is valid (regenerate if needed)
