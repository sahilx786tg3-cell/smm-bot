"""
SMM Panel Telegram Bot
----------------------
Yeh bot /start command pe ek welcome message aur menu buttons dikhata hai,
jaisa tumne image mein dikhaya tha.

Setup:
1) pip install python-telegram-bot --upgrade
2) Apna bot token niche BOT_TOKEN mein daalo (BotFather se milta hai)
3) python smm_bot.py
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
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
BOT_TOKEN = "8583974530:AAHWMz3Xdn7x3wMXQVOZqCu-trj2EGRPvp0"   # <-- BotFather se mila token
JOIN_CHANNEL = "@LiteDropX"               # <-- update/maintenance channel

WELCOME_TEXT = (
    "🚀 SMM Panel Menu -- a Social Media Marketing Service provider Telegram bot.\n"
    "At cheapest price on telegram,\n\n"
    f"Join {JOIN_CHANNEL} for Maintenance, Service, Price cost updates!"
)

# ===================== MENU LAYOUT =====================
# Row 1: ek bada button (full width) -> All Media Services
# Row 2: Wallet | Order Status  (chote, half-half)
# Row 3: AFF Program | Help     (chote, half-half)
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
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data

    if data == "services":
        text = "🛒 Pick a Service:"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📂 Telegram Services", callback_data="svc_telegram")],
            [InlineKeyboardButton("📂 TikTok Services", callback_data="svc_tiktok")],
            [InlineKeyboardButton("📂 Twitter (X) Services", callback_data="svc_twitter")],
            [InlineKeyboardButton("📂 Instagram Services", callback_data="svc_instagram")],
            [InlineKeyboardButton("📂 YouTube Services", callback_data="svc_youtube")],
            [InlineKeyboardButton("📂 Facebook Services", callback_data="svc_facebook")],
            [InlineKeyboardButton("🔝 Main Menu", callback_data="back_to_menu")],
        ])
        await query.edit_message_text(text=text, reply_markup=kb)
        return
    elif data == "wallet":
        user_id = query.from_user.id
        user = get_user(user_id)
        text = (
            "👝 Your Wallet Overview\n\n"
            f"💎 Balance: ${user['balance']:.3f}\n"
            f"🆔 User ID: {user_id}\n\n"
            f"📦 Orders Placed: {user['orders_placed']}\n"
            f"💸 Total Spending: ${user['total_spending']:.2f}"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📥 Deposit", callback_data="deposit")],
            [InlineKeyboardButton("📜 Transaction History", callback_data="tx_history")],
            [InlineKeyboardButton("🔝 Main Menu", callback_data="back_to_menu")],
        ])
        await query.edit_message_text(text=text, reply_markup=kb)
        return
    elif data == "deposit":
        text = (
            "➕ Add Funds to Your 💳 Wallet!\n\n"
            "💰 Automatic Deposit via GRAM Only\n"
            "⚡ Instant & Secure Processing\n\n"
            "📩 Prefer Binance Pay or Other Methods?\n"
            "Contact @TheNikoLaiii\n\n"
            "🚀 Fast, simple & reliable top-up system"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("💸 GRAM AUTOPAY", callback_data="gram_autopay")],
            [
                InlineKeyboardButton("🔙 Back", callback_data="wallet"),
                InlineKeyboardButton("🔝 Main Menu", callback_data="back_to_menu"),
            ],
        ])
        await query.edit_message_text(text=text, reply_markup=kb)
        return
    elif data == "tx_history":
        user_id = query.from_user.id
        user = get_user(user_id)
        if not user["transactions"]:
            text = "📜 Transaction History\n\nAbhi tak koi transaction nahi hai."
        else:
            lines = ["📜 Transaction History\n"]
            for tx in user["transactions"]:
                lines.append(
                    f"💰 Amount: ${tx['amount']:.2f}\n"
                    f"🧾 Hash: {tx['hash']}\n"
                    f"🕒 Time: {tx['time']}\n"
                )
            text = "\n".join(lines)
        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🔙 Back", callback_data="wallet"),
                InlineKeyboardButton("🔝 Main Menu", callback_data="back_to_menu"),
            ],
        ])
        await query.edit_message_text(text=text, reply_markup=kb)
        return
    elif data == "gram_autopay":
        text = "💸 GRAM Autopay\n\n(Yahan hum GRAM payment system connect karenge.)"
    elif data == "order_status":
        text = "📊 Order Status\n\n(Yahan hum order ID daal ke status check karenge.)"
    elif data == "aff_program":
        text = "🔗 AFF Program\n\n(Yahan affiliate link / earnings ayega.)"
    elif data == "help":
        text = "📑 Help\n\n(Yahan support / FAQ ayega.)"
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
        text = f"📂 {platform} Services\n\n(Yahan hum {platform} ki services list add karenge.)"
    else:
        text = "Unknown option."

    # Back button so user wapas menu pe ja sake
    back_kb = InlineKeyboardMarkup(
        [[InlineKeyboardButton("⬅️ Back", callback_data="back_to_menu")]]
    )
    await query.edit_message_text(text=text, reply_markup=back_kb)


async def back_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(text=WELCOME_TEXT, reply_markup=main_menu_keyboard())


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

    print("Bot chal raha hai... (Ctrl+C se band karo)")
    app.run_polling()


if __name__ == "__main__":
    main()
