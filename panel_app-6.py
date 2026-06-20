"""
SMM Panel Telegram Bot
----------------------
Full bot with Wallet, Affiliate Program, Orders, and Admin Panel.

Setup:
1) pip install python-telegram-bot --upgrade
2) Put your bot token below in BOT_TOKEN (from BotFather)
3) python smm_bot.py
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
import json
import os
import time
import uuid
import httpx

# ===================== CONFIG =====================
BOT_TOKEN = "8583974530:AAGU9eK6_tIzYyAfzF0hdrrN_mJT9D6k4G4"   # <-- token from BotFather
JOIN_CHANNEL = "@LiteDropX"
SUPPORT_USERNAME = "@TheNikoLaiii"
BOT_USERNAME = "SMMPanelAiRobot"   # <-- change this to your bot's actual username (without @)
ADMIN_ID = 6520878121
COMMISSION_RATE = 0.05  # 5%

# ---- GRAM Autopay (TON) config ----
GRAM_WALLET_ADDRESS = "UQB4rr2U6zTQCNq-jENXpmfQjUCe6cSpiy2tfSeT9JNyo3Rj"
TONCENTER_API = "https://toncenter.com/api/v2/getTransactions"
COINGECKO_API = "https://api.coingecko.com/api/v3/simple/price"
MIN_DEPOSIT_USD = 0.1

# ---- SMM Provider (reseller panel) config ----
PROVIDER_API_URL = "https://1xpanel.com/api/v2"
PROVIDER_API_KEY = "f415d758d266119c18c84453354ffa10"
SERVICES_CACHE_SECONDS = 600  # refresh provider catalog cache every 10 min (used only for admin search)

PLATFORM_KEYS = ["telegram", "tiktok", "twitter", "instagram", "youtube", "facebook"]
PLATFORM_LABELS = {
    "telegram": "Telegram",
    "tiktok": "TikTok",
    "twitter": "Twitter (X)",
    "instagram": "Instagram",
    "youtube": "YouTube",
    "facebook": "Facebook",
}

# ===================== STORAGE (simple JSON file based) =====================
DATA_FILE = "wallet_data.json"


def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            data = json.load(f)
            data.setdefault("processed_tx", [])
            data.setdefault("custom_services", [])
            return data
    return {"users": {}, "transactions": [], "processed_tx": [], "custom_services": []}


def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)


def get_user(user_id):
    data = load_data()
    uid = str(user_id)
    if uid not in data["users"]:
        data["users"][uid] = {
            "balance": 0.0,
            "orders_placed": 0,
            "orders": [],
            "total_spending": 0.0,
            "banned": False,
            "referred_by": None,
            "referrals": [],
            "total_earned": 0.0,
            "username": None,
            "first_name": "",
        }
        save_data(data)
    return data["users"][uid]


def update_user(user_id, user_record):
    data = load_data()
    data["users"][str(user_id)] = user_record
    save_data(data)


def add_global_transaction(user_id, amount, tx_hash):
    data = load_data()
    data["transactions"].append({
        "user_id": user_id,
        "amount": amount,
        "hash": tx_hash,
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
    })
    save_data(data)


def all_users():
    data = load_data()
    return data["users"]


def is_admin(user_id):
    return user_id == ADMIN_ID


# ===================== SMM PROVIDER API (1xpanel — standard "Perfect Panel" format) =====================
_services_cache = {"data": [], "fetched_at": 0}


async def provider_request(params: dict) -> dict:
    """Sends a request to the SMM provider's API. Always include 'key' + 'action'."""
    payload = {"key": PROVIDER_API_KEY, **params}
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(PROVIDER_API_URL, data=payload)
        resp.raise_for_status()
        return resp.json()


async def get_provider_services(force_refresh: bool = False) -> list:
    """Fetches (and caches) the full services list from the provider. Used by admin to find IDs."""
    now = time.time()
    if not force_refresh and _services_cache["data"] and (now - _services_cache["fetched_at"] < SERVICES_CACHE_SECONDS):
        return _services_cache["data"]

    result = await provider_request({"action": "services"})
    if isinstance(result, list):
        _services_cache["data"] = result
        _services_cache["fetched_at"] = now
        return result
    return _services_cache["data"]  # fall back to stale cache on error


async def search_provider_services(keyword: str, limit: int = 15) -> list:
    """Admin tool: search the full provider catalog by keyword (matches name or category)."""
    services = await get_provider_services()
    kw = keyword.lower()
    matches = [
        s for s in services
        if kw in str(s.get("name", "")).lower() or kw in str(s.get("category", "")).lower()
    ]
    return matches[:limit]


async def find_provider_service(service_id: str) -> dict | None:
    """Admin tool: look up one provider service's details by its ID."""
    services = await get_provider_services()
    for s in services:
        if str(s.get("service")) == str(service_id):
            return s
    return None


def add_custom_service(provider_service_id, name, price, platform, min_qty, max_qty) -> str:
    """Adds an admin-curated service that will show up in /services for users."""
    data = load_data()
    custom_id = uuid.uuid4().hex[:8]
    data.setdefault("custom_services", []).append({
        "id": custom_id,
        "provider_service_id": provider_service_id,
        "name": name,
        "price": price,
        "platform": platform,
        "min": min_qty,
        "max": max_qty,
    })
    save_data(data)
    return custom_id


def get_custom_services(platform: str = None) -> list:
    data = load_data()
    services = data.get("custom_services", [])
    if platform:
        return [s for s in services if s.get("platform") == platform]
    return services


def find_custom_service(custom_id: str) -> dict | None:
    for s in get_custom_services():
        if s["id"] == custom_id:
            return s
    return None


def remove_custom_service(custom_id: str) -> bool:
    data = load_data()
    services = data.get("custom_services", [])
    new_services = [s for s in services if s["id"] != custom_id]
    removed = len(new_services) != len(services)
    data["custom_services"] = new_services
    save_data(data)
    return removed


async def place_provider_order(service_id, link: str, quantity: int) -> dict:
    """Places an order with the provider. Returns the raw API response (contains 'order' id or 'error')."""
    return await provider_request({
        "action": "add",
        "service": service_id,
        "link": link,
        "quantity": quantity,
    })


