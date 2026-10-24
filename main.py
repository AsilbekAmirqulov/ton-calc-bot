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

# BOT TOKENINGIZNI SHU YERGA YOZING:
BOT_TOKEN = "BOT_TOKENINGIZNI_BUYERGA_YOZING"

# Kriptovalutalar nomini asosiy kodlarga bog'lash (Lotin va Kirill)
CRYPTO_MAP = {
    'ton': 'TON', 'tonn': 'TON', 'тон': 'TON', 'тонн': 'TON', 'gram': 'TON', 'gramm': 'TON', 'грамм': 'TON',
    'btc': 'BTC', 'бтк': 'BTC', 'bitcoin': 'BTC', 'биткоин': 'BTC', 'биткойн': 'BTC',
    'eth': 'ETH', 'эфир': 'ETH', 'ethereum': 'ETH', 'этериум': 'ETH',
    'usdt': 'USDT', 'usd': 'USDT', 'usdc': 'USDT', 'доллар': 'USDT'
}

rates_cache = {
    "prices": {
        "TON": 0.0,
        "BTC": 0.0,
        "ETH": 0.0,
        "USDT": 1.0
    },
    "usd_uzs": 0.0,
    "last_update": 0
}

async def get_rates():
    now = time.time()
    # Har 60 soniyada bir marta API'dan yangilanadi
    if now - rates_cache["last_update"] < 60 and all(v > 0 for k, v in rates_cache["prices"].items() if k != "USDT"):
        return rates_cache["prices"], rates_cache["usd_uzs"]

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    prices = rates_cache["prices"].copy()

    async with aiohttp.ClientSession(headers=headers) as session:
        # 1-urinish: Binance API (BTC, ETH, TON narxlarini bir so'rovda olish)
        try:
            async with session.get("https://api.binance.com/api/v3/ticker/price", timeout=5) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    price_map = {item["symbol"]: float(item["price"]) for item in data if item["symbol"] in ["BTCUSDT", "ETHUSDT", "TONUSDT"]}
                    if "TONUSDT" in price_map: prices["TON"] = price_map["TONUSDT"]
                    if "BTCUSDT" in price_map: prices["BTC"] = price_map["BTCUSDT"]
                    if "ETHUSDT" in price_map: prices["ETH"] = price_map["ETHUSDT"]
        except Exception:
            pass

        # 2-urinish: TonAPI (TON uchun)
        if prices["TON"] == 0.0:
            try:
                async with session.get("https://tonapi.io/v2/rates?tokens=ton&currencies=usd", timeout=5) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        prices["TON"] = float(data["rates"]["TON"]["prices"]["USD"])
            except Exception:
                pass

        # 3-urinish: CoinGecko API (Zaxira manba)
        if prices["BTC"] == 0.0 or prices["ETH"] == 0.0 or prices["TON"] == 0.0:
            try:
                async with session.get("https://api.coingecko.com/api/v3/simple/price?ids=the-open-network,bitcoin,ethereum&vs_currencies=usd", timeout=5) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if "the-open-network" in data and prices["TON"] == 0.0:
                            prices["TON"] = float(data["the-open-network"]["usd"])
                        if "bitcoin" in data and prices["BTC"] == 0.0:
                            prices["BTC"] = float(data["bitcoin"]["usd"])
                        if "ethereum" in data and prices["ETH"] == 0.0:
                            prices["ETH"] = float(data["ethereum"]["usd"])
            except Exception:
                pass

        # Markaziy Bank API - USD/UZS
        usd_uzs = 0.0
        try:
            async with session.get("https://cbu.uz/uz/arkhiv-kursov-valyut/json/USD/", timeout=5) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    usd_uzs = float(data[0]["Rate"])
        except Exception:
            pass

        if usd_uzs == 0.0:
            usd_uzs = rates_cache["usd_uzs"] or 12800.0

        rates_cache["prices"] = prices
        rates_cache["usd_uzs"] = usd_uzs
        rates_cache["last_update"] = now

        return rates_cache["prices"], rates_cache["usd_uzs"]

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

    # Kriptovalutalarni qidirish regex i
    crypto_pattern = r'^\b(\d+(?:[\.,]\d+)?)\s*(' + '|'.join(CRYPTO_MAP.keys()) + r')\b'
    crypto_match = re.search(crypto_pattern, text)

    if crypto_match:
        amount = float(crypto_match.group(1).replace(',', '.'))
        unit_word = crypto_match.group(2)
        crypto_code = CRYPTO_MAP.get(unit_word, 'TON')

        prices, usd_uzs = await get_rates()
        token_price = prices.get(crypto_code, 0.0)

        if token_price == 0:
            await message.reply("⚠️ Kurs ma'lumotlarini olishda xatolik yuz berdi. Birozdan so'ng qayta urinib ko'ring.")
            return

        total_usd = amount * token_price
        total_uzs = total_usd * usd_uzs

        formatted_uzs = f"{total_uzs:,.0f}"
        formatted_usd = f"{total_usd:,.2f}" if total_usd >= 1 else f"{total_usd:,.4f}"

        response = f"<b>{amount:g} {unit_word}</b> = <b>{formatted_usd} usd</b> | <b>{formatted_uzs} so'm</b>"

        kb = get_delete_keyboard(message.from_user.id)
        await message.reply(response, reply_markup=kb)
        return

    # 2. Matematik amallar
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

async def handle_ping(request):
    return web.Response(text="Bot 24/7 rejimida ishlayapti!")

async def main():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

    print("Bot muvaffaqiyatli ishga tushdi...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
