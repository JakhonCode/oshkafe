# Deployment Checklist

## Before GitHub

Do not commit real secrets or local data. This repo now ignores:

- `.env`
- `cafe.db`
- `*.log`
- `__pycache__/`

Rotate the Telegram bot token before deploying, because the old token was previously stored in code.

## Railway Environment Variables

Set these in Railway:

```env
BOT_TOKEN=your_rotated_telegram_bot_token
ADMIN_USER_IDS=8655939868,123456789
ADMIN_SECRET=your_strong_admin_password
APP_URL=https://your-app.up.railway.app
DB_PATH=/data/cafe.db
```

Use `ADMIN_USER_IDS` for every Telegram user allowed to open the admin panel from the bot. Separate IDs with commas.

## Railway SQLite Persistence

If you keep SQLite, add a Railway Volume and mount it at:

```text
/data
```

Then keep:

```env
DB_PATH=/data/cafe.db
```

Without a volume, Railway can lose `cafe.db` data on redeploys.

## Telegram Bot Setup

After Railway deploys, set the webhook:

```bash
curl "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/setWebhook?url=https://your-app.up.railway.app/telegram/webhook"
```

In BotFather, set the Mini App / Web App URL to:

```text
https://your-app.up.railway.app/
```

Selected admins can message the bot:

```text
/admin
```

Only IDs in `ADMIN_USER_IDS` will receive the admin panel button.
