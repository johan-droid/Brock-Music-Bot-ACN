# Music Bot System - Complete Troubleshooting & Debugging Guide

## 📋 Overview

This guide provides comprehensive troubleshooting steps for the complete music bot system including wrappers, core bot, and deployment issues.

## 🔍 Diagnostic Tools

### Bot Status Commands
```bash
# Check bot health
/ping

# Check bot info
/info

# Check queue status
/queue

# Check bot stats (admin)
/stats
```

### Health Check Endpoints
```bash
# YouTube Wrapper
curl https://youtube-music-wrapper.onrender.com/

# JioSaavn Wrapper
curl https://jio-savan-music-wrapper.onrender.com/

# Bot Health (if implemented)
curl https://your-bot-domain.com/health
```

### Log Monitoring
```bash
# Heroku logs
heroku logs --tail

# Render logs (via dashboard)
# Go to: https://dashboard.render.com → Service → Logs

# Local logs
tail -f bot.log
```

## 🚨 Common Issues & Solutions

### Bot Not Responding

#### Issue: Bot offline or not responding
**Symptoms:**
- `/ping` command no response
- Bot shows as offline in Telegram
- Commands hang without response

**Diagnostics:**
```bash
# 1. Check if bot is running
heroku ps

# 2. Check logs for errors
heroku logs --tail --num 100

# 3. Verify bot token
curl -X POST "https://api.telegram.org/bot<TOKEN>/getMe"
```

**Solutions:**
1. **Restart Bot**
   ```bash
   heroku restart
   ```

2. **Verify Bot Token**
   ```bash
   heroku config:get BOT_TOKEN
   # Test with curl
   curl -X POST "https://api.telegram.org/bot<TOKEN>/getMe"
   ```

3. **Check Webhook**
   ```bash
   # Verify webhook URL
   curl -X POST "https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://yourdomain.com/webhook"
   ```

### Music Search Not Working

#### Issue: Search returns no results or errors
**Symptoms:**
- `/play query` returns "No results found"
- Search commands fail with errors
- Empty search results

**Diagnostics:**
```bash
# Test YouTube wrapper
curl "https://youtube-music-wrapper.onrender.com/search?q=test&limit=3"

# Test JioSaavn wrapper
curl "https://jio-savan-music-wrapper.onrender.com/search?q=test&limit=3"

# Check bot logs for wrapper errors
heroku logs --tail | grep -E "(youtube|jiosaavn|wrapper)"
```

**Solutions:**
1. **Check Wrapper Health**
   ```bash
   # Both should return 200 OK
   curl https://youtube-music-wrapper.onrender.com/
   curl https://jio-savan-music-wrapper.onrender.com/
   ```

2. **Verify Wrapper URLs**
   ```bash
   # Check environment variables
   heroku config:get YOUTUBE_API_BASE_URL
   heroku config:get JIOSAAVN_API_BASE_URL
   ```

3. **Test Direct API Calls**
   ```python
   # Test wrapper APIs directly
   import aiohttp
   
   async def test_wrappers():
       async with aiohttp.ClientSession() as session:
           # Test YouTube
           async with session.get("https://youtube-music-wrapper.onrender.com/search?q=test") as resp:
               print(f"YouTube status: {resp.status}")
           
           # Test JioSaavn
           async with session.get("https://jio-savan-music-wrapper.onrender.com/search?q=test") as resp:
               print(f"JioSaavn status: {resp.status}")
   ```

### Playback Not Working

#### Issue: Tracks found but won't play in voice chat
**Symptoms:**
- Track added to queue but no audio
- "Track has no URL and resolution failed" error
- Bot joins VC but immediately leaves

**Diagnostics:**
```bash
# Check for stream extraction errors
heroku logs --tail | grep -E "(extract|resolution|stream_url)"

# Check for FFprobe errors
heroku logs --tail | grep -E "(FFprobe|validation|failed)"

# Check voice chat errors
heroku logs --tail | grep -E "(voice|call|py-tgcalls)"
```

**Solutions:**
1. **Check YouTube Cookies**
   ```bash
   # Verify cookies are set
   curl "https://youtube-music-wrapper.onrender.com/track/dQw4w9WgXcQ"
   
   # If 403 error, cookies need refresh
   # Follow: youtube-wrapper/COOKIES_SETUP.md
   ```

2. **Check JioSaavn Decryption**
   ```bash
   # Test JioSaavn track extraction
   curl "https://jio-savan-music-wrapper.onrender.com/track/<id>"
   
   # If only preview URLs, decryption failing
   # Check wrapper logs for decryption errors
   ```

