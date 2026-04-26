# YouTube Cookie Setup - BYPASS BOT DETECTION

This guide will help you set up YouTube cookies to bypass bot detection and play ALL music including Indian songs.

## Why Cookies?

YouTube blocks Heroku IPs with "Sign in to confirm you're not a bot" errors. With cookies from a logged-in account, yt-dlp can bypass this.

## Quick Setup (5 minutes)

### Step 1: Export Cookies from Chrome/Edge

1. **Install the cookie export extension:**
   - Go to: https://chrome.google.com/webstore/detail/get-cookiestxt-locally/cclelndahbllghknikmfpibnjhjpjgko
   - Click "Add to Chrome"

2. **Go to YouTube and log in:**
   - Open https://www.youtube.com
   - Sign in with your Google account (any account works)
   - Watch a video for 30 seconds to establish session

3. **Export cookies:**
   - Click the extension icon (🍪) in Chrome toolbar
   - Click "Export" 
   - Select "Export as Netscape format"
   - Save the file as `cookies.txt`
   - **IMPORTANT:** The file should look like this:
     ```
     # Netscape HTTP Cookie File
     .youtube.com	TRUE	/	TRUE	...
     ```

### Step 2: Add Cookies to Render

**Option A: Environment Variable (Recommended)**

1. Go to Render Dashboard: https://dashboard.render.com
2. Click your YouTube wrapper service
3. Go to "Environment" tab
4. Click "Add Environment Variable"
5. **Key:** `YOUTUBE_COOKIES`
6. **Value:** Copy-paste the ENTIRE contents of `cookies.txt` file
7. Click "Save"
8. Your service will auto-redeploy

**Option B: File Upload**

1. In your `youtube-wrapper` folder, place the `cookies.txt` file
2. Push to GitHub:
   ```bash
   cd "d:\Music bot\youtube-wrapper"
   git add cookies.txt
   git commit -m "Add YouTube cookies"
   git push origin main
   ```

### Step 3: Verify It Works

1. Wait for Render to deploy (2-3 minutes)
2. Check the logs show: `[INIT] Cookies file found`
3. Test in Telegram:
   ```
   /play tum hi ho
   ```

## Troubleshooting

### "Cookies file NOT found"
- If using env variable: Check `YOUTUBE_COOKIES` is set correctly
- If using file: Make sure `cookies.txt` is in the `youtube-wrapper` folder

### "Sign in to confirm you're not a bot" still happens
- Cookies expired (last ~1-2 weeks)
- Re-export fresh cookies from YouTube
- Update the env variable

### Cookie Format Issues
The file MUST start with:
```
# Netscape HTTP Cookie File
```

If it starts with `{` (JSON), you exported wrong format. Use "Netscape" format.

## Important Notes

1. **Privacy:** Cookies contain session tokens - don't share publicly
2. **Expiry:** Cookies expire after ~1-2 weeks of inactivity
3. **Re-export:** You'll need to redo this process periodically
4. **Account:** Any Google account works - doesn't need YouTube Premium

## Alternative: Skip YouTube for Now

If this is too complex, you can:
1. Use `/play` with direct MP3 links
2. Use Deezer/VK sources (already working)
3. Wait for a simpler solution

But with cookies, YouTube works perfectly for ALL music! 🎵
