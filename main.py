import asyncio
import os
import re
import time
import aiohttp
from aiohttp import web
from aiogram import Bot, Dispatcher, F, types
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

BOT_TOKEN = os.environ.get("BOT_TOKEN")

# Render'dagi xususiy manzilingiz webhook uchun ulanadi
WEBHOOK_URL = "https://ton-calc-bot.onrender.com/webhook"

CRYPTO_MAP = {
    'ton': 'TON', 'tonn': 'TON', 'тон': 'TON', 'тонн': 'TON', 'gram': 'TON', 'gramm': 'TON', 'грамм': 'TON',
    'btc': 'BTC', 'бтк': 'BTC', 'bitcoin': 'BTC', 'биткоин': 'BTC', 'биткойн': 'BTC',
    'eth': 'ETH', 'эфир': 'ETH', 'ethereum': 'ETH', 'этериум': 'ETH',
    'usdt': 'USDT', 'usd': 'USDT', 'usdc': 'USDT', 'доллар': 'USDT'
}

rates_cache = {
    "prices": {"TON": 0.0, "BTC": 0.0, "ETH": 0.0, "USDT": 1.0},
    "usd_uzs": 0.0,
    "last_update": 0
}

async def update_rates():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    prices = {"TON": 0.0, "BTC": 0.0, "ETH": 0.0, "USDT": 1.0}
    usd_uzs = 0.0

    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            # 1. CoinCap API
            try:
                async with session.get("https://api.coincap.io/v2/assets?ids=bitcoin,ethereum,the-open-network", timeout=4) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        for item in data.get("data", []):
                            if item["id"] == "bitcoin": prices["BTC"] = float(item["priceUsd"])
                            elif item["id"] == "ethereum": prices["ETH"] = float(item["priceUsd"])
                            elif item["id"] == "the-open-network": prices["TON"] = float(item["priceUsd"])
            except Exception:
                pass

            # 2. OKX API (Zaxira)
            if prices["BTC"] == 0.0 or prices["TON"] == 0.0:
                try:
                    async with session.get("https://www.okx.com/api/v5/market/ticker?instId=BTC-USDT", timeout=4) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            prices["BTC"] = float(data["data"][0]["last"])
                except Exception:
                    pass

                try:
                    async with session.get("https://www.okx.com/api/v5/market/ticker?instId=TON-USDT", timeout=4) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            prices["TON"] = float(data["data"][0]["last"])
                except Exception:
                    pass

            # 3. TonAPI
            if prices["TON"] == 0.0:
                try:
                    async with session.get("https://tonapi.io/v2/rates?tokens=ton&currencies=usd", timeout=4) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            prices["TON"] = float(data["rates"]["TON"]["prices"]["USD"])
                except Exception:
                    pass

            # 4. Markaziy Bank API
            try:
                async with session.get("https://cbu.uz/uz/arkhiv-kursov-valyut/json/USD/", timeout=4) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        usd_uzs = float(data[0]["Rate"])
            except Exception:
                pass

            # 5. Zaxira USD API
            if usd_uzs == 0.0:
                try:
                    async with session.get("https://open.er-api.com/v6/latest/USD", timeout=4) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            usd_uzs = float(data["rates"]["UZS"])
                except Exception:
                    pass

        # Xotirani yangilash
        for k in prices:
            if prices[k] > 0:
                rates_cache["prices"][k] = prices[k]

        if usd_uzs > 0:
            rates_cache["usd_uzs"] = usd_uzs

        rates_cache["last_update"] = time.time()
    except Exception:
        pass

# Fonda uzluksiz yangilash davri
async def fetch_rates_background():
    while True:
        await update_rates()
        await asyncio.sleep(45)

def parse_k_m(expr: str) -> str:
    expr = re.sub(r'(\d+(?:\.\d+)?)\s*k\b', lambda m: str(float(m.group(1)) * 1000), expr)
    expr = re.sub(r'(\d+(?:\.\d+)?)\s*m\b', lambda m: str(float(m.group(1)) * 1000000), expr)
    return expr