3. **Verify Voice Chat Permissions**
   ```bash
   # Bot must be admin in Telegram group
   # Check bot permissions in group settings
   ```

### YouTube Wrapper Issues

#### Issue: "Sign in to confirm you're not a bot"
**Symptoms:**
- HTTP 403 errors from YouTube wrapper
- Bot detection for Indian music videos
- Cookies not working

**Diagnostics:**
```bash
# Test specific video
curl "https://youtube-music-wrapper.onrender.com/track/Umqb9KENgmk"

# Check wrapper logs
# Go to Render dashboard → YouTube wrapper → Logs
# Look for: "[INIT] Cookies file found/NOT found"
```

**Solutions:**
1. **Refresh YouTube Cookies**
   ```bash
   # 1. Export fresh cookies from Chrome
   # 2. Go to youtube.com and watch a video for 2+ minutes
   # 3. Use browser extension to export cookies
   # 4. Copy Netscape format content
   
   # 5. Update environment variable
   # Render: YouTube wrapper → Environment → Edit YOUTUBE_COOKIES
   # 6. Wait for auto-redeploy (2 minutes)
   ```

2. **Verify Cookie Format**
   ```
   # Must start with:
   # Netscape HTTP Cookie File
   
   # Must contain:
   .youtube.com	TRUE	/	TRUE	1735689600	SAPISID	<value>
   .youtube.com	TRUE	/	TRUE	1735689600	__Secure-3PSID	<value>
   ```

3. **Test with Different Video**
   ```bash
   # Try with known working video
   curl "https://youtube-music-wrapper.onrender.com/track/dQw4w9WgXcQ"
   # Rick Astley should work with valid cookies
   ```

### JioSaavn Wrapper Issues

#### Issue: Only preview URLs (30-second clips)
**Symptoms:**
- All tracks return `jiotunepreview.jio.com` URLs
- Full songs not available
- Decryption fails

**Diagnostics:**
```bash
# Test track extraction
curl "https://jio-savan-music-wrapper.onrender.com/track/<id>"

# Check wrapper logs for decryption
# Look for: "[DECRYPT] Decryption result: FAILED"
```

**Solutions:**
1. **Accept Preview Limitation**
   - Current JioSaavn API returns preview URLs
   - 30-second clips are geo-restricted
   - Bot will fallback to other sources automatically

2. **Try Alternative Sources**
   - YouTube (with fresh cookies)
   - Deezer (direct API)
   - VK (if available)

3. **Monitor for API Changes**
   - JioSaavn may change API
   - Check for new endpoints or authentication

### Voice Chat Issues

#### Issue: Bot joins VC but no audio or leaves immediately
**Symptoms:**
- Bot joins voice chat successfully
- No audio playback
- Bot leaves VC after a few seconds

**Diagnostics:**
```bash
# Check for voice chat errors
heroku logs --tail | grep -E "(voice|call|join|leave)"

# Check for FFmpeg errors
heroku logs --tail | grep -E "(ffmpeg|stream|validation)"

# Check for py-tgcalls errors
heroku logs --tail | grep -E "(py-tgcalls|MediaStream)"
```

**Solutions:**
1. **Check Bot Permissions**
   ```bash
   # Bot must be admin in group
   # Must have permission to:
   # - Send messages
   # - Send audio
   # - Manage voice chat
   ```

2. **Verify Audio Configuration**
   ```python
   # Check audio quality settings
   # Heroku caps at 64kbps by default
   # Too high bitrate may cause failures
   ```

3. **Restart Voice Chat**
   ```bash
   # Stop and restart voice chat
   /stop
   /play <song>
   ```

## 🔧 Advanced Debugging

### Enable Debug Mode
```python
# bot/config.py
DEBUG = True
LOG_LEVEL = "DEBUG"

# Or via environment
export LOG_LEVEL=DEBUG
```

### Debug Logging
```python
# Add to your code
import logging

# Enable detailed logging
logging.getLogger("bot").setLevel(logging.DEBUG)
logging.getLogger("bot.music").setLevel(logging.DEBUG)
logging.getLogger("bot.call").setLevel(logging.DEBUG)
```

### Test Individual Components

#### Test YouTube Wrapper
```javascript
// Test extraction directly
const testVideoId = "dQw4w9WgXcQ";
fetch(`https://youtube-music-wrapper.onrender.com/track/${testVideoId}`)
  .then(res => res.json())
  .then(data => console.log(data));