async def get_provider_order_status(order_id) -> dict:
    """Checks an order's status with the provider."""
    return await provider_request({"action": "status", "order": order_id})


async def get_provider_balance() -> dict:
    """Checks our own balance with the provider (useful for admin)."""
    return await provider_request({"action": "balance"})


# ===================== GRAM AUTOPAY (TON blockchain verification) =====================
async def get_ton_price_usd() -> float:
    """Fetches current TON price in USD from CoinGecko."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            COINGECKO_API, params={"ids": "the-open-network", "vs_currencies": "usd"}
        )
        resp.raise_for_status()
        data = resp.json()
        return float(data["the-open-network"]["usd"])


async def fetch_wallet_transactions(limit: int = 50):
    """Fetches recent incoming transactions for the GRAM wallet from TonCenter."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            TONCENTER_API,
            params={"address": GRAM_WALLET_ADDRESS, "limit": limit, "archival": "true"},
        )
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            return []
        return data.get("result", [])


def extract_comment(in_msg: dict) -> str:
    """Pulls the memo/comment text out of a TonCenter in_msg object."""
    if not in_msg:
        return ""
    msg = in_msg.get("message")
    if msg:
        return msg.strip()
    msg_data = in_msg.get("msg_data", {}) or {}
    if msg_data.get("@type") == "msg.dataText":
        return (msg_data.get("text") or "").strip()
    return ""


async def verify_gram_deposit(user_id: int, min_ton: float = 0.0):
    """
    Checks the GRAM wallet for a new, not-yet-credited deposit whose memo matches
    this user's Telegram ID. If found: converts the TON amount to USD, credits the
    user's wallet, records the transaction, and marks the on-chain tx as processed.
    If min_ton > 0, transactions sending less than that amount are skipped (not
    credited) so the user must send the full amount they requested.
    Returns (usd_amount, ton_amount, tx_hash) if a new deposit was credited, else None.
    """
    data = load_data()
    processed = set(data.get("processed_tx", []))
    memo = str(user_id)

    transactions = await fetch_wallet_transactions()

    for tx in transactions:
        in_msg = tx.get("in_msg", {}) or {}
        comment = extract_comment(in_msg)
        if comment != memo:
            continue

        value_nanotons = int(in_msg.get("value", 0) or 0)
        if value_nanotons <= 0:
            continue

        tx_hash = tx.get("transaction_id", {}).get("hash", "")
        if not tx_hash or tx_hash in processed:
            continue

        ton_amount = value_nanotons / 1e9
        if min_ton and ton_amount + 1e-9 < min_ton:
            # Underpaid relative to the amount the user said they'd send — skip for now.
            continue

        price = await get_ton_price_usd()
        usd_amount = round(ton_amount * price, 3)

        # Credit user's wallet
        user = get_user(user_id)
        user["balance"] += usd_amount
        update_user(user_id, user)

        # Record transaction + mark this on-chain tx as processed (prevents double-credit)
        data = load_data()
        data["transactions"].append({
            "user_id": user_id,
            "amount": usd_amount,
            "hash": tx_hash,
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "type": "GRAM Autopay",
            "ton_amount": ton_amount,
        })
        data.setdefault("processed_tx", []).append(tx_hash)
        save_data(data)

        return usd_amount, ton_amount, tx_hash

    return None


# ===================== Business logic helpers =====================
def record_deposit(user_id, amount):
    """Call this when a deposit is confirmed (e.g. after GRAM Autopay success)."""
    user = get_user(user_id)
    user["balance"] += amount
    update_user(user_id, user)
    tx_hash = uuid.uuid4().hex[:16]
    add_global_transaction(user_id, amount, tx_hash)
    return tx_hash


def place_order(user_id, order_cost):
    """Call this when a user places an order. Deducts balance, pays referrer commission."""
    user = get_user(user_id)
    user["balance"] -= order_cost
    user["orders_placed"] += 1
    user["total_spending"] += order_cost
    update_user(user_id, user)

    referrer_id = user.get("referred_by")
    if referrer_id:
        commission = order_cost * COMMISSION_RATE
        ref_user = get_user(referrer_id)
        ref_user["balance"] += commission
        ref_user["total_earned"] += commission
        update_user(referrer_id, ref_user)


# ===================== TEXT TEMPLATES =====================
WELCOME_TEXT = (
    "🚀 *SMM Panel Menu* -- a Social Media Marketing Service provider Telegram bot.\n"
    "At cheapest price on telegram,\n\n"
    f"Join {JOIN_CHANNEL} for Maintenance, Service, Price cost updates!"
)

HELP_TEXT = (
    "🚀 *Welcome to SMM Panel*\n\n"
    "📈 Grow your social media faster with reliable and affordable services.\n\n"
    "📂 *Available Services:*\n"
    "📂 Telegram Services\n"
    "📂 TikTok Services\n"
    "📂 Twitter (X) Services\n"
    "📂 Instagram Services\n"
    "📂 YouTube Services\n"
    "📂 Facebook Services\n\n"
    "✨ *Features:*\n"
    "💰 Wallet System\n"
    "📦 Order Management\n"
    "🏆 Affiliate Program (5% Lifetime Commission)\n"
    "🎁 Welcome Bonus\n"
    "⚡ Instant Processing\n"
    "🤖 Fully Automated 24/7\n\n"
    "✅ High-Quality Services\n"
    "✅ Fast Delivery\n"
    "✅ Secure & Easy to Use\n\n"
    f"📩 Support: {SUPPORT_USERNAME}"
)


