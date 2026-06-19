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
        text = "💳 Wallet\n\n(Yahan hum wallet balance / add funds add karenge.)"
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
