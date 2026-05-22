# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running locally

```bash
./start.sh           # starts on port 8000
./start.sh 8080      # custom port
```

Endpoints once running:
- Customer app: `http://localhost:8000/`
- Admin panel: `http://localhost:8000/admin/`
- API docs: `http://localhost:8000/docs`

## Architecture

Single-file FastAPI backend (`main.py`) that serves both the API and static frontends. No separate build step.

**Backend** — `main.py`
- FastAPI + SQLite (via stdlib `sqlite3`), no ORM
- `init_db()` runs on startup: creates tables, seeds menu, and applies inline column migrations via `ALTER TABLE ... ADD COLUMN` wrapped in try/except
- Admin routes all require `x-admin-secret` header (or `?x_admin_secret=` query param), verified by `verify_admin` dependency
- Telegram bot notifications sent via HTTP to `api.telegram.org` — `BOT_TOKEN` and `ADMIN_USER_IDS` (comma-separated) must be set
- `APP_URL` env var is required for the Telegram webhook and the `/admin` Mini App button to work

**Frontends** — `frontend/customer/index.html` and `frontend/admin/index.html`
- Single-file SPAs with no build tooling — plain HTML/CSS/JS
- Mounted as FastAPI `StaticFiles` at `/` and `/admin` respectively

**Database**
- `DB_PATH` env var controls where `cafe.db` is stored (default: project root; production: `/data/cafe.db` for Railway persistent volume)
- Prices stored in UZS; `normalize_uzs_amount()` converts old USD seed values (< 1000) to UZS on read
- Order soft-delete: `status='deleted'` + `deleted_at` column; hard deletes are not used

## Environment variables

| Variable | Purpose |
|---|---|
| `BOT_TOKEN` | Telegram bot token |
| `ADMIN_USER_IDS` | Comma-separated Telegram user IDs for admin notifications |
| `ADMIN_SECRET` | Password for admin API endpoints |
| `APP_URL` | Public HTTPS URL (e.g. Railway URL) — needed for webhook registration |
| `DB_PATH` | SQLite file path (default: `cafe.db`) |

## Deployment

Deployed on Railway via `railway.json`. The start command is `python -m uvicorn main:app --host 0.0.0.0 --port $PORT`. Railway's persistent volume should be mounted at `/data` so `DB_PATH=/data/cafe.db` survives redeploys.

After deploying, register the Telegram webhook:
```
GET /telegram/set-webhook  (requires x-admin-secret header)
```
