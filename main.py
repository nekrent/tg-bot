import logging
import time
import asyncio
import aiohttp
import ssl
import certifi
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand, Bot
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from telegram.constants import ChatAction
import telegram.error
import hmac
import hashlib
import base64

CHANNEL_USERNAME = "-1002355119131" 
ADMIN_USERNAME = "@Kasumi_13"

# === API Keys ===
OKX_API_KEY = ''
OKX_SECRET = ''
OKX_PASSPHRASE = ''

MEXC_API_KEY = ''
MEXC_SECRET = ''

BYBIT_API_KEY = ''
BYBIT_SECRET = ''

HTX_API_KEY = ''
HTX_SECRET = ''

KUCOIN_API_KEY = ''
KUCOIN_SECRET = ''
KUCOIN_PASSPHRASE = ''

# Setup
ssl_context = ssl.create_default_context(cafile=certifi.where())
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
# logger = logging.getLogger(__name__)
logger = logging.getLogger()  # Это root-логгер, он использует basicConfig

application = Application.builder().token('7796998539:AAG8gNmAgqvsqtxMJNrmTlb_DCpHZDQPdzw').build()
job_queue = application.job_queue

COINS = {
    'BNB': 'BNB', 'XRP': 'XRP', 'ATOM': 'ATOM', 'AVAX': 'AVAX',
    'ADA': 'ADA', 'SOL': 'SOL', 'SEI': 'SEI', 'DOT': 'DOT', 'SUI': 'SUI', 
    'LINK': 'LINK', 'XLM': 'XLM', 'HBAR': 'HBAR', 'NEAR': 'NEAR', 'APT': 'APT',
    'ETC': 'ETC', 'ALGO': 'ALGO', 'ARB': 'ARB', 'TIA': 'TIA', 'OP': 'OP', 
    'INJ': 'INJ', 'IMX': 'IMX', 'IOTA': 'IOTA', 'FLOW': 'FLOW', 'MANA': 'MANA',
    'STRK': 'STRK', 'KAVA': 'KAVA', 'MINA': 'MINA', 'ZIL': 'ZIL',
    'CELO': 'CELO', 'ZETA': 'ZETA', 'ONE': 'ONE', 'OSMO': 'OSMO', 'ENJ': 'ENJ',
    'COTI': 'COTI'
    }

EXCHANGES = ['Bybit', 'HTX', 'KuCoin', 'OKX', 'MEXC']
CACHE_TTL = 30
NOTIFY_COOLDOWN = 20 * 60

cache = {}  # (exchange, symbol): (price, timestamp)
deposit_status = {}  # (exchange, symbol): bool
withdraw_status = {}  # (exchange, symbol): bool
user_ids = set()
last_notification_time = {}

# Безопасный логгер
def safe_log_request(url: str, result, status: int, prefix: str = '[SUCCESS]'):
    from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

    parsed_url = urlparse(url)
    query = parse_qs(parsed_url.query)

    # Маскируем чувствительные параметры
    for key in query:
        if key.lower() in ('signature', 'sign', 'api_key', 'apikey', 'token'):
            query[key] = ['***']

    # Собираем безопасный URL обратно
    safe_query = urlencode(query, doseq=True)
    safe_url = urlunparse(parsed_url._replace(query=safe_query))

    # Обрезаем URL если он слишком длинный
    if len(safe_url) > 200:
        safe_url = safe_url[:200] + '...'

    logger.info(f"{prefix} URL: {safe_url} | Status: {status} | Result: {result}")
    
async def is_user_subscribed(bot: Bot, user_id: int, channel_username: str) -> bool:
    try:
        member = await bot.get_chat_member(chat_id=channel_username, user_id=user_id)
        return member.status in ('member', 'administrator', 'creator')
    except Exception as e:
        logger.warning(f"Не удалось проверить подписку: {e}")
        return False

