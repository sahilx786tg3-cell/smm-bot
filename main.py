"""
SMM Panel Telegram Bot
----------------------
This bot shows a welcome message and menu buttons on /start.

Setup:
1) pip install python-telegram-bot --upgrade
2) Put your bot token below in BOT_TOKEN (from BotFather)
3) python smm_bot.py
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
import json
import os

# ===================== STORAGE (simple JSON file based) =====================
DATA_FILE = "wallet_data.json"


def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return {}


def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)


def get_user(user_id):
    data = load_data()
    uid = str(user_id)
    if uid not in data:
        data[uid] = {
            "balance": 0.0,
            "orders_placed": 0,
            "total_spending": 0.0,
            "transactions": [],  # each: {amount, hash, time}
        }
        save_data(data)
    return data[uid]


def update_user(user_id, user_record):
    data = load_data()
    data[str(user_id)] = user_record
    save_data(data)


# ===================== CONFIG =====================
BOT_TOKEN = "8583974530:AAHWMz3Xdn7x3wMXQVOZqCu-trj2EGRPvp0"   # <-- token from BotFather
JOIN_CHANNEL = "@LiteDropX"               # <-- maintenance/update channel
SUPPORT_USERNAME = "@TheNikoLaiii"

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
            InlineKeyboardButton("📊 Order Status", callback_data="order_status"),
        ],
        [
            InlineKeyboardButton("🔗 AFF Program", callback_data="aff_program"),
            InlineKeyboardButton("📑 Help", callback_data="help"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


# ===================== HANDLERS =====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        WELCOME_TEXT,
        reply_markup=main_menu_keyboard(),
        parse_mode=ParseMode.MARKDOWN,
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data

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
        user_id = query.from_user.id
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
        user_id = query.from_user.id
        user = get_user(user_id)
        if not user["transactions"]:
            text = "📜 *Transaction History*\n\nNo transactions yet."
        else:
            lines = ["📜 *Transaction History*\n"]
            for tx in user["transactions"]:
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

    elif data == "order_status":
        text = "📊 *Order Status*\n\n(Enter your Order ID here to check status.)"

    elif data == "aff_program":
        text = "🔗 *AFF Program*\n\n(Your affiliate link and earnings will appear here.)"

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

    # Generic back button so the user can return to the menu
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
    if update.callback_query.data == "back_to_menu":
        await back_to_menu(update, context)
    else:
        await button_handler(update, context)


# ===================== MAIN =====================
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(route_callback))

    print("Bot is running... (Ctrl+C to stop)")
    app.run_polling()


if __name__ == "__main__":
    main()
