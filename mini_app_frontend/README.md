# Mini App Frontend

This is a sample Telegram Mini App frontend for the Soul King project.

## What to use as Mini App URL

Do not use the Telegram Web App SDK script URL as the Mini App URL.

The Mini App URL must be a valid HTTPS page that Telegram loads.

Example:

- `https://your-domain.com/mini_app_frontend/index.html`

## How to use

1. Deploy or serve `mini_app_frontend/index.html` over HTTPS.
2. Set your bot's Mini App URL to the deployed page URL.
3. The page loads the Telegram Web App SDK:
   - `<script src="https://telegram.org/js/telegram-web-app.js"></script>`
4. Use `Telegram.WebApp.initData` from the page to authorize backend API calls.

## Notes

- `window.Telegram.WebApp.initData` is only available when the page is opened inside Telegram.
- If Telegram returns `Please send me a valid URL. https is required.`, it means the URL field is wrong.
- The script tag is not a valid Mini App URL.