async def ensure_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id
    if not await is_user_subscribed(context.bot, user_id, CHANNEL_USERNAME):
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("📩 Связаться с админом", url=f"https://t.me/{ADMIN_USERNAME.strip('@')}")
        ]])
        await update.message.reply_text(
            "❗ Чтобы пользоваться ботом, подпишитесь на наш канал.\n"
            "Если возникли вопросы — свяжитесь с админом.",
            reply_markup=keyboard
        )
        return False
    return True    

# Generate keyboard
def generate_keyboard():
    coins = list(COINS.items())
    keyboard, row = [], []
    for i, (name, value) in enumerate(coins):
        if value:
            row.append(InlineKeyboardButton(text=name, callback_data=value))
        if len(row) == 4:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    return keyboard

def generate_okx_headers():
    from datetime import datetime, timezone
    import hmac
    import hashlib
    import base64
    ts = datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
    method = 'GET'
    path = '/api/v5/asset/currencies'
    prehash = ts + method + path
    signature = base64.b64encode(hmac.new(OKX_SECRET.encode(), prehash.encode(), hashlib.sha256).digest()).decode()

    return {
        'OK-ACCESS-KEY': OKX_API_KEY,
        'OK-ACCESS-SIGN': signature,
        'OK-ACCESS-TIMESTAMP': ts,
        'OK-ACCESS-PASSPHRASE': OKX_PASSPHRASE,
        'Content-Type': 'application/json'
    }

def generate_mexc_headers():
    import time
    import hmac
    import hashlib
    import urllib.parse
    
    timestamp = str(int(time.time() * 1000))
    recv_window = "5000"
    params = {
        "timestamp": timestamp,
        "recvWindow": recv_window
    }

    # Формируем query string в отсортированном виде
    query_string = urllib.parse.urlencode(sorted(params.items()))

    # Подписываем строку
    signature = hmac.new(MEXC_SECRET.encode('utf-8'), query_string.encode('utf-8'), hashlib.sha256).hexdigest()

    # Добавляем signature в параметры
    signed_query = f"{query_string}&signature={signature}"

    headers = {
        "X-MEXC-APIKEY": MEXC_API_KEY,
        "Content-Type": "application/json"
    }

    return headers, signed_query