# ===================== MENU LAYOUT =====================
def main_menu_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("🚀 All Media Services", callback_data="services")],
        [
            InlineKeyboardButton("💳 Wallet", callback_data="wallet"),
            InlineKeyboardButton("📦 Orders", callback_data="orders"),
        ],
        [
            InlineKeyboardButton("🤝 Affiliate Program", callback_data="aff_program"),
            InlineKeyboardButton("📑 Help", callback_data="help"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


# ===================== USER HANDLERS =====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)

    # Keep username/first name fresh for admin lookups
    user["username"] = update.effective_user.username
    user["first_name"] = update.effective_user.first_name or ""
    update_user(user_id, user)

    # Handle referral deep link: /start <referrer_id>
    if context.args:
        ref_arg = context.args[0]
        if ref_arg.isdigit():
            referrer_id = int(ref_arg)
            if referrer_id != user_id and not user.get("referred_by"):
                user["referred_by"] = referrer_id
                update_user(user_id, user)
                ref_user = get_user(referrer_id)
                if user_id not in ref_user["referrals"]:
                    ref_user["referrals"].append(user_id)
                    update_user(referrer_id, ref_user)

    await update.message.reply_text(
        WELCOME_TEXT,
        reply_markup=main_menu_keyboard(),
        parse_mode=ParseMode.MARKDOWN,
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id

    if data == "services":
        context.user_data["awaiting_order_link"] = False
        context.user_data["awaiting_order_quantity"] = False
        context.user_data.pop("pending_order", None)
        text = "🛒 *Pick a Service:*"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📂 Telegram Services", callback_data="svc_telegram")],
            [InlineKeyboardButton("📂 TikTok Services", callback_data="svc_tiktok")],
            [InlineKeyboardButton("📂 Twitter (X) Services", callback_data="svc_twitter")],
            [InlineKeyboardButton("📂 Instagram Services", callback_data="svc_instagram")],
            [InlineKeyboardButton("📂 YouTube Services", callback_data="svc_youtube")],
            [InlineKeyboardButton("📂 Facebook Services", callback_data="svc_facebook")],
            [InlineKeyboardButton("🔝 Main Menu", callback_data="back_to_menu")],
        ])
        await query.edit_message_text(text=text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
        return

    elif data == "wallet":
        user = get_user(user_id)
        text = (
            "👝 *Your Wallet Overview*\n\n"
            f"💎 *Balance:* `${user['balance']:.3f}`\n"
            f"🆔 *User ID:* `{user_id}`\n\n"
            f"📦 *Orders Placed:* {user['orders_placed']}\n"
            f"💸 *Total Spending:* `${user['total_spending']:.2f}`"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📥 Deposit", callback_data="deposit")],
            [InlineKeyboardButton("📜 Transaction History", callback_data="tx_history")],
            [InlineKeyboardButton("🔝 Main Menu", callback_data="back_to_menu")],
        ])
        await query.edit_message_text(text=text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
        return

    elif data == "deposit":
        context.user_data["awaiting_deposit_amount"] = False
        text = (
            "➕ *Add Funds to Your* 💳 *Wallet!*\n\n"
            "💰 Automatic Deposit via GRAM Only\n"
            "⚡ Instant & Secure Processing\n\n"
            "📩 Prefer Binance Pay or Other Methods?\n"
            f"Contact {SUPPORT_USERNAME}\n\n"
            "🚀 Fast, simple & reliable top-up system"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("💸 GRAM AUTOPAY", callback_data="gram_autopay")],
            [
                InlineKeyboardButton("🔙 Back", callback_data="wallet"),
                InlineKeyboardButton("🔝 Main Menu", callback_data="back_to_menu"),
            ],
        ])
        await query.edit_message_text(text=text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
        return

    elif data == "tx_history":
        user = get_user(user_id)
        data_all = load_data()
        my_tx = [t for t in data_all["transactions"] if t["user_id"] == user_id]
        if not my_tx:
            text = "📜 *Transaction History*\n\nNo transactions yet."
        else:
            lines = ["📜 *Transaction History*\n"]
            for tx in my_tx[-20:]:
                lines.append(
                    f"💰 *Amount:* `${tx['amount']:.2f}`\n"
                    f"🧾 *Hash:* `{tx['hash']}`\n"
                    f"🕒 *Time:* {tx['time']}\n"
                )
            text = "\n".join(lines)
        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🔙 Back", callback_data="wallet"),
                InlineKeyboardButton("🔝 Main Menu", callback_data="back_to_menu"),
            ],
        ])
        await query.edit_message_text(text=text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
        return

    elif data == "gram_autopay":
        context.user_data["awaiting_deposit_amount"] = True
        text = (
            "💰 *Enter Deposit Amount (USD)*\n\n"
            "📌 *Minimum:* $0.1\n\n"
            "_Example: 0.50 | 1 | 5_"
        )
        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🔙 Back", callback_data="deposit"),
                InlineKeyboardButton("🔝 Main Menu", callback_data="back_to_menu"),
            ],
        ])
        await query.edit_message_text(text=text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
        return

    elif data == "verify_gram":
        await query.edit_message_text("🔍 Checking the blockchain for your deposit, please wait...")
        pending = context.user_data.get("pending_deposit")
        min_ton = pending["ton"] if pending else 0.0
        try:
            result = await verify_gram_deposit(user_id, min_ton=min_ton)
        except Exception:
            result = None

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Try Again", callback_data="verify_gram")],
            [
                InlineKeyboardButton("🔙 Back", callback_data="deposit"),
                InlineKeyboardButton("🔝 Main Menu", callback_data="back_to_menu"),
            ],
        ])

        if result:
            usd_amount, ton_amount, tx_hash = result
            context.user_data.pop("pending_deposit", None)
            text = (
                "✅ *Deposit Confirmed!*\n\n"
                f"💎 *Received:* `{ton_amount:.4f} TON`\n"
                f"💵 *Credited:* `${usd_amount:.3f}`\n"
                f"🧾 *Tx Hash:* `{tx_hash}`\n\n"
                "Your wallet balance has been updated."
            )
        else:
            amount_line = f" (`{pending['ton']:.4f} TON`)" if pending else ""
            text = (
                "⏳ *No new deposit found yet.*\n\n"
                "Please make sure you:\n"
                "1️⃣ Sent to the correct address\n"
                f"2️⃣ Sent the exact amount requested{amount_line}\n"
                f"3️⃣ Included memo `{user_id}` exactly\n\n"
                "On-chain confirmation can take a minute or two — try again shortly."
            )
        await query.edit_message_text(text=text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
        return

    elif data == "orders":
        user = get_user(user_id)
        orders = user.get("orders", [])

        if not orders:
            text = (
                "📦 *My Orders*\n\n"
                "No orders yet.\n\n"
                f"🧾 *Total Orders Placed:* {user['orders_placed']}\n"
                f"💸 *Total Spent:* `${user['total_spending']:.2f}`"
            )
        else:
            recent = orders[-10:]
            for o in recent:
                if o.get("status") not in ("Completed", "Canceled", "Cancelled"):
                    try:
                        status_resp = await get_provider_order_status(o["id"])
                        if "status" in status_resp:
                            o["status"] = status_resp["status"]
                    except Exception:
                        pass
            update_user(user_id, user)

            lines = ["📦 *My Orders* (most recent first)\n"]
            for o in reversed(recent):
                lines.append(
                    f"🆔 `{o['id']}` | {o.get('service', '-')}\n"
                    f"🔢 Qty: {o.get('quantity', '-')} | 💵 `${o.get('price', 0):.2f}` | "
                    f"📊 {o.get('status', 'Pending')}\n"
                )
            lines.append(f"🧾 *Total Orders Placed:* {user['orders_placed']}")
            lines.append(f"💸 *Total Spent:* `${user['total_spending']:.2f}`")
            text = "\n".join(lines)

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Refresh", callback_data="orders")],
            [InlineKeyboardButton("🔝 Main Menu", callback_data="back_to_menu")],
        ])
        await query.edit_message_text(text=text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
        return

    elif data == "aff_program":
        user = get_user(user_id)
        link = f"https://t.me/{BOT_USERNAME}?start={user_id}"
        text = (
            "🤝 *Affiliate Program*\n\n"
            "💸 Share your unique Affiliate link and earn 5% Commission of order cost on "
            "every order placed by your referrals—forever! The more they spend, the more "
            "you earn. No limits, no effort—just passive income!\n\n"
            f"🔗 *Affiliate Link:*\n`{link}`"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📊 Affiliate Statistics", callback_data="aff_stats")],
            [InlineKeyboardButton("🔝 Main Menu", callback_data="back_to_menu")],
        ])
        await query.edit_message_text(text=text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
        return

    elif data == "aff_stats":
        user = get_user(user_id)
        text = (
            "📊 *Affiliate Statistics*\n\n"
            f"👥 *Total Referred:* {len(user['referrals'])}\n"
            f"💰 *Total Earned:* `${user['total_earned']:.2f}`"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔝 Main Menu", callback_data="back_to_menu")],
        ])
        await query.edit_message_text(text=text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
        return

    elif data == "help":
        text = HELP_TEXT
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔝 Main Menu", callback_data="back_to_menu")],
        ])
        await query.edit_message_text(text=text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
        return

    elif data.startswith("svc_") and not data.startswith("svc_page_"):
        platform_key = data[len("svc_"):]
        platform_label = PLATFORM_LABELS.get(platform_key, platform_key.title())
        services = get_custom_services(platform_key)

        if not services:
            text = f"📂 *{platform_label} Services*\n\nNo services added yet."
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data="services")],
                [InlineKeyboardButton("🔝 Main Menu", callback_data="back_to_menu")],
            ])
            await query.edit_message_text(text=text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
            return

        rows = []
        for s in services:
            label = f"{s['name'][:35]} — ${s['price']:.2f}/1k"
            rows.append([InlineKeyboardButton(label, callback_data=f"selsvc_{s['id']}")])
        rows.append([InlineKeyboardButton("🔙 Back", callback_data="services")])
        rows.append([InlineKeyboardButton("🔝 Main Menu", callback_data="back_to_menu")])

        text = f"📂 *{platform_label} Services*\n\nSelect a service below:"
        await query.edit_message_text(text=text, reply_markup=InlineKeyboardMarkup(rows), parse_mode=ParseMode.MARKDOWN)
        return

    elif data.startswith("selsvc_"):
        custom_id = data.split("_", 1)[1]
        svc = find_custom_service(custom_id)
        if not svc:
            text = "⚠️ This service is no longer available. Please reopen the menu."
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("🚀 All Media Services", callback_data="services")],
                [InlineKeyboardButton("🔝 Main Menu", callback_data="back_to_menu")],
            ])
            await query.edit_message_text(text=text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
            return

        context.user_data["pending_order"] = {
            "custom_id": svc["id"],
            "provider_service_id": svc["provider_service_id"],
            "name": svc["name"],
            "price": svc["price"],
            "min": svc["min"],
            "max": svc["max"],
        }
        context.user_data["awaiting_order_link"] = True

        text = (
            f"🛒 *{svc['name']}*\n\n"
            f"💵 *Rate:* `${svc['price']:.2f}` per 1000\n"
            f"📉 *Min:* {svc['min']}  📈 *Max:* {svc['max']}\n\n"
            "🔗 Please send the *link* (your post/profile/video URL) for this order."
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Cancel", callback_data="services")],
        ])
        await query.edit_message_text(text=text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
        return

    else:
        text = "Unknown option."

    back_kb = InlineKeyboardMarkup(
        [[InlineKeyboardButton("⬅️ Back", callback_data="back_to_menu")]]
    )
    await query.edit_message_text(text=text, reply_markup=back_kb, parse_mode=ParseMode.MARKDOWN)


async def back_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["awaiting_deposit_amount"] = False
    context.user_data.pop("pending_deposit", None)
    context.user_data["awaiting_order_link"] = False
    context.user_data["awaiting_order_quantity"] = False
    context.user_data.pop("pending_order", None)
    await query.edit_message_text(
        text=WELCOME_TEXT,
        reply_markup=main_menu_keyboard(),
        parse_mode=ParseMode.MARKDOWN,
    )


async def route_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = update.callback_query.data
    if data == "back_to_menu":
        await back_to_menu(update, context)
    elif data.startswith("admin_") or data.startswith("adm_"):
        await admin_callback(update, context)
    else:
        await button_handler(update, context)


# ===================== ADMIN PANEL =====================
def admin_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔍 Search Provider Catalog", callback_data="admin_search_provider")],
        [InlineKeyboardButton("➕ Add Service", callback_data="admin_add_service")],
        [InlineKeyboardButton("🛍 My Services", callback_data="admin_my_services")],
        [InlineKeyboardButton("🔍 View User", callback_data="admin_view_user")],
        [InlineKeyboardButton("📦 All Orders", callback_data="admin_all_orders")],
        [
            InlineKeyboardButton("🚫 Ban User", callback_data="admin_ban"),
            InlineKeyboardButton("✅ Unban User", callback_data="admin_unban"),
        ],
        [InlineKeyboardButton("💰 All Deposits", callback_data="admin_all_deposits")],
        [InlineKeyboardButton("👥 All Users Balance", callback_data="admin_all_balances")],
        [InlineKeyboardButton("📋 All Users List", callback_data="admin_users_list")],
        [InlineKeyboardButton("🧾 Recent Transactions (30)", callback_data="admin_recent_tx")],
        [
            InlineKeyboardButton("➕ Add Balance", callback_data="admin_add_balance"),
            InlineKeyboardButton("➖ Subtract Balance", callback_data="admin_sub_balance"),
        ],
        [InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast")],
    ])


