from fastapi import FastAPI, HTTPException, Depends, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi import Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from typing import Optional, List
import sqlite3
import httpx
import os
import json
import time
import html
from datetime import datetime
import asyncio
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="Cozy Café API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Config ────────────────────────────────────────────────
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_USER_IDS = {
    admin_id.strip()
    for admin_id in os.getenv("ADMIN_USER_IDS", os.getenv("ADMIN_CHAT_ID", "")).split(",")
    if admin_id.strip()
}
ADMIN_SECRET = os.getenv("ADMIN_SECRET", "")
DB_PATH = os.getenv("DB_PATH", "cafe.db")
DELIVERY_FEE_UZS = 15000
USD_TO_UZS_MENU_RATE = 10000

db_dir = os.path.dirname(DB_PATH)
if db_dir:
    os.makedirs(db_dir, exist_ok=True)

def format_uzs(amount: float) -> str:
    amount = normalize_uzs_amount(float(amount or 0))
    return f"{int(round(amount)):,}".replace(",", " ") + " so'm"

def normalize_uzs_amount(amount: float) -> float:
    return round(amount * USD_TO_UZS_MENU_RATE) if 0 < amount < 1000 else amount

# ─── Database ──────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

def open_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_number TEXT UNIQUE NOT NULL,
            customer_name TEXT NOT NULL,
            customer_phone TEXT NOT NULL,
            delivery_address TEXT NOT NULL,
            delivery_city TEXT NOT NULL,
            delivery_zip TEXT,
            delivery_notes TEXT,
            items TEXT NOT NULL,
            subtotal REAL NOT NULL,
            delivery_fee REAL NOT NULL DEFAULT 15000,
            total REAL NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            telegram_user_id TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS menu_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            emoji TEXT NOT NULL,
            name TEXT NOT NULL,
            description TEXT,
            price REAL NOT NULL,
            badge TEXT,
            available INTEGER NOT NULL DEFAULT 1
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS menu_categories (
            key TEXT PRIMARY KEY,
            label_uz TEXT NOT NULL,
            label_ru TEXT,
            sort_order INTEGER NOT NULL DEFAULT 100,
            active INTEGER NOT NULL DEFAULT 1
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS telegram_contacts (
            telegram_user_id TEXT PRIMARY KEY,
            phone_number TEXT NOT NULL,
            first_name TEXT,
            last_name TEXT,
            updated_at TEXT NOT NULL
        )
    """)
    default_categories = [
        ("food", "Taomlar", "Еда", 10),
        ("salads", "Salatlar", "Салаты", 20),
        ("drinks", "Ichimliklar", "Напитки", 30),
        ("desserts", "Shirinliklar", "Десерты", 1000),
    ]
    c.executemany(
        "INSERT OR IGNORE INTO menu_categories (key,label_uz,label_ru,sort_order,active) VALUES (?,?,?,?,1)",
        default_categories
    )
    for key, label_uz, label_ru, sort_order in default_categories:
        c.execute(
            "UPDATE menu_categories SET label_uz=?, label_ru=?, sort_order=?, active=1 WHERE key=?",
            (label_uz, label_ru, sort_order, key)
        )
    # Seed menu if empty
    c.execute("SELECT COUNT(*) FROM menu_items")
    if c.fetchone()[0] == 0:
        items = [
            ('coffee','☕','Espresso','Double shot, rich & bold',3.50,'hot',1),
            ('coffee','🥛','Flat White','Smooth velvety microfoam',4.20,None,1),
            ('coffee','🧊','Iced Latte','Cold brew with oat milk',4.80,'new',1),
            ('coffee','🍫','Mocha','Espresso with chocolate',4.90,None,1),
            ('coffee','🌿','Matcha Latte','Ceremonial grade matcha',5.20,'new',1),
            ('drinks','🍊','Fresh OJ','Squeezed to order',3.80,None,1),
            ('drinks','🌸','Rose Lemonade','Sparkling with rose syrup',3.60,None,1),
            ('drinks','🍵','Chamomile Tea','Soothing herbal blend',2.80,None,1),
            ('food','🥐','Butter Croissant','Flaky, baked fresh daily',3.20,'hot',1),
            ('food','🥪','Avocado Toast','Sourdough, feta & seeds',7.50,None,1),
            ('food','🥗','Caesar Salad','Grilled chicken, parmesan',9.90,None,1),
            ('food','🥚','Eggs Benedict','Poached on brioche',10.50,None,1),
            ('desserts','🍰','Cheesecake Slice','New York style, berry coulis',5.80,'new',1),
            ('desserts','🍮','Crème Brûlée','Vanilla bean, torched sugar',6.20,None,1),
            ('desserts','🍪','Cookie Pack','3 assorted cookies',3.50,None,1),
            ('desserts','🍫','Brownie','Warm fudge, walnut',4.20,'hot',1),
        ]
        c.executemany(
            "INSERT INTO menu_items (category,emoji,name,description,price,badge,available) VALUES (?,?,?,?,?,?,?)",
            items
        )
    # Migrate: add columns if not present
    for col in ['lat REAL', 'lon REAL']:
        try:
            c.execute(f"ALTER TABLE orders ADD COLUMN {col}")
        except Exception:
            pass
    try:
        c.execute("ALTER TABLE orders ADD COLUMN deleted_at TEXT")
    except Exception:
        pass
    try:
        c.execute("ALTER TABLE menu_items ADD COLUMN photo TEXT")
    except Exception:
        pass
    c.execute(
        "UPDATE menu_items SET price = ROUND(price * ?) WHERE price > 0 AND price < 1000",
        (USD_TO_UZS_MENU_RATE,)
    )
    c.execute(
        "UPDATE orders SET subtotal = ROUND(subtotal * ?), delivery_fee = ?, total = ROUND((total - delivery_fee) * ?) + ? "
        "WHERE total > 0 AND total < 1000",
        (USD_TO_UZS_MENU_RATE, DELIVERY_FEE_UZS, USD_TO_UZS_MENU_RATE, DELIVERY_FEE_UZS)
    )
    c.execute("UPDATE menu_items SET category='drinks' WHERE category='coffee'")
    c.execute("UPDATE menu_items SET category='salads' WHERE LOWER(name) LIKE '%salad%'")
    conn.commit()
    conn.close()

init_db()

# ─── Models ────────────────────────────────────────────────
class OrderItem(BaseModel):
    id: int
    name: str
    emoji: str
    price: float
    qty: int

class PlaceOrderRequest(BaseModel):
    customer_name: str
    customer_phone: str
    delivery_address: str
    delivery_city: str
    delivery_zip: Optional[str] = ""
    delivery_notes: Optional[str] = ""
    items: List[OrderItem]
    telegram_user_id: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None

class UpdateOrderStatus(BaseModel):
    status: str

class UpdateMenuItem(BaseModel):
    price: Optional[float] = None
    available: Optional[int] = None
    badge: Optional[str] = None
    photo: Optional[str] = None

class AddMenuItem(BaseModel):
    category: str
    emoji: str
    name: str
    description: Optional[str] = ""
    price: float
    badge: Optional[str] = None
    photo: Optional[str] = None

class AddCategory(BaseModel):
    label_uz: str
    label_ru: Optional[str] = None

# ─── Auth helper ───────────────────────────────────────────
def verify_admin(
    x_admin_secret: Optional[str] = Header(None),
    x_admin_secret_query: Optional[str] = Query(None, alias="x_admin_secret")
):
    if not ADMIN_SECRET:
        raise HTTPException(status_code=503, detail="ADMIN_SECRET is not configured")
    if (x_admin_secret or x_admin_secret_query) != ADMIN_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return True

def make_category_key(label: str) -> str:
    key = "".join(ch.lower() if ch.isalnum() else "-" for ch in label.strip())
    key = "-".join(part for part in key.split("-") if part)
    return key or f"category-{int(time.time())}"

# ─── Telegram notification ─────────────────────────────────
async def send_telegram_notification(order: dict, items: list):
    # Uzbek Telegram notification. Keep this block before the legacy text below.
    if not BOT_TOKEN or not ADMIN_USER_IDS:
        print("Telegram notification skipped: BOT_TOKEN or ADMIN_USER_IDS is not configured")
        return

    normalized_items = []
    for item in items:
        normalized = dict(item)
        normalized["price"] = normalize_uzs_amount(normalized.get("price", 0))
        normalized_items.append(normalized)

    subtotal = sum(i["price"] * i["qty"] for i in normalized_items)
    delivery_fee = DELIVERY_FEE_UZS
    total = subtotal + delivery_fee
    items_text = "\n".join(
        [f"  {i['emoji']} {i['name']} x{i['qty']} - {format_uzs(i['price'] * i['qty'])}" for i in normalized_items]
    )
    map_line = (
        f"\nXarita: https://maps.google.com/?q={order['lat']},{order['lon']}"
        if order.get("lat") and order.get("lon") else ""
    )
    notes_line = f"Qo'shimcha izoh: {order['delivery_notes']}\n" if order.get("delivery_notes") else ""
    text = (
        f"Yangi buyurtma {order['order_number']}\n\n"
        f"Mijoz: {order['customer_name']} | {order['customer_phone']}\n"
        f"Manzil: {order['delivery_address']}, {order['delivery_city']}"
        + (f" {order['delivery_zip']}" if order.get("delivery_zip") else "") + "\n"
        + notes_line
        + map_line + "\n"
        + f"\nMahsulotlar:\n{items_text}\n\n"
        f"Jami: {format_uzs(subtotal)}\n"
        f"Yetkazish: {format_uzs(delivery_fee)}\n"
        f"Umumiy: {format_uzs(total)}\n\n"
        f"Vaqt: {format_uz_datetime(order['created_at'])}"
    )
    try:
        async with httpx.AsyncClient() as client:
            for admin_id in ADMIN_USER_IDS:
                await client.post(
                    f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                    json={"chat_id": admin_id, "text": text},
                    timeout=10
                )
    except Exception as e:
        print(f"Telegram error: {e}")
    return

# Telegram Webhook ─────────────────────────────────────
APP_URL = os.getenv("APP_URL", "").rstrip("/")

@app.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    if not BOT_TOKEN:
        return {"ok": True}
    data = await request.json()
    message = data.get("message", {})
    chat_id = str(message.get("chat", {}).get("id", ""))
    text = message.get("text", "")
    contact = message.get("contact")

    if contact:
        user_id = str(contact.get("user_id") or chat_id)
        phone_number = str(contact.get("phone_number") or "").strip()
        if phone_number:
            now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            db = open_db()
            try:
                db.execute(
                    """
                    INSERT INTO telegram_contacts
                    (telegram_user_id, phone_number, first_name, last_name, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(telegram_user_id) DO UPDATE SET
                        phone_number=excluded.phone_number,
                        first_name=excluded.first_name,
                        last_name=excluded.last_name,
                        updated_at=excluded.updated_at
                    """,
                    (
                        user_id,
                        phone_number,
                        contact.get("first_name") or "",
                        contact.get("last_name") or "",
                        now
                    )
                )
                db.commit()
            finally:
                db.close()
        return {"ok": True}

    if text.startswith("/admin") and chat_id in ADMIN_USER_IDS:
        payload = {
            "chat_id": chat_id,
            "text": "Admin panelni oching:",
            "reply_markup": {
                "inline_keyboard": [[{
                    "text": "Admin Panel",
                    "web_app": {"url": f"{APP_URL}/admin/"}
                }]]
            }
        }
        async with httpx.AsyncClient() as client:
            await client.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json=payload, timeout=10
            )
    elif text.startswith("/admin"):
        payload = {"chat_id": chat_id, "text": "Sizda admin panelga kirish huquqi yo'q."}
        async with httpx.AsyncClient() as client:
            await client.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json=payload, timeout=10
            )
    return {"ok": True}

@app.get("/telegram/set-webhook")
async def set_webhook(_: bool = Depends(verify_admin)):
    if not APP_URL or not BOT_TOKEN:
        return {"error": "APP_URL or BOT_TOKEN not set"}
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook",
            json={"url": f"{APP_URL}/telegram/webhook"},
            timeout=10
        )
    return r.json()

# ─── Customer Routes ───────────────────────────────────────
@app.get("/api/menu")
def get_menu(db: sqlite3.Connection = Depends(get_db)):
    rows = db.execute("""
        SELECT m.* FROM menu_items m
        LEFT JOIN menu_categories c ON c.key = m.category
        WHERE m.available=1
        ORDER BY COALESCE(c.sort_order, 100), m.category, m.id
    """).fetchall()
    return [dict(r) for r in rows]

@app.get("/api/categories")
def get_categories(db: sqlite3.Connection = Depends(get_db)):
    rows = db.execute("""
        SELECT c.key, c.label_uz, c.label_ru, c.sort_order, COUNT(m.id) AS item_count
        FROM menu_categories c
        LEFT JOIN menu_items m ON m.category = c.key AND m.available = 1
        WHERE c.active = 1
        GROUP BY c.key
        ORDER BY c.sort_order, c.label_uz
    """).fetchall()
    return [dict(r) for r in rows]

@app.get("/api/telegram/contact/{telegram_user_id}")
def get_telegram_contact(
    telegram_user_id: str,
    db: sqlite3.Connection = Depends(get_db)
):
    row = db.execute(
        "SELECT phone_number, first_name, last_name, updated_at FROM telegram_contacts WHERE telegram_user_id=?",
        (telegram_user_id,)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Contact not found")
    return dict(row)

@app.post("/api/orders")
async def place_order(req: PlaceOrderRequest, db: sqlite3.Connection = Depends(get_db)):
    if not req.items:
        raise HTTPException(status_code=400, detail="Cart is empty")
    items = [i.model_dump() for i in req.items]
    for item in items:
        item["price"] = normalize_uzs_amount(item["price"])
    subtotal = sum(i["price"] * i["qty"] for i in items)
    delivery_fee = DELIVERY_FEE_UZS
    total = subtotal + delivery_fee
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    items_json = json.dumps(items)
    temp_num = f"T{int(time.time() * 1000000)}"
    cursor = db.execute("""
        INSERT INTO orders
        (order_number, customer_name, customer_phone, delivery_address, delivery_city,
         delivery_zip, delivery_notes, items, subtotal, delivery_fee, total,
         status, telegram_user_id, lat, lon, created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (temp_num, req.customer_name, req.customer_phone,
          req.delivery_address, req.delivery_city, req.delivery_zip or "",
          req.delivery_notes or "", items_json, subtotal, delivery_fee, total,
          "pending", req.telegram_user_id or "", req.lat, req.lon, now, now))
    order_id = cursor.lastrowid
    order_number = f"#{order_id:04d}"
    db.execute("UPDATE orders SET order_number=? WHERE id=?", (order_number, order_id))
    db.commit()
    order = {
        "order_number": order_number, "customer_name": req.customer_name,
        "customer_phone": req.customer_phone, "delivery_address": req.delivery_address,
        "delivery_city": req.delivery_city, "delivery_zip": req.delivery_zip,
        "delivery_notes": req.delivery_notes, "subtotal": subtotal,
        "delivery_fee": delivery_fee, "total": total, "created_at": now,
        "lat": req.lat, "lon": req.lon
    }
    asyncio.create_task(send_telegram_notification(order, items))
    return {"success": True, "order_number": order_number, "total": total}

@app.get("/api/orders/history/{telegram_user_id}")
def get_order_history(
    telegram_user_id: str,
    db: sqlite3.Connection = Depends(get_db)
):
    rows = db.execute(
        """
        SELECT order_number, items, total, status, created_at
        FROM orders
        WHERE telegram_user_id=?
        ORDER BY created_at DESC
        LIMIT 50
        """,
        (telegram_user_id,)
    ).fetchall()
    history = []
    for row in rows:
        order = dict(row)
        items = json.loads(order["items"])
        order["items_summary"] = "  ".join(
            f"{item.get('emoji','')} {item.get('name','')}x{item.get('qty', 0)}"
            for item in items
        )
        order["date"] = format_uz_datetime(order["created_at"])
        order.pop("items", None)
        history.append(order)
    return history

@app.get("/api/orders/{order_number}/status")
def get_order_status(order_number: str, db: sqlite3.Connection = Depends(get_db)):
    row = db.execute("SELECT status, created_at FROM orders WHERE order_number=?", (order_number,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Order not found")
    return dict(row)

# ─── Admin Routes ──────────────────────────────────────────
def serialize_order_row(row: sqlite3.Row) -> dict:
    order = dict(row)
    order['items'] = json.loads(order['items'])
    for item in order['items']:
        item['price'] = normalize_uzs_amount(item.get('price', 0))
    return order

def format_uz_datetime(value: Optional[str]) -> str:
    if not value:
        return ""
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(value, fmt)
            return dt.strftime("%d.%m.%Y" + (" %H:%M" if "%H" in fmt else ""))
        except ValueError:
            pass
    return value

def normalize_filter_date(value: Optional[str], field_name: str) -> Optional[str]:
    if not value:
        return None
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    raise HTTPException(status_code=400, detail=f"{field_name} must be DD.MM.YYYY")

def build_order_date_filter(date_from: Optional[str], date_to: Optional[str]):
    conditions = []
    params = []
    date_from = normalize_filter_date(date_from, "date_from")
    date_to = normalize_filter_date(date_to, "date_to")
    if date_from:
        conditions.append("created_at >= ?")
        params.append(f"{date_from} 00:00:00")
    if date_to:
        conditions.append("created_at <= ?")
        params.append(f"{date_to} 23:59:59")
    where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
    return where, params

@app.get("/api/admin/orders")
def admin_get_orders(
    status: Optional[str] = None,
    db: sqlite3.Connection = Depends(get_db),
    _: bool = Depends(verify_admin)
):
    if status and status != "all":
        rows = db.execute("SELECT * FROM orders WHERE status=? ORDER BY created_at DESC", (status,)).fetchall()
    else:
        rows = db.execute("SELECT * FROM orders WHERE status != 'deleted' ORDER BY created_at DESC").fetchall()
    return [serialize_order_row(r) for r in rows]

@app.patch("/api/admin/orders/{order_id}/status")
async def admin_update_status(
    order_id: int,
    body: UpdateOrderStatus,
    db: sqlite3.Connection = Depends(get_db),
    _: bool = Depends(verify_admin)
):
    valid = ["pending", "confirmed", "preparing", "out_for_delivery", "delivered", "cancelled"]
    if body.status not in valid:
        raise HTTPException(status_code=400, detail=f"Invalid status. Must be one of: {valid}")
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    db.execute("UPDATE orders SET status=?, updated_at=? WHERE id=?", (body.status, now, order_id))
    db.commit()
    return {"success": True, "status": body.status}

@app.delete("/api/admin/orders/{order_id}")
def admin_delete_order(
    order_id: int,
    db: sqlite3.Connection = Depends(get_db),
    _: bool = Depends(verify_admin)
):
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    cur = db.execute(
        "UPDATE orders SET status='deleted', deleted_at=?, updated_at=? WHERE id=?",
        (now, now, order_id)
    )
    db.commit()
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Order not found")
    return {"success": True}

@app.get("/api/admin/stats")
def admin_stats(
    db: sqlite3.Connection = Depends(get_db),
    _: bool = Depends(verify_admin)
):
    total_orders = db.execute("SELECT COUNT(*) FROM orders WHERE status != 'deleted'").fetchone()[0]
    revenue = db.execute("SELECT COALESCE(SUM(total),0) FROM orders WHERE status NOT IN ('cancelled','deleted')").fetchone()[0]
    pending = db.execute("SELECT COUNT(*) FROM orders WHERE status='pending'").fetchone()[0]
    today = datetime.utcnow().strftime("%Y-%m-%d")
    today_orders = db.execute(
        "SELECT COUNT(*) FROM orders WHERE status != 'deleted' AND created_at LIKE ?",
        (today+"%",)
    ).fetchone()[0]
    by_status = db.execute("SELECT status, COUNT(*) as count FROM orders WHERE status != 'deleted' GROUP BY status").fetchall()
    return {
        "total_orders": total_orders,
        "revenue": round(revenue, 2),
        "pending": pending,
        "today_orders": today_orders,
        "by_status": [dict(r) for r in by_status]
    }

@app.get("/api/admin/order-statistics")
def admin_order_statistics(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    db: sqlite3.Connection = Depends(get_db),
    _: bool = Depends(verify_admin)
):
    where, params = build_order_date_filter(date_from, date_to)
    rows = db.execute(f"SELECT * FROM orders{where} ORDER BY created_at DESC", params).fetchall()
    orders = [serialize_order_row(r) for r in rows]
    summary = {
        "total_orders": len(orders),
        "deleted_orders": sum(1 for o in orders if o["status"] == "deleted"),
        "cancelled_orders": sum(1 for o in orders if o["status"] == "cancelled"),
        "completed_orders": sum(1 for o in orders if o["status"] == "delivered"),
        "gross_revenue": round(sum(float(o.get("total") or 0) for o in orders), 2),
        "net_revenue": round(sum(float(o.get("total") or 0) for o in orders if o["status"] not in ("cancelled", "deleted")), 2),
    }
    return {"summary": summary, "orders": orders}

@app.get("/api/admin/order-statistics/export")
def admin_export_order_statistics(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    db: sqlite3.Connection = Depends(get_db),
    _: bool = Depends(verify_admin)
):
    status_labels_uz = {
        "pending": "Kutilmoqda",
        "confirmed": "Tasdiqlangan",
        "preparing": "Tayyorlanmoqda",
        "out_for_delivery": "Yo'lda",
        "delivered": "Yetkazildi",
        "cancelled": "Bekor qilindi",
        "deleted": "O'chirilgan",
    }
    where, params = build_order_date_filter(date_from, date_to)
    rows = db.execute(f"SELECT * FROM orders{where} ORDER BY created_at DESC", params).fetchall()
    table_rows = []
    for row in rows:
        order = serialize_order_row(row)
        for item in order["items"]:
            qty = int(item.get("qty") or 0)
            price = normalize_uzs_amount(item.get("price", 0))
            table_rows.append([
                order["order_number"],
                status_labels_uz.get(order["status"], order["status"]),
                format_uz_datetime(order["created_at"]),
                format_uz_datetime(order["updated_at"]),
                format_uz_datetime(order.get("deleted_at")),
                order["customer_name"],
                order["customer_phone"],
                order["delivery_address"],
                order["delivery_city"],
                order.get("delivery_zip") or "",
                order.get("delivery_notes") or "",
                item.get("name") or "",
                qty,
                price,
                qty * price,
                order["subtotal"],
                order["delivery_fee"],
                order["total"],
                order.get("lat") or "",
                order.get("lon") or "",
            ])

    headers = [
        "Buyurtma raqami", "Holat", "Yaratilgan vaqt", "Yangilangan vaqt", "O'chirilgan vaqt",
        "Mijoz ismi", "Mijoz telefoni", "Manzil", "Shahar", "Pochta indeksi", "Izohlar",
        "Mahsulot", "Miqdor", "Mahsulot narxi", "Mahsulot jami", "Oraliq jami",
        "Yetkazib berish narxi", "Buyurtma jami", "Kenglik", "Uzunlik"
    ]
    html_rows = ["<tr>" + "".join(f"<th>{html.escape(h)}</th>" for h in headers) + "</tr>"]
    for row in table_rows:
        html_rows.append("<tr>" + "".join(f"<td>{html.escape(str(v))}</td>" for v in row) + "</tr>")
    content = (
        "<html><head><meta charset='utf-8'></head><body>"
        "<table border='1'>" + "".join(html_rows) + "</table>"
        "</body></html>"
    )
    filename = f"buyurtmalar-statistikasi-{datetime.utcnow().strftime('%d%m%Y')}.xls"
    return Response(
        content=content,
        media_type="application/vnd.ms-excel",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )

@app.get("/api/admin/menu")
def admin_get_menu(
    db: sqlite3.Connection = Depends(get_db),
    _: bool = Depends(verify_admin)
):
    rows = db.execute("""
        SELECT m.* FROM menu_items m
        LEFT JOIN menu_categories c ON c.key = m.category
        ORDER BY COALESCE(c.sort_order, 100), m.category, m.id
    """).fetchall()
    return [dict(r) for r in rows]

@app.get("/api/admin/categories")
def admin_get_categories(
    db: sqlite3.Connection = Depends(get_db),
    _: bool = Depends(verify_admin)
):
    rows = db.execute("""
        SELECT c.key, c.label_uz, c.label_ru, c.sort_order, COUNT(m.id) AS item_count
        FROM menu_categories c
        LEFT JOIN menu_items m ON m.category = c.key
        WHERE c.active = 1
        GROUP BY c.key
        ORDER BY c.sort_order, c.label_uz
    """).fetchall()
    return [dict(r) for r in rows]

@app.post("/api/admin/categories")
def admin_add_category(
    body: AddCategory,
    db: sqlite3.Connection = Depends(get_db),
    _: bool = Depends(verify_admin)
):
    label_uz = body.label_uz.strip()
    if not label_uz:
        raise HTTPException(status_code=400, detail="Category name is required")
    base_key = make_category_key(label_uz)
    key = base_key
    suffix = 2
    while db.execute("SELECT 1 FROM menu_categories WHERE key=?", (key,)).fetchone():
        key = f"{base_key}-{suffix}"
        suffix += 1
    next_order = db.execute(
        "SELECT MIN(COALESCE((SELECT MAX(sort_order) FROM menu_categories WHERE sort_order < 1000), 30) + 10, 990)"
    ).fetchone()[0]
    db.execute(
        "INSERT INTO menu_categories (key,label_uz,label_ru,sort_order,active) VALUES (?,?,?,?,1)",
        (key, label_uz, (body.label_ru or label_uz).strip(), next_order)
    )
    db.commit()
    return {"success": True, "key": key, "label_uz": label_uz, "label_ru": body.label_ru or label_uz, "sort_order": next_order}

@app.patch("/api/admin/menu/{item_id}")
def admin_update_menu(
    item_id: int,
    body: UpdateMenuItem,
    db: sqlite3.Connection = Depends(get_db),
    _: bool = Depends(verify_admin)
):
    if body.price is not None:
        db.execute("UPDATE menu_items SET price=? WHERE id=?", (body.price, item_id))
    if body.available is not None:
        db.execute("UPDATE menu_items SET available=? WHERE id=?", (body.available, item_id))
    if body.badge is not None:
        db.execute("UPDATE menu_items SET badge=? WHERE id=?", (body.badge or None, item_id))
    if body.photo is not None:
        db.execute("UPDATE menu_items SET photo=? WHERE id=?", (body.photo or None, item_id))
    db.commit()
    return {"success": True}

@app.post("/api/admin/menu")
def admin_add_menu_item(
    body: AddMenuItem,
    db: sqlite3.Connection = Depends(get_db),
    _: bool = Depends(verify_admin)
):
    db.execute(
        "INSERT INTO menu_items (category,emoji,name,description,price,badge,available,photo) VALUES (?,?,?,?,?,?,?,?)",
        (body.category, body.emoji, body.name, body.description or "",
         body.price, body.badge or None, 1, body.photo)
    )
    db.commit()
    return {"success": True}

@app.delete("/api/admin/menu/{item_id}")
def admin_delete_menu_item(
    item_id: int,
    db: sqlite3.Connection = Depends(get_db),
    _: bool = Depends(verify_admin)
):
    db.execute("DELETE FROM menu_items WHERE id=?", (item_id,))
    db.commit()
    return {"success": True}

# ─── Serve static files ────────────────────────────────────
app.mount("/admin", StaticFiles(directory="frontend/admin", html=True), name="admin")
app.mount("/", StaticFiles(directory="frontend/customer", html=True), name="customer")

