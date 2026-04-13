import os
from pathlib import Path

from dotenv import load_dotenv


load_dotenv(Path(__file__).with_name(".env"))


def _get_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _get_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


def _get_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return float(raw)


def _get_str(name: str, default: str) -> str:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw


EXECUTION_MODE = _get_str("EXECUTION_MODE", "paper")

TELEGRAM_ENABLED = _get_bool("TELEGRAM_ENABLED", True)
TELEGRAM_BOT_TOKEN = _get_str("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = _get_str("TELEGRAM_CHAT_ID", "")

BINGX_ENABLED = _get_bool("BINGX_ENABLED", False)
BINGX_API_KEY = _get_str("BINGX_API_KEY", "")
BINGX_SECRET_KEY = _get_str("BINGX_SECRET_KEY", "")
BINGX_BASE_URL = _get_str("BINGX_BASE_URL", "https://open-api.bingx.com")

TOP_SYMBOLS_COUNT = _get_int("TOP_SYMBOLS_COUNT", 20)
SCAN_INTERVAL_SECONDS = _get_int("SCAN_INTERVAL_SECONDS", 300)
MIN_VOLUME_FILTER = _get_float("MIN_VOLUME_FILTER", 5_000_000)

START_BALANCE_USDT = _get_float("START_BALANCE_USDT", 100.0)
MAX_OPEN_POSITIONS = _get_int("MAX_OPEN_POSITIONS", 10)
FIXED_MARGIN_PCT = _get_float("FIXED_MARGIN_PCT", 0.03)
DAILY_LOSS_LIMIT_USDT = _get_float("DAILY_LOSS_LIMIT_USDT", 0.0)
MAX_CONSECUTIVE_LOSSES = _get_int("MAX_CONSECUTIVE_LOSSES", 0)
MAX_TOTAL_DRAWDOWN_PCT = _get_float("MAX_TOTAL_DRAWDOWN_PCT", 0.0)

STOP_LOSS_PCT = _get_float("STOP_LOSS_PCT", 0.025)
TAKE_PROFIT_PCT = _get_float("TAKE_PROFIT_PCT", 0.05)

LEVERAGE_MODE = _get_str("LEVERAGE_MODE", "fixed")
FIXED_LEVERAGE = _get_int("FIXED_LEVERAGE", 20)

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

BINANCE_WS_BASE = _get_str("BINANCE_WS_BASE", "wss://fstream.binance.com")
BINANCE_REST_BASE = _get_str("BINANCE_REST_BASE", "https://fapi.binance.com")
BYBIT_REST_BASE = _get_str("BYBIT_REST_BASE", "https://api.bybit.com")

LARGE_TRADE_USD = _get_float("LARGE_TRADE_USD", 30000)
TRADE_WINDOW_SECONDS = _get_int("TRADE_WINDOW_SECONDS", 45)

PATTERN_ENABLED = _get_bool("PATTERN_ENABLED", True)
INVERT_SIGNALS = _get_bool("INVERT_SIGNALS", False)

HEARTBEAT_SECONDS = _get_int("HEARTBEAT_SECONDS", 60)
COOLDOWN_SECONDS = _get_int("COOLDOWN_SECONDS", 300)
MAX_SILENCE_SECONDS = _get_int("MAX_SILENCE_SECONDS", 60)

MIN_SYMBOL_PRICE = _get_float("MIN_SYMBOL_PRICE", 0.01)
MIN_QUOTE_VOLUME = _get_float("MIN_QUOTE_VOLUME", 10_000_000)

ANTI_FOMO_ENABLED = _get_bool("ANTI_FOMO_ENABLED", True)
ANTI_FOMO_LOOKBACK = _get_int("ANTI_FOMO_LOOKBACK", 5)
ANTI_FOMO_MAX_MOVE_PCT = _get_float("ANTI_FOMO_MAX_MOVE_PCT", 0.025)

STOPLOSS_COOLDOWN_SECONDS = _get_int("STOPLOSS_COOLDOWN_SECONDS", 3600)

WEAK_SIGNAL_POSITION_MULTIPLIER = _get_float("WEAK_SIGNAL_POSITION_MULTIPLIER", 0.5)
MEDIUM_SIGNAL_POSITION_MULTIPLIER = _get_float("MEDIUM_SIGNAL_POSITION_MULTIPLIER", 0.75)
STRONG_SIGNAL_POSITION_MULTIPLIER = _get_float("STRONG_SIGNAL_POSITION_MULTIPLIER", 1.0)

LOW_PRICE_COIN_THRESHOLD = _get_float("LOW_PRICE_COIN_THRESHOLD", 0.10)
LOW_PRICE_REQUIRES_RETEST = _get_bool("LOW_PRICE_REQUIRES_RETEST", True)

EXTENSION_FILTER_ENABLED = _get_bool("EXTENSION_FILTER_ENABLED", True)
EXTENSION_LOOKBACK = _get_int("EXTENSION_LOOKBACK", 12)
MAX_EXTENSION_FROM_LOCAL_LOW_PCT = _get_float("MAX_EXTENSION_FROM_LOCAL_LOW_PCT", 0.12)
MAX_EXTENSION_FROM_LOCAL_HIGH_PCT = _get_float("MAX_EXTENSION_FROM_LOCAL_HIGH_PCT", 0.12)