async def adminpanel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ This command is for admin only.")
        return
    await update.message.reply_text(
        "🛠 *Admin Panel*\n\nChoose an action below:",
        reply_markup=admin_menu_keyboard(),
        parse_mode=ParseMode.MARKDOWN,
    )


async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.from_user.id != ADMIN_ID:
        await query.edit_message_text("⛔ This action is for admin only.")
        return

    data = query.data
    back_kb = InlineKeyboardMarkup(
        [[InlineKeyboardButton("⬅️ Back to Admin Panel", callback_data="admin_back")]]
    )

    if data == "admin_back":
        await query.edit_message_text(
            "🛠 *Admin Panel*\n\nChoose an action below:",
            reply_markup=admin_menu_keyboard(),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    elif data == "admin_search_provider":
        context.user_data["admin_action"] = "search_provider"
        text = (
            "🔍 Send a *keyword* to search the provider's full catalog "
            "(e.g. `instagram followers`, `telegram members`).\n\n"
            "I'll show matching Service ID, name, real cost/1k, and min-max — "
            "use the ID with ➕ Add Service."
        )
        await query.edit_message_text(text=text, reply_markup=back_kb, parse_mode=ParseMode.MARKDOWN)
        return

    elif data == "admin_add_service":
        context.user_data["admin_action"] = "add_service_id"
        context.user_data.pop("new_service", None)
        text = (
            "➕ *Add a Service*\n\n"
            "Send the *provider Service ID* (from 1xpanel) you want to add.\n"
            "Don't know the ID? Use 🔍 Search Provider Catalog first."
        )
        await query.edit_message_text(text=text, reply_markup=back_kb, parse_mode=ParseMode.MARKDOWN)
        return

    elif data == "admin_my_services":
        services = get_custom_services()
        if not services:
            text = "🛍 *My Services*\n\nNo services added yet. Use ➕ Add Service to add one."
        else:
            lines = ["🛍 *My Services*\n"]
            for s in services:
                plat = PLATFORM_LABELS.get(s["platform"], s["platform"])
                lines.append(
                    f"🆔 `{s['id']}` | {s['name']} | {plat} | ${s['price']:.2f}/1k "
                    f"| min {s['min']}-max {s['max']}"
                )
            lines.append("\n_To remove one, send its ID after tapping 🗑 Remove Service._")
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🗑 Remove Service", callback_data="admin_remove_service")],
            [InlineKeyboardButton("⬅️ Back to Admin Panel", callback_data="admin_back")],
        ])
        await query.edit_message_text(text=text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
        return

    elif data == "admin_remove_service":
        context.user_data["admin_action"] = "remove_service"
        text = "🗑 Send the *Service ID* (shown in 🛍 My Services) you want to remove."
        await query.edit_message_text(text=text, reply_markup=back_kb, parse_mode=ParseMode.MARKDOWN)
        return

    elif data == "admin_view_user":
        context.user_data["admin_action"] = "view_user"
        text = "🔍 Send the *User ID* you want to view full details for."
        await query.edit_message_text(text=text, reply_markup=back_kb, parse_mode=ParseMode.MARKDOWN)
        return

    elif data == "admin_users_list":
        users = all_users()
        total = len(users)
        if total == 0:
            text = "📋 *All Users*\n\nNo users yet."
        else:
            items = list(users.items())
            lines = [f"📋 *All Users* — Total: *{total}*\n"]
            for uid, u in items[:70]:
                uname = u.get("username")
                uname_str = f"@{uname}" if uname else "—"
                fname = u.get("first_name") or "—"
                lines.append(f"🆔 `{uid}` | {uname_str} | {fname}")
            if total > 70:
                lines.append(f"\n_...and {total - 70} more (showing first 70)._")
            text = "\n".join(lines)

    elif data == "admin_broadcast":
        context.user_data["admin_action"] = "broadcast"
        text = "📢 Send the *message* you want to broadcast to all bot users."
        await query.edit_message_text(text=text, reply_markup=back_kb, parse_mode=ParseMode.MARKDOWN)
        return

    elif data == "admin_all_orders":
        users = all_users()
        lines = ["📦 *All Orders*\n"]
        any_orders = False
        for uid, u in users.items():
            if u["orders_placed"] > 0:
                any_orders = True
                lines.append(f"🆔 `{uid}` — Orders: {u['orders_placed']} — Spent: `${u['total_spending']:.2f}`")
        if not any_orders:
            lines.append("No orders placed yet.")
        text = "\n".join(lines)

    elif data == "admin_all_deposits":
        data_all = load_data()
        if not data_all["transactions"]:
            text = "💰 *All Deposits*\n\nNo deposits yet."
        else:
            lines = ["💰 *All Deposits*\n"]
            for tx in data_all["transactions"][-50:]:
                lines.append(
                    f"🆔 `{tx['user_id']}` | 💵 `${tx['amount']:.2f}` | 🧾 `{tx['hash']}` | 🕒 {tx['time']}"
                )
            text = "\n".join(lines)

    elif data == "admin_all_balances":
        users = all_users()
        sorted_users = sorted(users.items(), key=lambda x: x[1]["balance"], reverse=True)
        if not sorted_users:
            text = "👥 *All Users Balance*\n\nNo users yet."
        else:
            lines = ["👥 *All Users Balance* (highest first)\n"]
            for uid, u in sorted_users:
                ban_tag = " 🚫" if u.get("banned") else ""
                lines.append(f"🆔 `{uid}` — `${u['balance']:.3f}`{ban_tag}")
            text = "\n".join(lines)

    elif data == "admin_recent_tx":
        data_all = load_data()
        recent = data_all["transactions"][-30:]
        if not recent:
            text = "🧾 *Recent Transactions*\n\nNo transactions yet."
        else:
            lines = ["🧾 *Recent 30 Transactions*\n"]
            for tx in reversed(recent):
                lines.append(
                    f"🆔 `{tx['user_id']}` | 💵 `${tx['amount']:.2f}` | 🕒 {tx['time']}"
                )
            text = "\n".join(lines)

    elif data == "admin_ban":
        context.user_data["admin_action"] = "ban"
        text = "🚫 Send the *User ID* you want to ban."
        await query.edit_message_text(text=text, reply_markup=back_kb, parse_mode=ParseMode.MARKDOWN)
        return

    elif data == "admin_unban":
        context.user_data["admin_action"] = "unban"
        text = "✅ Send the *User ID* you want to unban."
        await query.edit_message_text(text=text, reply_markup=back_kb, parse_mode=ParseMode.MARKDOWN)
        return

    elif data == "admin_add_balance":
        context.user_data["admin_action"] = "add_balance"
        text = "➕ Send: `USER_ID AMOUNT`\nExample: `6520878121 5.00`"
        await query.edit_message_text(text=text, reply_markup=back_kb, parse_mode=ParseMode.MARKDOWN)
        return

    elif data == "admin_sub_balance":
        context.user_data["admin_action"] = "sub_balance"
        text = "➖ Send: `USER_ID AMOUNT`\nExample: `6520878121 5.00`"
        await query.edit_message_text(text=text, reply_markup=back_kb, parse_mode=ParseMode.MARKDOWN)
        return

    else:
        text = "Unknown admin action."

    await query.edit_message_text(text=text, reply_markup=back_kb, parse_mode=ParseMode.MARKDOWN)


async def admin_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles admin's text replies for ban/unban/add/subtract balance."""
    if update.effective_user.id != ADMIN_ID:
        return
    action = context.user_data.get("admin_action")
    if not action:
        return  # not waiting for admin input, ignore
    text_in = update.message.text.strip()
    context.user_data["admin_action"] = None  # clear state

    try:
        if action == "ban":
            target_id = int(text_in)
            user = get_user(target_id)
            user["banned"] = True
            update_user(target_id, user)
            await update.message.reply_text(f"🚫 User `{target_id}` has been banned.", parse_mode=ParseMode.MARKDOWN)

        elif action == "unban":
            target_id = int(text_in)
            user = get_user(target_id)
            user["banned"] = False
            update_user(target_id, user)
            await update.message.reply_text(f"✅ User `{target_id}` has been unbanned.", parse_mode=ParseMode.MARKDOWN)

        elif action == "add_balance":
            target_id_str, amount_str = text_in.split()
            target_id = int(target_id_str)
            amount = float(amount_str)
            user = get_user(target_id)
            user["balance"] += amount
            update_user(target_id, user)
            await update.message.reply_text(
                f"➕ Added `${amount:.2f}` to user `{target_id}`. New balance: `${user['balance']:.3f}`",
                parse_mode=ParseMode.MARKDOWN,
            )

        elif action == "sub_balance":
            target_id_str, amount_str = text_in.split()
            target_id = int(target_id_str)
            amount = float(amount_str)
            user = get_user(target_id)
            user["balance"] -= amount
            update_user(target_id, user)
            await update.message.reply_text(
                f"➖ Subtracted `${amount:.2f}` from user `{target_id}`. New balance: `${user['balance']:.3f}`",
                parse_mode=ParseMode.MARKDOWN,
            )

        elif action == "view_user":
            target_id = int(text_in)
            user = get_user(target_id)
            data_all = load_data()
            my_tx = [t for t in data_all["transactions"] if t["user_id"] == target_id]
            total_deposited = sum(t["amount"] for t in my_tx)
            orders = user.get("orders", [])

            uname = user.get("username")
            uname_str = f"@{uname}" if uname else "—"
            fname = user.get("first_name") or "—"

            lines = [
                f"👤 *User Details — `{target_id}`*",
                f"🪪 *Name:* {fname}  |  *Username:* {uname_str}\n",
                f"💰 *Balance:* `${user['balance']:.3f}`",
                f"🚫 *Banned:* {'Yes' if user.get('banned') else 'No'}",
                f"🔗 *Referred By:* `{user.get('referred_by') or 'None'}`",
                "",
                "📦 *Orders*",
                f"Total Orders Placed: {user['orders_placed']}",
                f"Total Spent: `${user['total_spending']:.2f}`",
            ]
            if orders:
                lines.append("")
                for o in orders[-20:]:
                    lines.append(
                        f"🆔 `{o.get('id', '-')}` | {o.get('service', '-')} | "
                        f"Qty: {o.get('quantity', '-')} | 💵 `${o.get('price', 0):.2f}` | "
                        f"Status: {o.get('status', '-')}"
                    )
            else:
                lines.append("_No individual order records yet — order system not connected._")

            lines.append("")
            lines.append("💵 *Deposits*")
            lines.append(f"Total Deposited: `${total_deposited:.2f}` ({len(my_tx)} deposits)")
            if my_tx:
                for t in my_tx[-10:]:
                    lines.append(f"🧾 `{t['hash']}` | 💵 `${t['amount']:.2f}` | 🕒 {t['time']}")
            else:
                lines.append("_No deposits yet._")

            lines.append("")
            lines.append("🤝 *Affiliate*")
            lines.append(f"Total Referred: {len(user.get('referrals', []))}")
            lines.append(f"Total Earned: `${user.get('total_earned', 0):.2f}`")
            if user.get("referrals"):
                ref_list = ", ".join(str(r) for r in user["referrals"][:30])
                lines.append(f"Referred Users: {ref_list}")

            await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)

        elif action == "broadcast":
            users = all_users()
            await update.message.reply_text(f"📢 Broadcasting to {len(users)} users...")
            sent, failed = 0, 0
            for uid in users.keys():
                try:
                    await context.bot.send_message(chat_id=int(uid), text=text_in)
                    sent += 1
                except Exception:
                    failed += 1
            await update.message.reply_text(
                f"✅ *Broadcast complete.*\nSent: {sent}\nFailed: {failed}",
                parse_mode=ParseMode.MARKDOWN,
            )

        elif action == "search_provider":
            matches = await search_provider_services(text_in)
            if not matches:
                await update.message.reply_text("🔍 No matching services found. Try a different keyword.")
            else:
                lines = [f"🔍 *Search Results for* `{text_in}`\n"]
                for s in matches:
                    lines.append(
                        f"🆔 `{s.get('service')}` | {s.get('name', '-')}\n"
                        f"📂 {s.get('category', '-')} | 💵 cost `${float(s.get('rate', 0)):.3f}`/1k "
                        f"| min {s.get('min', '-')}-max {s.get('max', '-')}\n"
                    )
                lines.append("_Use the Service ID above with ➕ Add Service._")
                await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)

        elif action == "add_service_id":
            svc = await find_provider_service(text_in)
            if not svc:
                await update.message.reply_text(
                    "⚠️ That Service ID wasn't found in the provider catalog. "
                    "Use 🔍 Search Provider Catalog to find the correct ID, then try again."
                )
            else:
                context.user_data["new_service"] = {
                    "provider_service_id": text_in,
                    "name": svc.get("name", "Service"),
                    "min": int(float(svc.get("min", 1))),
                    "max": int(float(svc.get("max", 1))),
                    "provider_cost": float(svc.get("rate", 0)),
                }
                context.user_data["admin_action"] = "add_service_price"
                await update.message.reply_text(
                    f"✅ Found: *{svc.get('name')}*\n"
                    f"Provider cost: `${float(svc.get('rate', 0)):.3f}`/1k | "
                    f"min {svc.get('min')}-max {svc.get('max')}\n\n"
                    "💵 Now send the *price* YOU want to charge per 1000 in your bot (e.g. `1.50`).",
                    parse_mode=ParseMode.MARKDOWN,
                )

        elif action == "add_service_price":
            new_service = context.user_data.get("new_service")
            if not new_service:
                await update.message.reply_text("⚠️ Something went wrong. Please start over with ➕ Add Service.")
            else:
                price = float(text_in)
                new_service["price"] = price
                context.user_data["new_service"] = new_service
                context.user_data["admin_action"] = "add_service_platform"
                platform_list = ", ".join(PLATFORM_KEYS)
                await update.message.reply_text(
                    f"📂 Which menu should this show under? Reply with one of:\n`{platform_list}`",
                    parse_mode=ParseMode.MARKDOWN,
                )

        elif action == "add_service_platform":
            new_service = context.user_data.get("new_service")
            if not new_service:
                await update.message.reply_text("⚠️ Something went wrong. Please start over with ➕ Add Service.")
            else:
                platform = text_in.strip().lower()
                if platform not in PLATFORM_KEYS:
                    context.user_data["admin_action"] = "add_service_platform"
                    platform_list = ", ".join(PLATFORM_KEYS)
                    await update.message.reply_text(
                        f"⚠️ Please reply with exactly one of:\n`{platform_list}`",
                        parse_mode=ParseMode.MARKDOWN,
                    )
                else:
                    custom_id = add_custom_service(
                        provider_service_id=new_service["provider_service_id"],
                        name=new_service["name"],
                        price=new_service["price"],
                        platform=platform,
                        min_qty=new_service["min"],
                        max_qty=new_service["max"],
                    )
                    context.user_data.pop("new_service", None)
                    await update.message.reply_text(
                        f"✅ *Service Added!*\n\n"
                        f"🆔 `{custom_id}` | {new_service['name']}\n"
                        f"📂 {PLATFORM_LABELS.get(platform, platform)} | 💵 `${new_service['price']:.2f}`/1k\n\n"
                        "It will now appear in /services for users.",
                        parse_mode=ParseMode.MARKDOWN,
                    )

        elif action == "remove_service":
            removed = remove_custom_service(text_in)
            if removed:
                await update.message.reply_text(f"🗑 Service `{text_in}` removed.", parse_mode=ParseMode.MARKDOWN)
            else:
                await update.message.reply_text(f"⚠️ No service found with ID `{text_in}`.", parse_mode=ParseMode.MARKDOWN)

    except Exception as e:
        await update.message.reply_text(f"⚠️ Error: {e}\nPlease try again from /adminpanel.")