def generate_bybit_headers() -> dict:
    import hmac
    import hashlib
    import time

    api_key = BYBIT_API_KEY
    api_secret = BYBIT_SECRET
    timestamp = str(int(time.time() * 1000))
    recv_window = "5000"

    # Подпись формируется из этой строки (именно в таком порядке!)
    sign_payload = f"{timestamp}{api_key}{recv_window}"
    signature = hmac.new(
        api_secret.encode('utf-8'),
        sign_payload.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()

    headers = {
        "X-BAPI-API-KEY": api_key,
        "X-BAPI-TIMESTAMP": timestamp,
        "X-BAPI-RECV-WINDOW": recv_window,
        "X-BAPI-SIGN": signature,
        "Content-Type": "application/json"
    }
    return headers


def generate_htx_headers():
    # HTX требует query-подписей (через HMAC-SHA256, URL-параметры). Лучше использовать GET-запросы без ключей.
    return {}

def generate_kucoin_headers(endpoint='/api/v1/currencies/BTC', method='GET', body=''):
    now = str(int(time.time() * 1000))
    str_to_sign = now + method + endpoint + body
    signature = base64.b64encode(hmac.new(KUCOIN_SECRET.encode('utf-8'), str_to_sign.encode('utf-8'), hashlib.sha256).digest()).decode()
    passphrase = base64.b64encode(hmac.new(KUCOIN_SECRET.encode('utf-8'), KUCOIN_PASSPHRASE.encode('utf-8'), hashlib.sha256).digest()).decode()

    return {
        'KC-API-KEY': KUCOIN_API_KEY,
        'KC-API-SIGN': signature,
        'KC-API-TIMESTAMP': now,
        'KC-API-PASSPHRASE': passphrase,
        'KC-API-KEY-VERSION': '2',
        'Content-Type': 'application/json'
    }

# Generic price fetcher
async def get_price(url, extractor, headers=None):
    try:
        connector = aiohttp.TCPConnector(ssl=ssl_context)
        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.get(url, headers=headers) as resp:
                text = await resp.text()
                if resp.status == 200:
                    try:
                        data = await resp.json()
                        result = extractor(data)
                        safe_log_request(url, result, resp.status)
                        return result
                    except Exception as e:
                        logger.error(f"[ERROR] Extracting data from: {url} | Raw: {text} | Error: {e}")
                else:
                    logger.error(f"[ERROR] Status {resp.status} from {url} | Body: {text}")
    except Exception as e:
        logger.error(f"[ERROR] Fetching {url}: {e}")
    return None

# Price API functions
async def get_bybit_price(symbol):
    url = f'https://api.bybit.com/v5/market/tickers?category=spot&symbol={symbol}USDT'
    return await get_price(url, lambda d: float(d['result']['list'][0]['lastPrice']) if d.get('result') else None)

async def get_htx_price(symbol):
    url = f"https://api-aws.huobi.pro/market/detail/merged?symbol={symbol.lower()}usdt"
    return await get_price(url, lambda d: float(d['tick']['close']) if d.get('tick') else None)

async def get_kucoin_price(symbol):
    url = f"https://api.kucoin.com/api/v1/market/orderbook/level1?symbol={symbol}-USDT"
    return await get_price(url, lambda d: float(d['data']['price']) if d.get('data') else None)

async def get_okx_price(symbol):
    url = f'https://www.okx.com/api/v5/market/ticker?instId={symbol}-USDT'
    return await get_price(url, lambda d: float(d['data'][0]['last']) if d.get('data') else None)

async def get_mexc_price(symbol):
    url = f'https://api.mexc.com/api/v3/ticker/price?symbol={symbol}USDT'
    return await get_price(url, lambda d: float(d['price']) if 'price' in d else None)

# Deposit and withdraw status checkers
#Bybit
async def get_bybit_deposit(symbol: str) -> bool:
    import aiohttp

    url = 'https://api.bybit.com/v5/asset/coin/query-info'
    headers = generate_bybit_headers()

    try:
        connector = aiohttp.TCPConnector(ssl=ssl_context)
        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.get(url, headers=headers) as response:
                text = await response.text()
                if response.status != 200:
                    logger.error(f"[BYBIT] HTTP {response.status}: {text}")
                    return False

                data = await response.json()
                if data.get('retCode') != 0:
                    logger.error(f"[BYBIT] API error: {data.get('retMsg')}")
                    return False

                for coin in data.get('result', {}).get('rows', []):
                    if coin.get('coin', '').upper() == symbol.upper():
                        for chain in coin.get('chains', []):
                            if chain.get('chainDeposit') == '1':
                                return True
                        return False
                return False
    except Exception as e:
        logger.error(f"[BYBIT] Exception: {e}")
        return False
    
    return await get_price(url, extractor, headers=headers)

async def get_bybit_withdraw(symbol: str) -> bool:
    url = 'https://api.bybit.com/v5/asset/coin/query-info'
    headers = generate_bybit_headers()

    try:
        connector = aiohttp.TCPConnector(ssl=ssl_context)
        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.get(url, headers=headers) as response:
                text = await response.text()
                if response.status != 200:
                    logger.error(f"[BYBIT-WD] HTTP {response.status}: {text}")
                    return False

                data = await response.json()
                if data.get('retCode') != 0:
                    logger.error(f"[BYBIT-WD] API error: {data.get('retMsg')}")
                    return False

                for coin in data.get('result', {}).get('rows', []):
                    if coin.get('coin', '').upper() == symbol.upper():
                        for chain in coin.get('chains', []):
                            if chain.get('chainWithdraw') == '1':
                                return True
                        return False
                return False
    except Exception as e:
        logger.error(f"[BYBIT-WD] Exception: {e}")
        return False

#HTX
async def get_htx_deposit(symbol):
    url = f'https://api.huobi.pro/v2/reference/currencies'
    return await get_price(url, lambda d: any(x['currency'].upper() == symbol and x['chains'][0]['depositStatus'] == 'allowed' for x in d['data']))

async def get_htx_withdraw(symbol):
    url = 'https://api.huobi.pro/v2/reference/currencies'
    return await get_price(
        url,
        lambda d: any(
            x['currency'].upper() == symbol.upper() and 
            any(c['withdrawStatus'] == 'allowed' for c in x['chains'])
            for x in d['data']
        )
    )

#KuCoin
async def get_kucoin_deposit(symbol):
    endpoint = f'/api/v1/currencies/{symbol}'
    url = 'https://api.kucoin.com' + endpoint
    headers = generate_kucoin_headers(endpoint)
    
    def extractor(d):
        data = d.get('data', {})
        return data.get('isDepositEnabled', False)

    return await get_price(url, extractor, headers=headers)

async def get_kucoin_withdraw(symbol):
    endpoint = f'/api/v1/currencies/{symbol}'
    url = 'https://api.kucoin.com' + endpoint
    headers = generate_kucoin_headers(endpoint)

    def extractor(d):
        data = d.get('data', {})
        return data.get('isWithdrawEnabled', False)

    return await get_price(url, extractor, headers=headers)

#OKX
async def get_okx_deposit(symbol):
    url = 'https://www.okx.com/api/v5/asset/currencies'
    headers = generate_okx_headers()
    
    def extractor(d):
        for x in d.get('data', []):
            if x.get('ccy') == symbol.upper():
                # canDep == 'true' означает, что депозиты разрешены
                return x.get('canDep') is True
        return False

    return await get_price(url, extractor, headers=headers)

async def get_okx_withdraw(symbol):
    url = 'https://www.okx.com/api/v5/asset/currencies'
    headers = generate_okx_headers()

    def extractor(d):
        for item in d.get('data', []):
            if item.get('ccy') == symbol.upper():
                return item.get('canWd') is True
        return False

    return await get_price(url, extractor, headers=headers)

#MEXC
async def get_mexc_deposit(symbol):
    base = 'https://api.mexc.com'
    ep = '/api/v3/capital/config/getall'
    headers, signed = generate_mexc_headers()  # как у тебя: timestamp+recvWindow+signature
    url = f"{base}{ep}?{signed}"
    def extractor(d):
        for coin_obj in d:
            if coin_obj.get('coin') == symbol:
                for net in coin_obj.get('networkList', []):
                    if net.get('depositEnable', False):
                        return True
                return False
        return False
    return await get_price(url, extractor, headers=headers)

async def get_mexc_withdraw(symbol):
    base = 'https://api.mexc.com'
    ep = '/api/v3/capital/config/getall'
    headers, signed = generate_mexc_headers()
    url = f"{base}{ep}?{signed}"

    def extractor(d):
        for coin_obj in d:
            if coin_obj.get('coin') == symbol:
                for net in coin_obj.get('networkList', []):
                    if net.get('withdrawEnable', False):
                        return True
                return False
        return False

    return await get_price(url, extractor, headers=headers)


# Update all transfer status
async def update_all_transfer_statuses():
    for symbol in COINS.values():
        for ex, func_d, func_w in zip(
            EXCHANGES,
            [get_bybit_deposit, get_htx_deposit, get_kucoin_deposit, get_okx_deposit, get_mexc_deposit],
            [get_bybit_withdraw, get_htx_withdraw, get_kucoin_withdraw, get_okx_withdraw, get_mexc_withdraw]
        ):
            deposit_status[(ex, symbol)] = await func_d(symbol)
            withdraw_status[(ex, symbol)] = await func_w(symbol)

# Fetch with cache & deposit filter
async def fetch_price_with_cache(exchange, symbol, fetch_func):
    key = (exchange, symbol)
    now = time.time()
    if key in cache and now - cache[key][1] < CACHE_TTL:
        return cache[key][0]
    price = await fetch_func(symbol)
    if price:
        cache[key] = (price, now)
    return price

async def generate_response_text(symbol: str, force_fetch: bool = False) -> str:
    coin_name = next((k for k, v in COINS.items() if v == symbol), symbol)
    response = f'\U0001F3E6 <b>{coin_name} курсы:</b>\n\n'

    prices = []
    active_prices = []

    fetch_funcs = [
        get_bybit_price,
        get_htx_price,
        get_kucoin_price,
        get_okx_price,
        get_mexc_price,
    ]

    for exchange, fetch_func in zip(EXCHANGES, fetch_funcs):
        # Получаем цену из кэша или с помощью функции
        if force_fetch or (exchange, symbol) not in cache or time.time() - cache[(exchange, symbol)][1] > CACHE_TTL:
            price = await fetch_price_with_cache(exchange, symbol, fetch_func)
        else:
            price = cache[(exchange, symbol)][0]

        # Получаем статус депозита/вывода
        dep = deposit_status.get((exchange, symbol), False)
        wd = withdraw_status.get((exchange, symbol), False)

        # Проверяем статус активации (и депозита, и вывода)
        is_active = dep and wd

        prices.append(price)

        price_str = f'{price:.6f} USDT' if price else 'Нет данных'
        dep_str = '✅' if dep else '❌'
        wd_str = '✅' if wd else '❌'

        response += f'\U0001F539 {exchange}: {price_str} | Депозит: {dep_str} | Вывод: {wd_str}\n'

        if price and is_active:
            active_prices.append((exchange, price))

    # Арбитражная информация
    if len(active_prices) >= 2:
        min_ex, min_price = min(active_prices, key=lambda x: x[1])
        max_ex, max_price = max(active_prices, key=lambda x: x[1])
        spread = max_price - min_price
        spread_pct = (spread / min_price) * 100
        response += f'\n\U0001F53B Минимум: {min_ex} - ${min_price:.6f}\n'
        response += f'\U0001F53A Максимум: {max_ex} - ${max_price:.6f}\n'
        response += f'\U0001F4CA Спред: ${spread:.6f} ({spread_pct:.2f}%)'
    else:
        response += '\n❗ Недостаточно бирж с активным депозитом и выводом для арбитража'

    return response

async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    symbol = query.data

    # 👇 Обработка фиктивной кнопки "noop"
    if symbol == "noop":
        await query.answer()
        return

    try:
        await query.answer()

        # Шаг 1: Показываем "анимацию" загрузки
        loading_keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("🔄 Обновляется…", callback_data="noop")
        ]])
        try:
            await query.edit_message_reply_markup(reply_markup=loading_keyboard)
        except telegram.error.BadRequest as e:
            logger.warning(f"Не удалось показать кнопку загрузки: {e}")

        # Шаг 2: Показать "печатает"
        await context.bot.send_chat_action(chat_id=query.message.chat_id, action=ChatAction.TYPING)
        await asyncio.sleep(1.2)

        # Шаг 3: Сгенерировать ответ
        response = await generate_response_text(symbol, force_fetch=True)
        current_text = query.message.text_html or query.message.text

        # Шаг 4: Обновить сообщение при изменении
        if response.strip() == current_text.strip():
            logger.info(f"Текст не изменился для {symbol}, обновим только клавиатуру.")
            await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(generate_keyboard()))
        else:
            await query.edit_message_text(
                response,
                reply_markup=InlineKeyboardMarkup(generate_keyboard()),
                parse_mode='HTML'
            )

    except Exception as e:
        logger.exception(f"Ошибка в обработке кнопки {symbol}: {e}")