```

#### Test JioSaavn Wrapper
```javascript
// Test search and extraction
const testQuery = "tum hi ho";
fetch(`https://jio-savan-music-wrapper.onrender.com/search?q=${testQuery}`)
  .then(res => res.json())
  .then(data => console.log(data));
```

#### Test Bot Core
```python
# Test music backend directly
import asyncio
from bot.core.music_backend import MusicBackend

async def test_backend():
    backend = MusicBackend()
    await backend.init()
    
    # Test search
    results = await backend.search("test song", limit=5)
    print(f"Search results: {len(results)} tracks")
    
    # Test extraction
    if results:
        payload = await backend.get_stream_payload(results[0])
        print(f"Stream URL: {payload.get('url') if payload else 'None'}")

asyncio.run(test_backend())
```

## 📊 Performance Issues

### Slow Response Times

#### Issue: Commands take too long to respond
**Symptoms:**
- `/play` takes >10 seconds
- Search results appear slowly
- Bot timeout errors

**Diagnostics:**
```bash
# Measure response times
time curl "https://youtube-music-wrapper.onrender.com/search?q=test"
time curl "https://jio-savan-music-wrapper.onrender.com/search?q=test"

# Check bot logs for timing
heroku logs --tail | grep -E "(seconds|timeout|slow)"
```

**Solutions:**
1. **Enable Caching**
   ```python
   # Add Redis caching
   # Cache search results for 5 minutes
   # Cache stream URLs for 1 hour
   ```

2. **Optimize Database**
   ```sql
   -- Add indexes
   CREATE INDEX idx_queues_chat_id ON queues(chat_id);
   CREATE INDEX idx_track_history_chat_id ON track_history(chat_id);
   ```

3. **Reduce Concurrent Requests**
   ```python
   # Limit parallel requests
   # Add rate limiting
   # Use connection pooling
   ```

### Memory Issues

#### Issue: Bot crashes or restarts frequently
**Symptoms:**
- Heroku "Memory quota exceeded" errors
- Bot restarts every few minutes
- OutOfMemoryError in logs

**Diagnostics:**
```bash
# Check memory usage
heroku logs --tail | grep -E "(memory|Memory|OOM)"

# Check dyno size
heroku ps
```

**Solutions:**
1. **Upgrade Dyno**
   ```bash
   # Upgrade to Standard-1x or higher
   heroku dyno:type standard-1x
   ```

2. **Optimize Memory Usage**
   ```python
   # Use generators instead of lists
   # Clear caches regularly
   # Limit queue size
   # Use streaming for large files
   ```

3. **Add Memory Monitoring**
   ```python
   import psutil
   
   def log_memory_usage():
       memory = psutil.virtual_memory()
       print(f"Memory usage: {memory.percent}%")
   ```

## 🌐 Network Issues

### SSL/TLS Problems

#### Issue: Certificate errors or HTTPS issues
**Symptoms:**
- SSL handshake failed
- Certificate verification errors
- HTTPS connection refused

**Diagnostics:**
```bash
# Test SSL certificate
openssl s_client -connect yourdomain.com:443 -servername yourdomain.com

# Test HTTPS connection
curl -vI https://yourdomain.com

# Check certificate expiry
curl -I https://yourdomain.com 2>&1 | grep -E "(expire|valid)"
```

**Solutions:**
1. **Renew SSL Certificate**
   ```bash
   # Cloudflare: SSL/TLS → Encrypt mode → Full
   # Let's Encrypt: certbot --renew
   # Self-signed: regenerate certificates
   ```

2. **Fix Certificate Chain**
   ```bash
   # Ensure intermediate certificates are included
   # Test with SSL Labs: https://www.ssllabs.com/ssltest/
   ```

### DNS Issues

#### Issue: Domain not resolving or wrong IP
**Symptoms:**
- DNS resolution failed
- Wrong service IP address
- Intermittent connectivity

**Diagnostics:**
```bash
# Test DNS resolution
nslookup yourdomain.com
dig yourdomain.com

# Test wrapper DNS
nslookup youtube-music-wrapper.onrender.com
nslookup jio-savan-music-wrapper.onrender.com
```

**Solutions:**
1. **Check DNS Settings**
   - Verify domain points to correct IP
   - Check TTL settings
   - Ensure no conflicting records

2. **Use CDN DNS**
   - Cloudflare DNS
   - Google DNS (8.8.8.8)
   - OpenDNS (208.67.222.222)

## 🔒 Security Issues

### Bot Token Compromised

#### Issue: Bot behaving unexpectedly or spamming
**Symptoms:**
- Bot sends messages without command
- Bot joins unrelated groups
- Unusual activity patterns

**Diagnostics:**
```bash
# Check bot token usage
curl -X POST "https://api.telegram.org/bot<TOKEN>/getMe"