# ===================== GRAM AUTOPAY: deposit amount entry =====================
async def deposit_amount_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles a user's reply after tapping GRAM AUTOPAY — they type the USD amount
    they want to deposit, and the bot shows them the exact TON amount + memo to send."""
    text_in = update.message.text.strip()

    try:
        usd_amount = float(text_in)
    except ValueError:
        await update.message.reply_text(
            "⚠️ Please enter a valid number, e.g. `0.50` or `1` or `5`.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    if usd_amount < MIN_DEPOSIT_USD:
        await update.message.reply_text(
            f"⚠️ Minimum deposit is *${MIN_DEPOSIT_USD:.2f}*. Please enter a higher amount.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    try:
        price = await get_ton_price_usd()
    except Exception:
        await update.message.reply_text(
            "⚠️ Couldn't fetch the live TON price right now. Please try again in a moment."
        )
        return  # keep awaiting_deposit_amount True so they can retry

    context.user_data["awaiting_deposit_amount"] = False
    ton_needed = usd_amount / price
    context.user_data["pending_deposit"] = {"usd": usd_amount, "ton": ton_needed}

    user_id = update.effective_user.id
    text = (
        "💸 *GRAM Autopay Deposit*\n\n"
        f"💵 *Amount:* `${usd_amount:.2f}`\n"
        f"💎 *Send exactly:* `{ton_needed:.4f} TON`\n\n"
        "📥 *Address:*\n"
        f"`{GRAM_WALLET_ADDRESS}`\n\n"
        "📝 *Memo / Comment (REQUIRED):*\n"
        f"`{user_id}`\n\n"
        "⚠️ Send the *exact TON amount* above with the memo included — sending less "
        "won't be credited automatically.\n\n"
        "✅ After sending, tap *Verify Payment* below."
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Verify Payment", callback_data="verify_gram")],
        [
            InlineKeyboardButton("🔙 Back", callback_data="deposit"),
            InlineKeyboardButton("🔝 Main Menu", callback_data="back_to_menu"),
        ],
    ])
    await update.message.reply_text(text=text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)


# ===================== SERVICE ORDERING: link + quantity entry =====================
async def order_link_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the link the user sends after picking a service."""
    link = update.message.text.strip()
    pending = context.user_data.get("pending_order")

    if not pending:
        context.user_data["awaiting_order_link"] = False
        await update.message.reply_text("⚠️ No order in progress. Please pick a service again from the menu.")
        return

    if not (link.startswith("http://") or link.startswith("https://")):
        await update.message.reply_text(
            "⚠️ That doesn't look like a valid link. Please send a link starting with http:// or https://"
        )
        return

    context.user_data["pending_order"]["link"] = link
    context.user_data["awaiting_order_link"] = False
    context.user_data["awaiting_order_quantity"] = True

    await update.message.reply_text(
        f"🔢 *Enter Quantity*\n\n📉 Min: {pending['min']}  📈 Max: {pending['max']}",
        parse_mode=ParseMode.MARKDOWN,
    )


