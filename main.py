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
import asyncio
import json
import os
import time
import uuid
import base64
import secrets
import string
import httpx


def ton_hash_to_hex(hash_str: str) -> str:
    """Converts a TON base64 transaction hash (from TonCenter) into the hex format
    that Tonviewer.com / Tonscan.org use, so admins/users can paste it directly."""
    if not hash_str:
        return hash_str
    try:
        return base64.b64decode(hash_str).hex()
    except Exception:
        return hash_str  # already hex, or some other format — leave as-is


def get_explorer_link(chain: str, tx_hash: str) -> str:
    """Builds a clickable Tonviewer URL for a GRAM (exTON) transaction hash."""
    return f"https://tonviewer.com/transaction/{ton_hash_to_hex(tx_hash)}"


def guess_chain_from_label(label: str) -> str:
    """Kept for compatibility with old transaction records — only TON exists now."""
    return "ton"

# ===================== CONFIG =====================
BOT_TOKEN = "8583974530:AAGPWZppMQqVaqofQO4U68yPL_D_QkjhHx4"   # <-- token from BotFather
JOIN_CHANNEL = "@LiteDropX"
SUPPORT_USERNAME = "@TheNikoLaiii"
BOT_USERNAME = "SMMPanelAiRobot"   # <-- change this to your bot's actual username (without @)
ADMIN_ID = 6520878121
COMMISSION_RATE = 0.05  # 5%
DATA_FILE_VERSION = 2  # Increment when data structure changes (for auto-migration)

# ---- GRAM (exTON) Autopay config — the ONLY supported deposit method ----
GRAM_WALLET_ADDRESS = "UQB4rr2U6zTQCNq-jENXpmfQjUCe6cSpiy2tfSeT9JNyo3Rj"   # TON wallet (GRAM)

TONCENTER_API = "https://toncenter.com/api/v2/getTransactions"
# Free TonCenter API key (get one in seconds from https://t.me/tonapibot) — WITHOUT
# this, TonCenter rate-limits to ~1 request/sec and can lag behind the real chain
# state, which is the #1 cause of "No new deposit found yet" right after a real
# payment. Leave as "" to use the slower/unauthenticated public endpoint.
TONCENTER_API_KEY = "6596a286e2ea6132169fa2e18fe092678a9fc91a50fa91eb4d30b5c59f8f4bc0"
COINGECKO_API = "https://api.coingecko.com/api/v3/simple/price"

MIN_DEPOSIT_USD = 0.1

# Only one payment method exists: GRAM (exTON). Everything in the deposit
# menu, verify_deposit, and admin tools reads from this dict.
PAYMENT_METHODS = {
    "ton_gram": {
        "label": "💎 GRAM (exTON)", "symbol": "GRAM", "chain": "ton", "asset": "native",
        "binance_symbol": "TONUSDT", "coingecko_id": "the-open-network",
        "address": GRAM_WALLET_ADDRESS, "uses_memo": True,
    },
}


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
# IMPORTANT: this path must point inside a Railway Volume (mount path /data),
# otherwise the file lives on ephemeral storage and gets wiped on every
# redeploy — which is why old/processed transactions used to get re-credited.
DATA_DIR = "/data"
DATA_FILE = os.path.join(DATA_DIR, "wallet_data.json")
DATA_DIR_WRITABLE = None  # set on first check; None = not checked yet

import threading
_DATA_LOCK = threading.RLock()  # serializes load+modify+save so two near-simultaneous
                                 # requests can't overwrite each other's changes


def _ensure_data_dir():
    global DATA_DIR_WRITABLE
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        # Confirm it's actually writable, not just creatable
        test_path = os.path.join(DATA_DIR, ".write_test")
        with open(test_path, "w") as f:
            f.write("ok")
        os.remove(test_path)
        DATA_DIR_WRITABLE = True
    except Exception:
        DATA_DIR_WRITABLE = False  # /data isn't writable — likely no Volume mounted yet


def load_data():
    _ensure_data_dir()
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, "r") as f:
                data = json.load(f)
                
                # Auto-migrate if data version is older than code version
                stored_version = data.get("_version", 1)
                if stored_version < DATA_FILE_VERSION:
                    print(f"📊 Upgrading data: v{stored_version} → v{DATA_FILE_VERSION}")
                    data = migrate_data_v1_to_v2(data)
                    data["_version"] = DATA_FILE_VERSION
                    save_data(data)
                
                data.setdefault("processed_tx", [])
                data.setdefault("custom_services", [])
                data.setdefault("custom_texts", {})
                data.setdefault("_version", DATA_FILE_VERSION)
                return data
    except Exception as e:
        print(f"⚠️ load_data failed: {e}")
    return {
        "users": {}, 
        "transactions": [], 
        "processed_tx": [], 
        "custom_services": [], 
        "custom_texts": {},
        "_version": DATA_FILE_VERSION
    }


