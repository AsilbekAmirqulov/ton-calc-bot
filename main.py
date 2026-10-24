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

rates_cache = {
    "ton_usd": 0.0,
    "usd_uzs": 0.0,
    "last_update": 0
}

async def get_rates():
    now = time.time()
    # Har 60 soniyada bir marta API'dan yangilanadi
    if now - rates_cache["last_update"] < 60 and rates_cache["ton_usd"] > 0:
        return rates_cache["ton_usd"], rates_cache["usd_uzs"]

    # Serverlar bloklamasligi uchun brauzer kabi so'rov yuborish
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    async with aiohttp.ClientSession(headers=headers) as session:
        ton_usd = 0.0

        # 1-urinish: TonAPI (Telegram ekotizimi API'si)
        try:
            async with session.get("https://tonapi.io/v2/rates?tokens=ton&currencies=usd", timeout=5) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    ton_usd = float(data["rates"]["TON"]["prices"]["USD"])
        except Exception:
            pass

        # 2-urinish: CoinGecko API
        if ton_usd == 0.0:
            try:
                async with session.get("https://api.coingecko.com/api/v3/simple/price?ids=the-open-network&vs_currencies=usd", timeout=5) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        ton_usd = float(data["the-open-network"]["usd"])
            except Exception:
                pass

        # 3-urinish: OKX API
        if ton_usd == 0.0:
            try:
                async with session.get("https://www.okx.com/api/v5/market/ticker?instId=TON-USDT", timeout=5) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        ton_usd = float(data["data"][0]["last"])
            except Exception:
                pass

        # 4-urinish: Binance API
        if ton_usd == 0.0:
            try:
                async with session.get("https://api.binance.com/api/v3/ticker/price?symbol=TONUSDT", timeout=5) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        ton_usd = float(data["price"])
            except Exception:
                pass

        if ton_usd == 0.0:
            ton_usd = rates_cache["ton_usd"] or 5.0

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

        rates_cache["ton_usd"] = ton_usd
        rates_cache["usd_uzs"] = usd_uzs
        rates_cache["last_update"] = now

        return rates_cache["ton_usd"], rates_cache["usd_uzs"]

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

    # 1. TON / GRAM kalkulyatori (Lotin va Kirill xabarlarini avtomatik tanish)
    # Masalan: "1 ton", "2.5 тон", "11.2 gram", "10 грамм", "15tonn"
    crypto_match = re.search(r'^\b(\d+(?:[\.,]\d+)?)\s*(ton|tonn|тон|тонн|gram|gramm|грамм)\b', text)
    if crypto_match:
        amount = float(crypto_match.group(1).replace(',', '.'))
        unit_word = crypto_match.group(2)
        
        ton_usd, usd_uzs = await get_rates()

        if ton_usd == 0:
            await message.reply("⚠️ Kurs ma'lumotlarini olishda xatolik yuz berdi. Birozdan so'ng qayta urinib ko'ring.")
            return

        total_usd = amount * ton_usd
        total_uzs = total_usd * usd_uzs

        formatted_uzs = f"{total_uzs:,.0f}"
        response = f"<b>{amount:g} {unit_word}</b> = <b>{total_usd:.2f} usd</b> | <b>{formatted_uzs} so'm</b>"

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

# Render salomatlik tekshiruvi (Health check) uchun mini-server
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
