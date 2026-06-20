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

# ===================== CONFIG =====================
BOT_TOKEN = "8583974530:AAHWMz3Xdn7x3wMXQVOZqCu-trj2EGRPvp0"   # <-- token from BotFather
JOIN_CHANNEL = "@LiteDropX"
SUPPORT_USERNAME = "@TheNikoLaiii"
BOT_USERNAME = "SMMPanelAiRobot"   # <-- change this to your bot's actual username (without @)
ADMIN_ID = 6520878121
COMMISSION_RATE = 0.05  # 5%

# ===================== STORAGE (simple JSON file based) =====================
DATA_FILE = "wallet_data.json"


def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return {"users": {}, "transactions": []}


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
            "total_spending": 0.0,
            "banned": False,
            "referred_by": None,
            "referrals": [],
            "total_earned": 0.0,
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
        text = "💸 *GRAM Autopay*\n\n(GRAM payment system will be connected here.)"

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
        [InlineKeyboardButton("📦 All Orders", callback_data="admin_all_orders")],
        [
            InlineKeyboardButton("🚫 Ban User", callback_data="admin_ban"),
            InlineKeyboardButton("✅ Unban User", callback_data="admin_unban"),
        ],
        [InlineKeyboardButton("💰 All Deposits", callback_data="admin_all_deposits")],
        [InlineKeyboardButton("👥 All Users Balance", callback_data="admin_all_balances")],
        [InlineKeyboardButton("🧾 Recent Transactions (30)", callback_data="admin_recent_tx")],
        [
            InlineKeyboardButton("➕ Add Balance", callback_data="admin_add_balance"),
            InlineKeyboardButton("➖ Subtract Balance", callback_data="admin_sub_balance"),
        ],
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

    except Exception as e:
        await update.message.reply_text(f"⚠️ Error: {e}\nPlease try again from /adminpanel.")


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
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, admin_text_input))

    print("Bot is running... (Ctrl+C to stop)")
    app.run_polling()


if __name__ == "__main__":
    main()