def save_data(data):
    _ensure_data_dir()
    try:
        with open(DATA_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        # Never let a failed save crash the bot — just log it.
        # If you keep seeing this in the Railway logs, it means /data has
        # no persistent Volume attached (Settings → Volumes → mount at /data).
        print(f"⚠️ save_data FAILED — your changes were NOT saved to disk: {e}")


def migrate_data_v1_to_v2(data):
    """Auto-migration: v1 → v2. Adds 'chain' field to old transactions.
    This ensures old deposits work with new multi-chain system. Data is never deleted."""
    print("🔄 Running migration v1 → v2...")
    migrated_count = 0
    for tx in data.get("transactions", []):
        if "chain" not in tx:
            # Infer chain from old label field
            label = tx.get("label", "")
            tx["chain"] = guess_chain_from_label(label)
            migrated_count += 1
    if migrated_count > 0:
        print(f"  ✅ Migrated {migrated_count} transactions with chain field")
    return data


def get_user(user_id):
    with _DATA_LOCK:
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
    with _DATA_LOCK:
        data = load_data()
        data["users"][str(user_id)] = user_record
        save_data(data)


def add_global_transaction(user_id, amount, tx_hash):
    with _DATA_LOCK:
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


async def get_provider_services(force_refresh: bool = False):
    """
    Fetches (and caches) the full services list from the provider.
    Returns (services_list, error_message). error_message is None on success.
    """
    now = time.time()
    if not force_refresh and _services_cache["data"] and (now - _services_cache["fetched_at"] < SERVICES_CACHE_SECONDS):
        return _services_cache["data"], None

    try:
        result = await provider_request({"action": "services"})
    except Exception as e:
        return _services_cache["data"], f"Couldn't reach the provider: {e}"

    if isinstance(result, list):
        _services_cache["data"] = result
        _services_cache["fetched_at"] = now
        return result, None
    if isinstance(result, dict) and "error" in result:
        return _services_cache["data"], f"Provider returned an error: {result['error']}"
    return _services_cache["data"], f"Unexpected response format: {str(result)[:300]}"


async def search_provider_services(keyword: str, limit: int = 15):
    """Admin tool: search the full provider catalog by keyword (matches name or category)."""
    services, err = await get_provider_services()
    if err:
        return [], err
    kw = keyword.lower()
    matches = [
        s for s in services
        if kw in str(s.get("name", "")).lower() or kw in str(s.get("category", "")).lower()
    ]
    return matches[:limit], None


async def find_provider_service(service_id: str):
    """Admin tool: look up one provider service's details by its ID."""
    services, err = await get_provider_services()
    if err:
        return None, err
    for s in services:
        if str(s.get("service")) == str(service_id):
            return s, None
    return None, f"Not found among {len(services)} services fetched from provider."


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


def edit_custom_service_field(custom_id: str, field: str, value) -> bool:
    """Edits one field (e.g. 'name' or 'price') of an existing custom service."""
    data = load_data()
    services = data.get("custom_services", [])
    for s in services:
        if s["id"] == custom_id:
            s[field] = value
            save_data(data)
            return True
    return False


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


# ===================== AUTOPAY (multi-chain blockchain verification) =====================
_price_cache = {}  # {coingecko_id: (price, fetched_at)}
PRICE_CACHE_SECONDS = 60


BINANCE_PRICE_API = "https://api.binance.com/api/v3/ticker/price"


async def get_token_price_usd(method: dict) -> float:
    """
    Fetches (and briefly caches) a token's USD price.
    - USDT is hardcoded to $1.00 (no need to hit any API for a stablecoin —
      this also removes the odd extra decimals like 0.100096).
    - Everything else tries Binance's public ticker first (no API key,
      generous rate limits, very reliable), then falls back to CoinGecko
      if Binance is unreachable for some reason.
    """
    coingecko_id = method["coingecko_id"]
    cache_key = coingecko_id

    if coingecko_id == "tether":
        return 1.0

    now = time.time()
    cached = _price_cache.get(cache_key)
    if cached and now - cached[1] < PRICE_CACHE_SECONDS:
        return cached[0]

    binance_symbol = method.get("binance_symbol")
    binance_symbols_to_try = [binance_symbol] if binance_symbol else []
    if binance_symbol == "POLUSDT":
        binance_symbols_to_try.append("MATICUSDT")  # older ticker, in case POLUSDT isn't listed yet

    last_error = None

    # 1) Try CoinGecko first (Binance's public API is blocked from many cloud/datacenter
    #    IPs — including Railway — which used to make every deposit wait ~30s before
    #    falling back). Single attempt, short timeout = fail fast instead of hanging.
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(
                COINGECKO_API, params={"ids": coingecko_id, "vs_currencies": "usd"}
            )
            resp.raise_for_status()
            data = resp.json()
            price = float(data[coingecko_id]["usd"])
            _price_cache[cache_key] = (price, now)
            return price
    except Exception as e:
        last_error = e

    # 2) Fall back to Binance (single attempt per symbol, short timeout)
    for sym in binance_symbols_to_try:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(BINANCE_PRICE_API, params={"symbol": sym})
                resp.raise_for_status()
                data = resp.json()
                price = float(data["price"])
                _price_cache[cache_key] = (price, now)
                return price
        except Exception as e:
            last_error = e

    # 3) All sources failed — serve stale cached price rather than blocking the deposit
    if cached:
        return cached[0]
    raise last_error


_DEPOSIT_CODE_ALPHABET = string.ascii_uppercase + string.digits


def generate_unique_deposit_code(length: int = 8) -> str:
    """Generates a fresh random alphanumeric memo code for a TON deposit (GRAM native
    or GRAM USDT) and permanently reserves it (persisted to disk) so it can never be
    issued or matched again. Replaces the old scheme of using the Telegram user_id as
    the memo, which stayed identical across every deposit a user ever made — meaning an
    old, already-credited transaction (still sitting in the wallet's recent history)
    could be re-matched against a brand-new deposit request, e.g. after a redeploy that
    wiped the processed-tx list."""
    with _DATA_LOCK:
        data = load_data()
        used = set(data.setdefault("used_deposit_codes", []))
        while True:
            code = "".join(secrets.choice(_DEPOSIT_CODE_ALPHABET) for _ in range(length))
            if code in used:
                continue
            used.add(code)
            data["used_deposit_codes"] = list(used)
            save_data(data)
            return code


# ---- TON (native GRAM) ----
async def fetch_ton_native_transactions(limit: int = 100):
    """Fetches recent incoming transactions for the GRAM wallet from TonCenter.
    Retries a couple of times on transient errors (timeouts, 429 rate-limit, etc.)
    instead of giving up on the very first hiccup — this was the main cause of
    deposits showing 'No new deposit found yet' even after a correct, on-chain payment."""
    params = {"address": GRAM_WALLET_ADDRESS, "limit": limit, "archival": "true"}
    headers = {}
    if TONCENTER_API_KEY:
        params["api_key"] = TONCENTER_API_KEY        # TonCenter v2 documented method
        headers["X-API-Key"] = TONCENTER_API_KEY      # also send as header, just in case

    last_error = None
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(TONCENTER_API, params=params, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                if not data.get("ok"):
                    print(f"⚠️ TonCenter returned ok=false: {data.get('error', data)}")
                    return []
                return data.get("result", [])
        except Exception as e:
            last_error = e
            if attempt < 2:
                await asyncio.sleep(2)  # brief backoff, then retry — handles transient 429s/timeouts
    print(f"⚠️ TonCenter fetch failed after retries: {last_error}")
    return []


def extract_ton_comment(in_msg: dict) -> str:
    if not in_msg:
        return ""
    msg = in_msg.get("message")
    if msg:
        return msg.strip()
    msg_data = in_msg.get("msg_data", {}) or {}
    if msg_data.get("@type") == "msg.dataText":
        return (msg_data.get("text") or "").strip()
    return ""


async def verify_ton_native_deposit(user_id: int, min_amount: float = 0.0, memo_code: str = None, expected_usd: float = None):
    """Checks for a new GRAM(TON) deposit whose memo matches the one-time code issued
    for THIS specific deposit request. Returns (usd, token_amt, tx_hash) or None."""
    if not memo_code:
        return None
    transactions = await fetch_ton_native_transactions()

    for tx in transactions:
        in_msg = tx.get("in_msg", {}) or {}
        if extract_ton_comment(in_msg) != memo_code:
            continue
        value_nanotons = int(in_msg.get("value", 0) or 0)
        if value_nanotons <= 0:
            continue
        tx_hash = tx.get("transaction_id", {}).get("hash", "")
        if not tx_hash:
            continue
        token_amount = value_nanotons / 1e9
        if min_amount and token_amount + 1e-9 < min_amount:
            continue
        # Claim the hash atomically. Nothing after this point may `await` and risk
        # failing — a failure after the claim would mark the tx "used" forever
        # without ever crediting the user, silently losing their deposit. That's why
        # we credit the USD amount the user already locked in at request time
        # (expected_usd) instead of re-fetching a live price here.
        if not _claim_tx_hash(tx_hash):
            continue
        usd_amount = round(expected_usd, 3) if expected_usd is not None else round(token_amount, 3)
        _finalize_deposit(user_id, usd_amount, tx_hash, "GRAM (exTON) Autopay", token_amount)
        return usd_amount, token_amount, tx_hash
    return None


def _claim_tx_hash(tx_hash: str) -> bool:
    """Atomically checks whether tx_hash has already been claimed/processed; if not,
    marks it processed immediately and returns True. Must be called BEFORE any
    `await` in the calling verify_* function so two near-simultaneous verification
    requests (double-tapping "Verify"/"Try Again", or two concurrent polls) can never
    both pass the check and credit the same blockchain transaction twice."""
    with _DATA_LOCK:
        data = load_data()
        processed = data.setdefault("processed_tx", [])
        if tx_hash in processed:
            return False
        processed.append(tx_hash)
        save_data(data)
        return True


def _finalize_deposit(user_id: int, usd_amount: float, tx_hash: str, label: str, token_amount: float):
    """Credits the user's wallet and records the transaction. Only call this after
    _claim_tx_hash(tx_hash) has returned True for this tx_hash."""
    user = get_user(user_id)
    user["balance"] += usd_amount
    update_user(user_id, user)

    data = load_data()
    data["transactions"].append({
        "user_id": user_id,
        "amount": usd_amount,
        "hash": tx_hash,
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "type": label,
        "token_amount": token_amount,
    })
    save_data(data)


async def verify_deposit(method_key: str, user_id: int, expected_amount: float, memo_code: str = None, expected_usd: float = None):
    """Only GRAM (exTON) is supported, so this always checks the TON chain."""
    return await verify_ton_native_deposit(user_id, min_amount=expected_amount, memo_code=memo_code, expected_usd=expected_usd)


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


# ===================== EDITABLE TEXTS (admin can change these from /adminpanel) =====================
DEFAULT_TEXTS = {
    "welcome": (
        "🚀 *SMM Panel Menu* -- a Social Media Marketing Service provider Telegram bot.\n"
        "At cheapest price on telegram,\n\n"
        f"Join {JOIN_CHANNEL} for Maintenance, Service, Price cost updates!"
    ),
    "help": (
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
    ),
    "btn_services": "🚀 All Media Services",
    "btn_wallet": "💳 Wallet",
    "btn_orders": "📦 Orders",
    "btn_affiliate": "🤝 Affiliate Program",
    "btn_help": "📑 Help",
}

# Friendly names shown to admin when picking which text to edit
TEXT_LABELS = {
    "welcome": "Welcome Message (/start)",
    "help": "Help Message",
    "btn_services": "Main Menu Button: All Media Services",
    "btn_wallet": "Main Menu Button: Wallet",
    "btn_orders": "Main Menu Button: Orders",
    "btn_affiliate": "Main Menu Button: Affiliate Program",
    "btn_help": "Main Menu Button: Help",
}


def get_text(key: str) -> str:
    data = load_data()
    custom = data.get("custom_texts", {})
    return custom.get(key, DEFAULT_TEXTS.get(key, ""))


def set_text(key: str, value: str):
    data = load_data()
    data.setdefault("custom_texts", {})
    data["custom_texts"][key] = value
    save_data(data)


def reset_text(key: str):
    data = load_data()
    if "custom_texts" in data and key in data["custom_texts"]:
        del data["custom_texts"][key]
        save_data(data)


# ===================== MENU LAYOUT =====================
def main_menu_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton(get_text("btn_services"), callback_data="services")],
        [
            InlineKeyboardButton(get_text("btn_wallet"), callback_data="wallet"),
            InlineKeyboardButton(get_text("btn_orders"), callback_data="orders"),
        ],
        [
            InlineKeyboardButton(get_text("btn_affiliate"), callback_data="aff_program"),
            InlineKeyboardButton(get_text("btn_help"), callback_data="help"),
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
        get_text("welcome"),
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
        context.user_data.pop("selected_payment_method", None)
        context.user_data.pop("pending_deposit", None)
        text = (
            "➕ *Add Funds to Your* 💳 *Wallet!*\n\n"
            "⚡ Instant & Secure Automatic Processing\n\n"
            "📩 Prefer Binance Pay or Other Methods?\n"
            f"Contact {SUPPORT_USERNAME}\n\n"
            "Choose a network below:"
        )
        rows = [[InlineKeyboardButton(m["label"], callback_data=f"paymethod_{key}")] for key, m in PAYMENT_METHODS.items()]
        rows.append([
            InlineKeyboardButton("🔙 Back", callback_data="wallet"),
            InlineKeyboardButton("🔝 Main Menu", callback_data="back_to_menu"),
        ])
        kb = InlineKeyboardMarkup(rows)
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
                chain = guess_chain_from_label(tx.get("type", ""))
                link = get_explorer_link(chain, tx["hash"])
                lines.append(
                    f"💰 *Amount:* `${tx['amount']:.2f}`\n"
                    f"🧾 *Transaction:* [View on Explorer]({link})\n"
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

    elif data.startswith("paymethod_"):
        method_key = data[len("paymethod_"):]
        if method_key not in PAYMENT_METHODS:
            text = "⚠️ Unknown payment method."
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="deposit")]])
            await query.edit_message_text(text=text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
            return
        context.user_data["selected_payment_method"] = method_key
        context.user_data["awaiting_deposit_amount"] = True
        method = PAYMENT_METHODS[method_key]
        text = (
            f"💰 *Enter Deposit Amount (USD)* — {method['label']}\n\n"
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

    elif data == "verify_payment":
        await query.edit_message_text("🔍 Checking the blockchain for your deposit, please wait...")
        pending = context.user_data.get("pending_deposit")

        if not pending:
            text = "⚠️ No deposit in progress. Please start again from 📥 Deposit."
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="deposit")]])
            await query.edit_message_text(text=text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
            return

        method = PAYMENT_METHODS[pending["method_key"]]
        result = None
        error_msg = None
        try:
            result = await verify_deposit(pending["method_key"], user_id, pending["token"], pending.get("code"), pending.get("usd"))
        except Exception as e:
            error_msg = str(e)
            print(f"⚠️ verify_deposit error: {e}")

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Try Again", callback_data="verify_payment")],
            [
                InlineKeyboardButton("🔙 Back", callback_data="deposit"),
                InlineKeyboardButton("🔝 Main Menu", callback_data="back_to_menu"),
            ],
        ])

        if result:
            usd_amount, token_amount, tx_hash = result
            context.user_data.pop("pending_deposit", None)
            explorer_url = get_explorer_link(method["chain"], tx_hash)
            text = (
                "✅ *Deposit Confirmed!*\n\n"
                f"💎 *Received:* `{token_amount:.4f} {method['symbol']}`\n"
                f"💵 *Credited:* `${usd_amount:.3f}`\n"
                f"🧾 *Transaction:* [View on Explorer]({explorer_url})\n\n"
                "Your wallet balance has been updated."
            )
        else:
            if method["uses_memo"]:
                checklist = (
                    "1️⃣ Sent to the correct address\n"
                    f"2️⃣ Sent the exact amount requested (`{pending['token']:.4f} {method['symbol']}`)\n"
                    f"3️⃣ Included the memo `{pending.get('code')}` exactly"
                )
            else:
                checklist = (
                    "1️⃣ Sent to the correct address\n"
                    f"2️⃣ Sent the *exact* amount shown — `{pending['token']:.4f} {method['symbol']}` "
                    "(every decimal matters, this network has no memo field)"
                )
            text = (
                "⏳ *No new deposit found yet.*\n\n"
                f"Please make sure you:\n{checklist}\n\n"
                "On-chain confirmation can take a minute or two — try again shortly."
            )
            if error_msg:
                text += f"\n\n⚠️ *Debug:* {error_msg}"
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
        text = get_text("help")
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
    context.user_data.pop("selected_payment_method", None)
    context.user_data["awaiting_order_link"] = False
    context.user_data["awaiting_order_quantity"] = False
    context.user_data.pop("pending_order", None)
    await query.edit_message_text(
        text=get_text("welcome"),
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
        [InlineKeyboardButton("🩺 Test Provider Connection", callback_data="admin_test_provider")],
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
        [InlineKeyboardButton("✏️ Edit Texts", callback_data="admin_edit_texts")],
        [InlineKeyboardButton("📝 Edit Service Name", callback_data="admin_edit_service_name")],
        [InlineKeyboardButton("💾 Check Storage/Volume", callback_data="admin_check_storage")],
        [InlineKeyboardButton("🐞 Debug Saved Data", callback_data="admin_debug_data")],
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

    elif data == "admin_edit_texts":
        lines = ["✏️ *Edit Texts*\n\nTap a text below to edit it:"]
        kb_rows = []
        for key, label in TEXT_LABELS.items():
            kb_rows.append([InlineKeyboardButton(label, callback_data=f"admin_edit_text_{key}")])
        kb_rows.append([InlineKeyboardButton("⬅️ Back to Admin Panel", callback_data="admin_back")])
        await query.edit_message_text(
            "\n".join(lines),
            reply_markup=InlineKeyboardMarkup(kb_rows),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    elif data.startswith("admin_edit_text_"):
        key = data.replace("admin_edit_text_", "")
        current = get_text(key)
        label = TEXT_LABELS.get(key, key)
        context.user_data["admin_action"] = f"set_text:{key}"
        text = (
            f"✏️ *Editing:* {label}\n\n"
            f"*Current value:*\n{current}\n\n"
            "👉 Now send the new text you want to use.\n"
            "(Use `*bold*` for bold. Send the word `RESET` to restore the default text instead.)"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Back", callback_data="admin_edit_texts")],
        ])
        await query.edit_message_text(text=text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
        return

    elif data == "admin_debug_data":
        try:
            d = load_data()
            users_count = len(d.get("users", {}))
            tx_count = len(d.get("transactions", []))
            processed_count = len(d.get("processed_tx", []))
            last_processed = d.get("processed_tx", [])[-3:] if d.get("processed_tx") else []
            last_tx = d.get("transactions", [])[-3:] if d.get("transactions") else []

            lines = [
                "🐞 Debug: Raw Saved Data\n",
                f"📁 File path: {DATA_FILE}",
                f"💾 File exists right now: {os.path.exists(DATA_FILE)}\n",
                f"👥 Total users saved: {users_count}",
                f"💰 Total deposit transactions: {tx_count}",
                f"✅ Total processed_tx hashes: {processed_count}\n",
            ]
            if last_processed:
                lines.append("Last 3 processed hashes:")
                for h in last_processed:
                    h_str = str(h)[:30]
                    lines.append(h_str + "...")
            else:
                lines.append("⚠️ processed_tx list is EMPTY.")

            if last_tx:
                lines.append("\nLast 3 deposit records:")
                for t in last_tx:
                    uid = t.get("user_id", "?")
                    amt = t.get("amount", 0)
                    try:
                        amt_str = f"${float(amt):.2f}"
                    except (TypeError, ValueError):
                        amt_str = f"${amt} (non-numeric!)"
                    tm = t.get("time", "?")
                    lines.append(f"🆔 {uid} | {amt_str} | {tm}")

            # No Markdown parse_mode here on purpose: raw hashes/data can contain
            # characters (_, *, `, etc.) that break Telegram's Markdown parser and
            # crash this exact screen with a generic "Something went wrong".
            await query.edit_message_text("\n".join(lines), reply_markup=back_kb)
        except Exception as e:
            await query.edit_message_text(
                f"🐞 Debug handler hit an error itself:\n{type(e).__name__}: {e}",
                reply_markup=back_kb,
            )
        return

    elif data == "admin_check_storage":
        _ensure_data_dir()
        if DATA_DIR_WRITABLE:
            text = (
                "💾 *Storage Check*\n\n"
                "✅ `/data` is writable — your Railway Volume is correctly mounted.\n"
                "Deposits and balances will safely survive redeploys."
            )
        else:
            text = (
                "💾 *Storage Check*\n\n"
                "❌ `/data` is *NOT* writable — no Volume is mounted!\n\n"
                "⚠️ This means every redeploy wipes your data, and old deposits "
                "may get re-credited.\n\n"
                "👉 Fix: Railway → your service → *Settings* → *Volumes* → "
                "*+ New Volume* → mount path `/data` → Save."
            )
        await query.edit_message_text(text=text, reply_markup=back_kb, parse_mode=ParseMode.MARKDOWN)
        return

    elif data == "admin_edit_service_name":
        services = get_custom_services()
        if not services:
            text = "📝 *Edit Service Name*\n\nNo custom services added yet."
        else:
            lines = ["📝 *Edit Service Name*\n\nYour services:\n"]
            for s in services:
                lines.append(f"🆔 `{s['id']}` — {s['name']} ({PLATFORM_LABELS.get(s['platform'], s['platform'])})")
            lines.append("\n👉 Send the *Service ID* (from above) you want to rename.")
            text = "\n".join(lines)
        context.user_data["admin_action"] = "edit_service_name_id"
        await query.edit_message_text(text=text, reply_markup=back_kb, parse_mode=ParseMode.MARKDOWN)
        return

    elif data == "admin_test_provider":
        await query.edit_message_text("🩺 Testing connection to provider...")
        try:
            balance_resp = await get_provider_balance()
        except Exception as e:
            balance_resp = {"error": f"Request failed: {e}"}

        if "error" in balance_resp:
            text = (
                "❌ *Connection Failed*\n\n"
                f"Provider replied: `{balance_resp['error']}`\n\n"
                "This means your *API URL* or *API Key* is likely wrong, or the "
                "provider account isn't active. Double-check both values in the bot's code "
                "(`PROVIDER_API_URL` and `PROVIDER_API_KEY`)."
            )
        elif "balance" in balance_resp:
            text = (
                "✅ *Connection OK!*\n\n"
                f"💰 Provider Balance: `{balance_resp.get('balance')} {balance_resp.get('currency', '')}`\n\n"
                "Your API URL and Key are working correctly."
            )
        else:
            text = f"⚠️ *Unexpected response:*\n`{str(balance_resp)[:300]}`"

        await query.edit_message_text(text=text, reply_markup=back_kb, parse_mode=ParseMode.MARKDOWN)
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
                chain = guess_chain_from_label(tx.get("type", ""))
                link = get_explorer_link(chain, tx["hash"])
                lines.append(
                    f"🆔 `{tx['user_id']}` | 💵 `${tx['amount']:.2f}` | [View Tx]({link}) | 🕒 {tx['time']}"
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
                chain = guess_chain_from_label(tx.get("type", ""))
                link = get_explorer_link(chain, tx["hash"])
                lines.append(
                    f"🆔 `{tx['user_id']}` | 💵 `${tx['amount']:.2f}` | [View Tx]({link}) | 🕒 {tx['time']}"
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
        if action.startswith("set_text:"):
            key = action.split(":", 1)[1]
            label = TEXT_LABELS.get(key, key)
            if text_in.strip().upper() == "RESET":
                reset_text(key)
                await update.message.reply_text(f"♻️ *{label}* reset to default.", parse_mode=ParseMode.MARKDOWN)
            else:
                set_text(key, update.message.text)  # use original (unstripped/markdown intact) text
                await update.message.reply_text(f"✅ *{label}* updated successfully!", parse_mode=ParseMode.MARKDOWN)

        elif action == "ban":
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
            matches, err = await search_provider_services(text_in)
            if err:
                await update.message.reply_text(
                    f"⚠️ *Couldn't search the provider catalog.*\n\n`{err}`\n\n"
                    "This usually means the API URL or Key is wrong, or the provider account "
                    "isn't active yet. Double-check both in the code.",
                    parse_mode=ParseMode.MARKDOWN,
                )
            elif not matches:
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
            svc, err = await find_provider_service(text_in)
            if err and not svc:
                await update.message.reply_text(
                    f"⚠️ *Couldn't add this service.*\n\n`{err}`\n\n"
                    "If this says a connection/API error, your API URL or Key is likely wrong. "
                    "If it says 'Not found among 0 services', the provider returned an empty "
                    "catalog — check the API key is active on 1xpanel.",
                    parse_mode=ParseMode.MARKDOWN,
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

        elif action == "edit_service_name_id":
            svc = find_custom_service(text_in)
            if not svc:
                await update.message.reply_text(f"⚠️ No service found with ID `{text_in}`.", parse_mode=ParseMode.MARKDOWN)
            else:
                context.user_data["edit_service_id"] = text_in
                context.user_data["admin_action"] = "edit_service_name_value"
                await update.message.reply_text(
                    f"✏️ Current name: *{svc['name']}*\n\n👉 Send the new name for this service.",
                    parse_mode=ParseMode.MARKDOWN,
                )

        elif action == "edit_service_name_value":
            svc_id = context.user_data.get("edit_service_id")
            if not svc_id:
                await update.message.reply_text("⚠️ Something went wrong. Please start over with 📝 Edit Service Name.")
            else:
                new_name = update.message.text.strip()
                edit_custom_service_field(svc_id, "name", new_name)
                context.user_data.pop("edit_service_id", None)
                await update.message.reply_text(
                    f"✅ Service `{svc_id}` renamed to *{new_name}*.", parse_mode=ParseMode.MARKDOWN
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
    """Handles a user's reply after picking a payment method — they type the USD amount
    they want to deposit, and the bot shows them the exact amount (+ memo if applicable) to send."""
    text_in = update.message.text.strip()
    user_id = update.effective_user.id

    method_key = context.user_data.get("selected_payment_method")
    if not method_key or method_key not in PAYMENT_METHODS:
        context.user_data["awaiting_deposit_amount"] = False
        await update.message.reply_text("⚠️ No payment method selected. Please start again from 📥 Deposit.")
        return
    method = PAYMENT_METHODS[method_key]

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

    fetching_msg = await update.message.reply_text("⏳ Fetching live price...")
    try:
        price = await get_token_price_usd(method)
    except Exception:
        await fetching_msg.edit_text(
            "⚠️ Couldn't fetch the live price right now. Please try again in a moment."
        )
        return  # keep awaiting_deposit_amount True so they can retry

    base_amount = usd_amount / price
    deposit_code = generate_unique_deposit_code()
    token_needed = base_amount

    context.user_data["awaiting_deposit_amount"] = False
    context.user_data["pending_deposit"] = {
        "usd": usd_amount, "token": token_needed, "method_key": method_key,
        "code": deposit_code,
    }

    text = (
        f"💸 *{method['label']} Deposit*\n\n"
        f"💵 *Amount:* `${usd_amount:.2f}`\n"
        f"💎 *Send exactly:* `{token_needed:.4f}` {method['symbol']}\n\n"
        "📥 *Address:*\n"
        f"`{method['address']}`\n\n"
        "📝 *Memo / Comment (REQUIRED — one-time code, use exactly this):*\n"
        f"`{deposit_code}`\n\n"
        "⚠️ This code is unique to *this* deposit only and can never be reused — "
        "send the *exact amount* above with this *exact* memo. Sending less, or "
        "with any other memo, won't be credited automatically.\n\n"
        "✅ After sending, tap *Verify Payment* below."
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Verify Payment", callback_data="verify_payment")],
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
    try:
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
    except Exception as e:
        # Never let an unexpected error crash the whole bot process —
        # just report it back so the admin/user can retry without losing the bot.
        try:
            await update.message.reply_text(f"⚠️ Unexpected error: {e}\nPlease try again.")
        except Exception:
            pass


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


async def global_error_handler(update, context: ContextTypes.DEFAULT_TYPE):
    """Catches ANY unhandled exception anywhere in the bot so the process never crashes/restarts."""
    print(f"⚠️ Unhandled error: {context.error}")

    # Telegram throws "Message is not modified" when we edit_message_text with the
    # exact same text+buttons as before — e.g. tapping "Try Again" on a deposit check
    # that still finds nothing. This is harmless and NOT a real failure, but it used to
    # surface to the user as a scary "⚠️ Something went wrong" every single time.
    err_text = str(context.error).lower()
    if "message is not modified" in err_text:
        try:
            if update.callback_query:
                await update.callback_query.answer("⏳ Still no new deposit found yet.")
        except Exception:
            pass
        return

    try:
        if isinstance(update, Update):
            if update.effective_message:
                await update.effective_message.reply_text(
                    "⚠️ Something went wrong. Please try again."
                )
            elif update.callback_query:
                await update.callback_query.answer("⚠️ Something went wrong. Please try again.", show_alert=True)
    except Exception:
        pass


async def _post_init_storage_check(app):
    """Runs once the bot starts. Confirms /data (the Volume) is writable so deposits/
    balances actually persist — and warns the admin in Telegram instead of failing silently."""
    _ensure_data_dir()
    if DATA_DIR_WRITABLE:
        print(f"✅ Storage OK — {DATA_FILE} is writable.")
    else:
        warning = (
            "⚠️ *STORAGE WARNING*\n\n"
            f"`{DATA_DIR}` is NOT writable on this deploy. No Railway Volume is mounted there.\n\n"
            "This means user balances, deposits, and orders will NOT be saved, and "
            "everything will reset (and old deposits can get re-credited) on the next redeploy.\n\n"
            "Fix: Railway → Service → Settings → Volumes → mount path must be exactly `/data`."
        )
        print(warning)
        try:
            await app.bot.send_message(chat_id=ADMIN_ID, text=warning, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            print(f"⚠️ Couldn't even send the storage warning to admin: {e}")


# ===================== MAIN =====================
def main():
    app = Application.builder().token(BOT_TOKEN).post_init(_post_init_storage_check).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("adminpanel", adminpanel))
    app.add_handler(CallbackQueryHandler(route_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_input))
    app.add_error_handler(global_error_handler)

    print("Bot is running... (Ctrl+C to stop)")
    app.run_polling()


if __name__ == "__main__":
    main()