# Revoke and regenerate if compromised
# BotFather → /revoke → Create new bot
```

**Solutions:**
1. **Regenerate Bot Token**
   ```bash
   # 1. /revoke old bot in BotFather
   # 2. Create new bot with same name
   # 3. Update environment variables
   # 4. Deploy with new token
   ```

2. **Enable Two-Factor Authentication**
   - Secure Telegram account
   - Use strong passwords
   - Enable 2FA on hosting platforms

### API Key Exposure

#### Issue: API keys or tokens exposed
**Symptoms:**
- API keys in public repositories
- Tokens in logs or error messages
- Unauthorized API usage

**Diagnostics:**
```bash
# Check for exposed secrets
grep -r "TOKEN\|KEY\|SECRET" . --exclude-dir=.git

# Scan repository history
git log --all --grep="TOKEN\|KEY\|SECRET" --oneline
```

**Solutions:**
1. **Rotate All Keys**
   ```bash
   # Regenerate all exposed keys
   # Update environment variables
   # Clear any caches
   ```

2. **Clean Repository History**
   ```bash
   # Remove sensitive data from history
   git filter-branch --force --index-filter 'rm --cached --ignore-unmatch <filename>' --prune-empty HEAD
   ```

## 📋 Maintenance Procedures

### Daily Checks
```bash
# 1. Health check all services
curl https://youtube-music-wrapper.onrender.com/
curl https://jio-savan-music-wrapper.onrender.com/

# 2. Check bot status
/ping

# 3. Review error logs
heroku logs --since=24h | grep ERROR

# 4. Monitor performance metrics
/stats
```

### Weekly Maintenance
```bash
# 1. Update dependencies
pip install -r requirements.txt --upgrade
npm update

# 2. Clean old logs
heroku logs --since=168h > /dev/null

# 3. Backup database
heroku pg:backups:capture

# 4. Review and rotate secrets
# Check for exposed keys
# Update tokens if needed
```

### Monthly Maintenance
```bash
# 1. Security audit
# Review bot permissions
# Check for unauthorized access
# Scan for vulnerabilities

# 2. Performance review
# Analyze response times
# Check error rates
# Optimize slow queries

# 3. Update documentation
# Review all guides
# Update with latest changes
# Add new troubleshooting steps
```

## 🚨 Emergency Procedures

### Bot Completely Down
```bash
# 1. Immediate restart
heroku restart

# 2. Check status
heroku ps
heroku logs --tail

# 3. Fallback to manual mode
# Disable automated features
# Enable admin-only commands
```

### Wrapper Service Down
```bash
# 1. Check wrapper status
curl https://youtube-music-wrapper.onrender.com/
curl https://jio-savan-music-wrapper.onrender.com/

# 2. Restart wrapper services
# Render dashboard → Service → Restart

# 3. Deploy fallback
# Switch to alternative wrapper
# Use direct extraction if available
```

### Database Corruption
```bash
# 1. Backup current database
heroku pg:backups:capture

# 2. Restore from backup
heroku pg:backups:restore <backup-id>

# 3. Reinitialize if needed
# Drop and recreate tables
# Restart bot to reinitialize
```

## 📞 Support Resources

### Documentation
- YouTube Wrapper: `youtube-wrapper/TECHNICAL_DOCUMENTATION.md`
- JioSaavn Wrapper: `jiosaavn-wrapper/TECHNICAL_DOCUMENTATION.md`
- Bot Core: `MUSIC_BOT_CORE_TECHNICAL_DOCUMENTATION.md`
- API Reference: `API_ENDPOINTS_DOCUMENTATION.md`
- Deployment: `DEPLOYMENT_GUIDE.md`

### Community Support
- GitHub Issues: Create new issue with detailed logs
- Telegram Support: Contact bot admin for help
- Documentation: Check all guides for relevant sections

### Debug Information Collection
When reporting issues, include:
1. **Full Error Messages**
2. **Command Used**
3. **Expected vs Actual Behavior**
4. **Environment Details**
5. **Recent Changes**
6. **Log Excerpts**

---

*Last Updated: May 8, 2026*