def safe_eval(expr: str):
    expr = expr.replace(',', '.')
    expr = parse_k_m(expr)
    expr = re.sub(r'(\d+(?:\.\d+)?)\s*%', r'(\1/100)', expr)

    if not re.match(r'^[0-9\+\-\*\/\(\)\.\s]+$', expr):
        return None

    try:
        result = eval(expr, {"__builtins__": None}, {})
        if isinstance(result, (int, float)):
            return result
    except Exception:
        return None
    return None

def get_delete_keyboard(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑 O'chirish", callback_data=f"delete:{user_id}")]
    ])

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

@dp.message(F.text)
async def handle_messages(message: types.Message):
    text = message.text.strip().lower()

    crypto_pattern = r'^\b(\d+(?:[\.,]\d+)?)\s*(' + '|'.join(CRYPTO_MAP.keys()) + r')\b'
    crypto_match = re.search(crypto_pattern, text)

    if crypto_match:
        amount = float(crypto_match.group(1).replace(',', '.'))
        unit_word = crypto_match.group(2)
        crypto_code = CRYPTO_MAP.get(unit_word, 'TON')

        token_price = rates_cache["prices"].get(crypto_code, 0.0)
        usd_uzs = rates_cache["usd_uzs"]

        if token_price == 0 or usd_uzs == 0:
            await message.reply("⚠️ Kurs ma'lumotlari yuklanmoqda, iltimos 3 soniyadan so'ng qayta urinib ko'ring.")
            return

        total_usd = amount * token_price
        total_uzs = total_usd * usd_uzs

        formatted_uzs = f"{total_uzs:,.0f}"
        formatted_usd = f"{total_usd:,.2f}" if total_usd >= 1 else f"{total_usd:,.4f}"

        response = f"<b>{amount:g} {unit_word}</b> = <b>{formatted_usd} usd</b> | <b>{formatted_uzs} so'm</b>"

        kb = get_delete_keyboard(message.from_user.id)
        await message.reply(response, reply_markup=kb)
        return

    if re.search(r'[\+\-\*\/\%]', text) and not re.search(r'[a-jl-ln-zq-zA-JL-LN-ZQ-Zа-яА-Я]', text):
        result = safe_eval(text)
        if result is not None:
            if isinstance(result, float):
                formatted_res = f"{result:,.4f}".rstrip('0').rstrip('.')
            else:
                formatted_res = f"{result:,}"

            kb = get_delete_keyboard(message.from_user.id)
            await message.reply(f"🧮 <b>Natija:</b> <code>{formatted_res}</code>", reply_markup=kb)

@dp.callback_query(F.data.startswith("delete:"))
async def delete_message_callback(callback: types.CallbackQuery):
    owner_id = int(callback.data.split(":")[1])
    user_id = callback.from_user.id

    is_admin = False
    if callback.message.chat.type in ['group', 'supergroup']:
        try:
            member = await callback.bot.get_chat_member(callback.message.chat.id, user_id)
            if member.status in ['creator', 'administrator']:
                is_admin = True
        except Exception:
            pass

    if user_id == owner_id or is_admin:
        await callback.message.delete()
    else:
        await callback.answer("Siz bu xabarni o'chira olmaysiz! Faqat muallif yoki admin o'chira oladi.", show_alert=True)

# ----------------- WEBHOOK SOZLAMALARI -----------------

async def on_startup(bot: Bot):
    # Telegramga webhook ulash (endi bot aslo qotib qolmaydi)
    await bot.set_webhook(WEBHOOK_URL, drop_pending_updates=True)
    print(f"Webhook muvaffaqiyatli o'rnatildi: {WEBHOOK_URL}")
    await update_rates()
    asyncio.create_task(fetch_rates_background())

async def handle_ping(request):
    return web.Response(text="Bot Webhook rejimida 24/7 ishlayapti!")

def main():
    dp.startup.register(on_startup)

    app = web.Application()
    app.router.add_get("/", handle_ping)

    # Telegram'ning webhook zaproslarini aynan shu yerda qabul qilamiz
    webhook_requests_handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
    webhook_requests_handler.register(app, path="/webhook")
    setup_application(app, dp, bot=bot)

    port = int(os.environ.get("PORT", 8080))
    print("Veb-server ishga tushmoqda...")
    web.run_app(app, host="0.0.0.0", port=port)

if __name__ == "__main__":
    main()
