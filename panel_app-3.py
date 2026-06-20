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


async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Routes free-text replies: admin actions first, then user deposit-amount entry."""
    user_id = update.effective_user.id

    if user_id == ADMIN_ID and context.user_data.get("admin_action"):
        await admin_text_input(update, context)
        return

    if context.user_data.get("awaiting_deposit_amount"):
        await deposit_amount_input(update, context)
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
