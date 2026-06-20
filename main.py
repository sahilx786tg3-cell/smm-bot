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

# ===================== STORAGE (simple JSON file based) =====================
DATA_FILE = "wallet_data.json"


def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            data = json.load(f)
            data.setdefault("processed_tx", [])
            return data
    return {"users": {}, "transactions": [], "processed_tx": []}


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
        text = (
            "📦 *My Orders*\n\n"
            f"📊 *Status:* No active orders.\n"
            f"🧾 *Total Orders Placed:* {user['orders_placed']}\n"
            f"💸 *Total Spent:* `${user['total_spending']:.2f}`\n\n"
            "(Order details will appear here once the ordering system is connected.)"
        )

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

    elif data.startswith("svc_"):
        platform_names = {
            "svc_telegram": "Telegram",
            "svc_tiktok": "TikTok",
            "svc_twitter": "Twitter (X)",
            "svc_instagram": "Instagram",
            "svc_youtube": "YouTube",
            "svc_facebook": "Facebook",
        }
        platform = platform_names.get(data, "Unknown")
        text = f"📂 *{platform} Services*\n\n(The {platform} services list will be added here.)"

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
        [InlineKeyboardButton("🔍 View User", callback_data="admin_view_user")],
        [InlineKeyboardButton("📦 All Orders", callback_data="admin_all_orders")],
        [
            InlineKeyboardButton("🚫 Ban User", callback_data="admin_ban"),
            InlineKeyboardButton("✅ Unban User", callback_data="admin_unban"),
        ],
        [InlineKeyboardButton("💰 All Deposits", callback_data="admin_all_deposits")],
        [InlineKeyboardButton("👥 All Users Balance", callback_data="admin_all_balances")],
        [InlineKeyboardButton("📋 All Users List", callback_data="admin_users_list")