async def check_spread_periodically(app: Application):
    while True:
        await update_all_transfer_statuses()
        now = time.time()

        for symbol in COINS.values():
            prices = {
                'Bybit': await fetch_price_with_cache('Bybit', symbol, get_bybit_price),
                'HTX': await fetch_price_with_cache('HTX', symbol, get_htx_price),
                'KuCoin': await fetch_price_with_cache('KuCoin', symbol, get_kucoin_price),
                'OKX': await fetch_price_with_cache('OKX', symbol, get_okx_price),
                'MEXC': await fetch_price_with_cache('MEXC', symbol, get_mexc_price)
            }

            # Биржи с ценой и активным депозитом
            valid = [
                (ex, p) for ex, p in prices.items()
                #if p and deposit_status.get((ex, symbol), False)
                if p and deposit_status.get((ex, symbol), False) and withdraw_status.get((ex, symbol), False)
            ]

            if len(valid) >= 2:
                min_ex, min_price = min(valid, key=lambda x: x[1])
                max_ex, max_price = max(valid, key=lambda x: x[1])
                spread_pct = ((max_price - min_price) / min_price) * 100

                if spread_pct >= 0.5:
                    last_time = last_notification_time.get(symbol, 0)
                    if now - last_time >= NOTIFY_COOLDOWN:
                        # Генерация таблицы цен и статусов депозитов
                        text = f'\U0001F4B0 {symbol} курсы:\n\n'
                        for ex, price in prices.items():
                            dep = '✅' if deposit_status.get((ex, symbol), False) else '❌'
                            wd = '✅' if withdraw_status.get((ex, symbol), False) else '❌'
                            price_str = f'{price:.6f} USDT' if price else 'Нет данных'
                            text += f'🔹 {ex}: {price_str} | Депозит: {dep} | Вывод: {wd}\n'

                        # Добавление строки с направлением арбитража
                        arbitrage_line = (
                            f"\n📈 Купить на <b>{min_ex}</b> по <b>{min_price:.6f} USDT</b>, "
                            f"продать на <b>{max_ex}</b> по <b>{max_price:.6f} USDT</b>\n"
                            f"📊 Спред: <b>{spread_pct:.2f}%</b>"
                        )

                        msg = f'\U0001F6A8 АРБИТРАЖ ВОЗМОЖЕН:\n\n{text}{arbitrage_line}'
                        
                        for uid in user_ids:
                            try:
                                if await is_user_subscribed(app.bot, uid, CHANNEL_USERNAME):
                                    await app.bot.send_message(chat_id=uid, text=msg, parse_mode='HTML')
                                else:
                                    logger.info(f"Пользователь {uid} не подписан — уведомление не отправлено.")
                            except Exception as e:
                                logger.error(f"Ошибка отправки пользователю {uid}: {e}")

                        last_notification_time[symbol] = now

        await asyncio.sleep(300)  # проверка каждые 5 минут
        
