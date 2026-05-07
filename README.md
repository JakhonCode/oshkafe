# ☕ Cozy Café — Telegram Mini App

A full-stack café ordering system with a **customer Telegram Mini App**, an **admin dashboard**, and a **FastAPI + SQLite backend** that sends Telegram notifications on new orders.

---

## Project Structure

```
cozy-cafe/
├── backend/
│   ├── main.py              # FastAPI app — all API routes
│   ├── requirements.txt     # Python dependencies
│   ├── .env.example         # Environment variable template
│   └── cafe.db              # SQLite DB (auto-created on first run)
├── frontend/
│   ├── customer/
│   │   └── index.html       # Telegram Mini App (customer ordering)
│   └── admin/
│       └── index.html       # Admin dashboard
├── start.sh                 # One-command startup script
└── README.md
```

---

## Quick Start

### 1. Install dependencies

```bash
cd backend
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp backend/.env.example backend/.env
# Edit backend/.env with your values
```

### 3. Start the server

```bash
chmod +x start.sh
./start.sh
# or with a custom port:
./start.sh 8080
```

The server serves everything:
- **Customer app** → `http://localhost:8000/`
- **Admin panel** → `http://localhost:8000/admin/`
- **API docs** → `http://localhost:8000/docs`

---

## Telegram Bot Setup

### Step 1 — Create your bot
1. Open Telegram and message **@BotFather**
2. Send `/newbot` and follow the prompts
3. Copy the **BOT_TOKEN** you receive

### Step 2 — Get your admin chat ID
1. Message **@userinfobot** on Telegram
2. It replies with your numeric user ID
3. Copy it as **ADMIN_USER_IDS**

### Step 3 — Set up the Mini App
1. Message **@BotFather** again
2. Send `/newapp` (or `/mybots` → select your bot → Bot Menu Button)
3. Set the **Web App URL** to your hosted URL (e.g. `https://your-domain.com/`)

### Step 4 — Update .env

```env
BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrSTUvwxYZ
ADMIN_USER_IDS=987654321,123456789
ADMIN_SECRET=your_secure_password_here
APP_URL=https://your-app.up.railway.app
DB_PATH=/data/cafe.db
```

---

## Deployment (Production)

### Deploy to a VPS (e.g. DigitalOcean, Hetzner)

```bash
# Install
git clone <your-repo> && cd cozy-cafe
pip install -r backend/requirements.txt

# Configure
cp backend/.env.example backend/.env
nano backend/.env  # fill in your values

# Run with uvicorn behind nginx
uvicorn main:app --host 127.0.0.1 --port 8000
```

### Nginx config (with HTTPS — required by Telegram)

```nginx
server {
    listen 443 ssl;
    server_name your-domain.com;

    ssl_certificate /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

Get a free SSL cert: `sudo certbot --nginx -d your-domain.com`

### Deploy to Railway / Render (easier)

1. Push code to GitHub
2. Connect repo to Railway or Render
3. Set environment variables in their dashboard
4. Done — they handle HTTPS automatically

---

## API Reference

### Customer Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/menu` | Get all available menu items |
| POST | `/api/orders` | Place a new order |
| GET | `/api/orders/{order_number}/status` | Poll order status |

### Admin Endpoints (require `x-admin-secret` header)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/admin/orders` | List all orders (filter by `?status=`) |
| PATCH | `/api/admin/orders/{id}/status` | Update order status |
| GET | `/api/admin/stats` | Dashboard stats |
| GET | `/api/admin/menu` | List all menu items |
| PATCH | `/api/admin/menu/{id}` | Update price / availability |

---

## Order Status Flow

```
pending → confirmed → preparing → out_for_delivery → delivered
                  ↘ cancelled (from any step)
```

The customer app polls every 5 seconds and updates the progress tracker live.

---

## Admin Dashboard Features

- 📊 **Stats** — total orders, today's count, pending count, total revenue
- 📋 **Order list** — filterable by status, expandable cards with full details
- 🔄 **Status updates** — one-click status progression with Telegram notification history
- 🍽 **Menu management** — toggle item availability, edit prices live

---

## Security Notes

- Change `ADMIN_SECRET` to a strong password before deploying
- The admin dashboard is at `/admin/` — consider IP-restricting it via nginx
- Telegram Mini App receives the user's Telegram ID for future notification features
- In production, set `allow_origins` in CORS to your actual domain

---

## Customising the Menu

Edit the seed data in `backend/main.py` (the `init_db()` function), or use the admin dashboard to toggle items on/off and adjust prices at runtime. Menu changes take effect immediately — no restart needed.
