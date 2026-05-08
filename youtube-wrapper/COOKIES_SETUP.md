# YouTube Cookies Setup

To bypass YouTube bot detection, you need to export cookies from your browser.

## Step 1: Install Cookie Export Extension

1. Open Chrome/Edge
2. Install "Get cookies.txt LOCALLY" extension:
   https://chrome.google.com/webstore/detail/get-cookiestxt-locally/cclelndahbllghknikmfpibnjbh

## Step 2: Export YouTube Cookies

1. Go to https://www.youtube.com
2. Make sure you're logged in to a Google account
3. Click the extension icon
4. Click "Export" → "Export as JSON"
5. Save the file

## Step 3: Add Cookies to Render

1. Go to Render dashboard → Environment Variables
2. Add:
   ```
   YOUTUBE_COOKIES=<paste the entire JSON here>
   ```

## Alternative: Use Direct yt-dlp with Cookies File

If the above doesn't work, use this simpler approach:

1. Create file `cookies.txt` from YouTube:
   - Use the same extension → "Export as Netscape"
   - Save as `cookies.txt`

2. Add to your repo and push:
   ```bash
   git add cookies.txt
   git commit -m "Add YouTube cookies"
   git push origin main
   ```

3. Update `index.js` to use cookies file

## Note

Cookies expire after a while. You'll need to re-export them periodically.

For Indian music, you might also try:
- Spotify API (requires Spotify Premium)
- JioSaavn API (for Indian music specifically)
- Gaana API (Indian music)