async def order_quantity_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the quantity the user sends, then places the order with the provider."""
    pending = context.user_data.get("pending_order")
    if not pending or "link" not in pending:
        context.user_data["awaiting_order_quantity"] = False
        await update.message.reply_text("⚠️ No order in progress. Please pick a service again from the menu.")
        return

    text_in = update.message.text.strip()
    try:
        quantity = int(text_in)
    except ValueError:
        await update.message.reply_text("⚠️ Please enter a valid whole number for quantity.")
        return

    if quantity < pending["min"] or quantity > pending["max"]:
        await update.message.reply_text(
            f"⚠️ Quantity must be between {pending['min']} and {pending['max']}. Please try again."
        )
        return

    price = round((pending["price"] / 1000) * quantity, 3)
    user_id = update.effective_user.id
    user = get_user(user_id)

    if user["balance"] < price:
        shortfall = round(price - user["balance"], 2)
        await update.message.reply_text(
            f"⚠️ *Insufficient balance.*\n\nThis order costs `${price:.3f}` but your balance is "
            f"`${user['balance']:.3f}`. Please deposit at least `${shortfall:.2f}` more.",
            parse_mode=ParseMode.MARKDOWN,
        )
        context.user_data["awaiting_order_quantity"] = False
        context.user_data.pop("pending_order", None)
        return

    try:
        result = await place_provider_order(pending["provider_service_id"], pending["link"], quantity)
    except Exception:
        result = {"error": "Could not reach the provider. Please try again shortly."}

    context.user_data["awaiting_order_quantity"] = False
    context.user_data.pop("pending_order", None)

    if "order" in result:
        order_id = result["order"]
        user["balance"] -= price
        user["orders_placed"] += 1
        user["total_spending"] += price
        user.setdefault("orders", []).append({
            "id": order_id,
            "service": pending["name"],
            "quantity": quantity,
            "price": price,
            "status": "Pending",
            "link": pending["link"],
            "date": time.strftime("%Y-%m-%d %H:%M:%S"),
        })
        update_user(user_id, user)

        referrer_id = user.get("referred_by")
        if referrer_id:
            commission = round(price * COMMISSION_RATE, 4)
            ref_user = get_user(referrer_id)
            ref_user["balance"] += commission
            ref_user["total_earned"] += commission
            update_user(referrer_id, ref_user)

        await update.message.reply_text(
            "✅ *Order Placed!*\n\n"
            f"🆔 *Order ID:* `{order_id}`\n"
            f"🛒 *Service:* {pending['name']}\n"
            f"🔢 *Quantity:* {quantity}\n"
            f"💵 *Charged:* `${price:.3f}`\n\n"
            "Track its progress under 📦 *Orders*.",
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        err = result.get("error", "Unknown error from provider.")
        await update.message.reply_text(
            f"❌ *Order failed:* {err}\n\nYour balance was not charged.",
            parse_mode=ParseMode.MARKDOWN,
        )


async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Routes free-text replies: admin actions, deposit-amount entry, or order link/quantity entry."""
    user_id = update.effective_user.id

    if user_id == ADMIN_ID and context.user_data.get("admin_action"):
        await admin_text_input(update, context)
        return

    if context.user_data.get("awaiting_deposit_amount"):
        await deposit_amount_input(update, context)
        return

    if context.user_data.get("awaiting_order_link"):
        await order_link_input(update, context)
        return

    if context.user_data.get("awaiting_order_quantity"):
        await order_quantity_input(update, context)
        return
    # otherwise: not waiting for any text input from this user, ignore silently


# ===================== BAN CHECK (optional global guard) =====================
async def check_banned(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Blocks banned users from using the bot. Returns True if blocked."""
    user_id = update.effective_user.id if update.effective_user else None
    if user_id is None:
        return False
    user = get_user(user_id)
    if user.get("banned"):
        if update.message:
            await update.message.reply_text("🚫 You are banned from using this bot.")
        elif update.callback_query:
            await update.callback_query.answer("🚫 You are banned from using this bot.", show_alert=True)
        return True
    return False


# ===================== MAIN =====================
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("adminpanel", adminpanel))
    app.add_handler(CallbackQueryHandler(route_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_input))

    print("Bot is running... (Ctrl+C to stop)")
    app.run_polling()


if __name__ == "__main__":
    main()