# Telegram handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_subscription(update, context):
        return
    user_ids.add(update.effective_chat.id)
    keyboard = generate_keyboard()
    await update.message.reply_text('\U0001F4B0 Выберите криптовалюту:', reply_markup=InlineKeyboardMarkup(keyboard))
        
async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_subscription(update, context):
        return
    await update.message.reply_text("Уведомления остановлены.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_subscription(update, context):
        return
    await update.message.reply_text("Используйте /start для запуска бота и выбора монет.")

async def coins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await ensure_subscription(update, context):
        return
    await start(update, context)  # если start показывает список монет

async def set_bot_commands(app: Application):
    commands = [
        BotCommand("start", "Запустить бота и выбрать монеты"),
        BotCommand("stop", "Остановить уведомления"),
        BotCommand("help", "Справка"),
        BotCommand("coins", "Показать список монет")
    ]
    await app.bot.set_my_commands(commands)
    
spread_task: asyncio.Task | None = None

async def on_startup(application: Application):
    global spread_task
    spread_task = asyncio.create_task(check_spread_periodically(application))
    await set_bot_commands(application)
    
async def on_shutdown(application: Application):
    global spread_task
    if spread_task:
        spread_task.cancel()
        try:
            await spread_task
        except asyncio.CancelledError:
            pass  # задача отменена — всё ок

# Entry
application.post_init = on_startup
application.post_shutdown = on_shutdown
application.add_handler(CommandHandler('start', start))
application.add_handler(CommandHandler('stop', stop))
application.add_handler(CommandHandler('help', help_command))
application.add_handler(CommandHandler('coins', coins))
application.add_handler(CallbackQueryHandler(button_click))
application.run_polling()
            
