# =============================
# Execution mode
# =============================

# "paper" = виртуальная торговля
# "real" = реальная (подключается позже executor)
EXECUTION_MODE = "paper"

TELEGRAM_ENABLED = True
TELEGRAM_BOT_TOKEN = "8715407394:AAHWqqgbnyTW6y2VGHDLQ7gzt4W1KOa-R-0"
TELEGRAM_CHAT_ID = "840388513"

BINGX_ENABLED = False
BINGX_API_KEY = "30f5NHUM5dz3sb9svEPz99C6OwUTYjDsSzDAG5RwezCHgL0crmFhU3ADvChLpsMSdayTQixl3RyVtO3g"
BINGX_SECRET_KEY = "p3m4pb6FX8olLzQz9KHKHgKlht8xycilKg8jjNfP0KO2wnSJd0Su7sLcceF3lQ2YErg2A1V8jLCQ589v2UQ"
BINGX_BASE_URL = "https://open-api.bingx.com"

TOP_SYMBOLS_COUNT = 20
SCAN_INTERVAL_SECONDS = 300
MIN_VOLUME_FILTER = 5_000_000

# =============================
# Whale Flow Bot CONFIG
# =============================

# Стартовый баланс (виртуальный)
START_BALANCE_USDT = 100.0

# Максимум одновременно открытых сделок
MAX_OPEN_POSITIONS = 10

# Размер входа (% от баланса)
FIXED_MARGIN_PCT = 0.03

# =============================
# Stop / Take
# =============================

STOP_LOSS_PCT = 0.025
TAKE_PROFIT_PCT = 0.05

# =============================
# Плечо
# =============================

# Режим плеча:
# "dynamic" = автоматически по силе сигнала
# "fixed" = всегда одинаковое плечо

LEVERAGE_MODE = "fixed"

# Используется если LEVERAGE_MODE = "fixed"
FIXED_LEVERAGE = 20

# =============================
# Монеты
# =============================

SYMBOLS = [
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "BNBUSDT",
    "XRPUSDT",
    "AVAXUSDT",
    "LINKUSDT",
    "ADAUSDT",
    "DOGEUSDT",
    "LTCUSDT",
    "DOTUSDT",
    "MATICUSDT",
    "ATOMUSDT",
    "APTUSDT",
    "NEARUSDT",
    "ARBUSDT",
    "OPUSDT",
    "INJUSDT",
    "SUIUSDT",
    "SEIUSDT",
    "FILUSDT",
    "TRXUSDT",
    "ETCUSDT",
    "AAVEUSDT",
    "UNIUSDT",
    "XLMUSDT",
    "ALGOUSDT",
    "VETUSDT",
    "ICPUSDT",
    "RUNEUSDT",
]

# =============================
# Binance / Bybit endpoints
# =============================

BINANCE_WS_BASE = "wss://fstream.binance.com"
BINANCE_REST_BASE = "https://fapi.binance.com"
BYBIT_REST_BASE = "https://api.bybit.com"

# =============================
# Whale flow detection
# =============================

LARGE_TRADE_USD = 30000
TRADE_WINDOW_SECONDS = 45

# =============================
# Strategy logic
# =============================

PATTERN_ENABLED = True

# Можно инвертировать сигналы стратегии
INVERT_SIGNALS = False

# =============================
# System timing
# =============================

HEARTBEAT_SECONDS = 60
COOLDOWN_SECONDS = 300
MAX_SILENCE_SECONDS = 60

# фильтр монет
MIN_SYMBOL_PRICE = 0.01
MIN_QUOTE_VOLUME = 10_000_000

# anti-FOMO
ANTI_FOMO_ENABLED = True
ANTI_FOMO_LOOKBACK = 5
ANTI_FOMO_MAX_MOVE_PCT = 0.025  # 2.5%

# cooldown
STOPLOSS_COOLDOWN_SECONDS = 3600  # 60 минут после стопа

# размер позиции по силе сигнала
WEAK_SIGNAL_POSITION_MULTIPLIER = 0.5
MEDIUM_SIGNAL_POSITION_MULTIPLIER = 0.75
STRONG_SIGNAL_POSITION_MULTIPLIER = 1.0

# ---------- Late entry protection ----------
LOW_PRICE_COIN_THRESHOLD = 0.10
LOW_PRICE_REQUIRES_RETEST = True

EXTENSION_FILTER_ENABLED = True
EXTENSION_LOOKBACK = 12

MAX_EXTENSION_FROM_LOCAL_LOW_PCT = 0.08
MAX_EXTENSION_FROM_LOCAL_HIGH_PCT = 0.08
