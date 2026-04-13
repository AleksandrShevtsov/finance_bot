import time

from market_structure import detect_market_structure, structure_allows_side
from breakout_volume_filter import breakout_volume_confirms
from signal_quality import classify_signal_quality

from entry_filters import blocked_by_anti_fomo
from late_entry_filters import is_low_price_coin, blocked_by_extension
from telegram_notifier import TelegramNotifier
from executors.bingx_real_executor import BingXRealExecutor
from connectors.binance_stream import BinanceMarketFeed
from connectors.bybit_client import BybitOIClient
from config import (
    EXECUTION_MODE,
    TELEGRAM_ENABLED,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    BINGX_ENABLED,
    BINGX_API_KEY,
    BINGX_SECRET_KEY,
    BINGX_BASE_URL,
    ANTI_FOMO_ENABLED,
    ANTI_FOMO_LOOKBACK,
    ANTI_FOMO_MAX_MOVE_PCT,
    LOW_PRICE_COIN_THRESHOLD,
    EXTENSION_FILTER_ENABLED,
    EXTENSION_LOOKBACK,
    MAX_EXTENSION_FROM_LOCAL_LOW_PCT,
    MAX_EXTENSION_FROM_LOCAL_HIGH_PCT,
    TOP_SYMBOLS_COUNT,
    SCAN_INTERVAL_SECONDS,
    START_BALANCE_USDT,
    FIXED_MARGIN_PCT,
    MAX_OPEN_POSITIONS,
    DAILY_LOSS_LIMIT_USDT,
    MAX_CONSECUTIVE_LOSSES,
    MAX_TOTAL_DRAWDOWN_PCT,
    STOP_LOSS_PCT,
    TAKE_PROFIT_PCT,
    INVERT_SIGNALS,
    HEARTBEAT_SECONDS,
    COOLDOWN_SECONDS,
    STOPLOSS_COOLDOWN_SECONDS,
    LOW_PRICE_REQUIRES_RETEST,
    BINANCE_WS_BASE,
    BYBIT_REST_BASE,
    MAX_SILENCE_SECONDS,
)
from utils import log, log_green, log_red, log_yellow, log_cyan
from exchange_momentum_scanner import ExchangeMomentumScanner
from binance_candles_feed import fetch_klines
from htf_trend_filter import detect_htf_trend
from breakout_detector import detect_range_breakout, confirm_breakout_with_orderflow
from trendline_detector import detect_trendline_breakout, confirm_trendline_breakout
from retest_detector import detect_retest_after_breakout
from fast_move_detector import detect_fast_move
from acceleration_detector import detect_price_acceleration
from strategy import build_signal
from position_manager import PositionManager
from smart_exit_manager import SmartExitManager
from trade_history import ensure_history_files, append_trade
from bot_state_store import BotStateStore
from feed_health import FeedHealthMonitor
from risk_guard import RiskGuard
from exchange_state_sync import ExchangeStateSync


class SmartMomentumPaperBot:
    def __init__(self):
        ensure_history_files()

        self.scanner = ExchangeMomentumScanner()
        self.balance = START_BALANCE_USDT
        self.symbols = []
        self.positions = {}
        self.cooldown_until = {}
        self.last_signal = {}
        self.last_heartbeat = 0.0
        self.market_feed = None
        self.oi_client = BybitOIClient(rest_base=BYBIT_REST_BASE)
        self.state_store = BotStateStore()
        self.feed_health = FeedHealthMonitor(max_feed_silence_seconds=MAX_SILENCE_SECONDS)
        self.risk_guard = RiskGuard(
            daily_loss_limit_usdt=DAILY_LOSS_LIMIT_USDT,
            max_consecutive_losses=MAX_CONSECUTIVE_LOSSES,
            max_total_drawdown_pct=MAX_TOTAL_DRAWDOWN_PCT,
        )

        self.position_manager = PositionManager(entry_pct=FIXED_MARGIN_PCT)
        self.exit_manager = SmartExitManager()

        self.notifier = TelegramNotifier(
            bot_token=TELEGRAM_BOT_TOKEN,
            chat_id=TELEGRAM_CHAT_ID,
            enabled=TELEGRAM_ENABLED,
        )

        self.executor = BingXRealExecutor(
            api_key=BINGX_API_KEY,
            secret_key=BINGX_SECRET_KEY,
            enabled=(EXECUTION_MODE == "real" and BINGX_ENABLED),
            base_url=BINGX_BASE_URL,
        )
        self.exchange_sync = ExchangeStateSync(
            executor=self.executor,
            enabled=(EXECUTION_MODE == "real" and BINGX_ENABLED),
        )

        self.restore_runtime_state()
        self.sync_with_exchange_state()

        self.notifier.send("🤖 Бот запущен")

    def invert_side_if_needed(self, side: str) -> str:
        if not INVERT_SIGNALS:
            return side
        if side == "BUY":
            return "SELL"
        if side == "SELL":
            return "BUY"
        return side

    def configure_market_feed(self):
        desired = list(self.symbols)
        if not desired:
            return

        current = self.market_feed.symbols if self.market_feed is not None else []
        if current == desired:
            return

        if self.market_feed is not None:
            self.market_feed.stop()

        self.market_feed = BinanceMarketFeed(desired, ws_base=BINANCE_WS_BASE)
        self.market_feed.start()
        log_cyan(f"ORDERFLOW FEED started for {len(desired)} symbols")

    def _exchange_position_side(self, side: str) -> str:
        return "LONG" if side == "BUY" else "SHORT"

    def _exchange_close_side(self, side: str) -> str:
        return "SELL" if side == "BUY" else "BUY"

    def _empty_position_slot(self, symbol: str):
        if symbol not in self.positions:
            self.positions[symbol] = None
        if symbol not in self.cooldown_until:
            self.cooldown_until[symbol] = 0
        if symbol not in self.last_signal:
            self.last_signal[symbol] = "NONE"

    def serialize_positions(self):
        data = {}
        for symbol, pos in self.positions.items():
            if pos is not None:
                data[symbol] = pos
        return data

    def save_runtime_state(self):
        self.state_store.save(
            {
                "balance": self.balance,
                "positions": self.serialize_positions(),
                "cooldown_until": self.cooldown_until,
                "last_signal": self.last_signal,
                "risk_guard": self.risk_guard.snapshot(),
            }
        )

    def restore_runtime_state(self):
        state = self.state_store.load()
        if not state:
            self.risk_guard.initialize_balance(self.balance)
            return

        self.balance = float(state.get("balance", self.balance))
        self.positions = state.get("positions", {}) or {}
        self.cooldown_until = state.get("cooldown_until", {}) or {}
        self.last_signal = state.get("last_signal", {}) or {}
        self.risk_guard.hydrate(state.get("risk_guard", {}) or {})
        self.risk_guard.initialize_balance(self.balance)

    def sync_with_exchange_state(self):
        remote = self.exchange_sync.map_by_symbol()
        if not remote:
            self.save_runtime_state()
            return

        for symbol in list(self.positions.keys()):
            pos = self.positions.get(symbol)
            if pos is None:
                continue
            if symbol not in remote:
                log_yellow(f"SYNC CLEAR {symbol} | reason=missing_on_exchange")
                self.positions[symbol] = None

        for symbol, remote_pos in remote.items():
            self._empty_position_slot(symbol)
            local = self.positions.get(symbol)
            if local is not None:
                continue

            qty = float(remote_pos.get("qty", 0.0) or 0.0)
            entry = float(remote_pos.get("entry_price", 0.0) or 0.0)
            position_side = str(remote_pos.get("position_side", "")).upper()
            side = "BUY" if "LONG" in position_side else "SELL"

            self.positions[symbol] = {
                "side": side,
                "entry": entry,
                "qty": qty,
                "stop": entry,
                "take": entry,
                "leverage": 1,
                "margin": 0.0,
                "notional": qty * entry,
                "risk_usdt": 0.0,
                "level_data": None,
                "be_moved": False,
                "partial_done": False,
                "trail_active": False,
                "opened_at": time.time(),
                "reason": "restored_from_exchange",
                "signal_score": 0.0,
                "signal_class": "SYNCED",
                "external_sync_only": True,
            }
            log_yellow(f"SYNC RESTORE {symbol} | side={side} | qty={qty:.4f} | entry={entry:.4f}")

        self.save_runtime_state()

    def _sync_reduce_on_exchange(self, symbol, pos, quantity):
        if EXECUTION_MODE != "real" or not BINGX_ENABLED:
            return True

        reduce_qty = round(quantity, 6)
        if reduce_qty <= 0:
            return False

        try:
            self.executor.reduce_position(
                symbol=symbol,
                side=self._exchange_close_side(pos["side"]),
                quantity=reduce_qty,
                position_side=self._exchange_position_side(pos["side"]),
            )
            return True
        except Exception as e:
            log_red(f"REAL CLOSE ERROR {symbol}: {e}")
            self.notifier.send(f"❌ REAL CLOSE ERROR {symbol}: {e}")
            return False

    def update_symbols(self):
        self.symbols = self.scanner.get_top_symbols(TOP_SYMBOLS_COUNT)
        self.configure_market_feed()

        log_cyan("UPDATED SYMBOL LIST:")
        for s in self.symbols:
            self._empty_position_slot(s)
            print(" -", s)

    def count_open_positions(self):
        return sum(1 for pos in self.positions.values() if pos is not None)

    def open_position(self, symbol, side, entry_price, score, reason, candles, signal_class="REJECT"):
        if self.positions.get(symbol) is not None:
            return

        if self.count_open_positions() >= MAX_OPEN_POSITIONS:
            log_yellow(f"SKIP {symbol} | reason=max_open_positions")
            return

        allowed, risk_reason = self.risk_guard.can_open_new_position(self.balance)
        if not allowed:
            log_yellow(f"SKIP {symbol} | reason={risk_reason}")
            return

        pos = self.position_manager.build_position(
            balance=self.balance,
            side=side,
            price=entry_price,
            sl_pct=STOP_LOSS_PCT,
            tp_pct=TAKE_PROFIT_PCT,
            score=score,
            candles=candles,
        )

        pos["opened_at"] = time.time()
        pos["reason"] = reason
        pos["signal_score"] = score
        pos["signal_class"] = signal_class

        self.positions[symbol] = pos

        log_green(
            f"OPEN {symbol} {side} | class={signal_class} | entry={pos['entry']:.4f} | "
            f"notional={pos.get('notional', 0.0):.2f} | "
            f"margin={pos.get('margin', 0.0):.2f} | "
            f"qty={pos['qty']:.4f} | lev=x{pos['leverage']} | "
            f"SL={pos['stop']:.4f} | TP={pos['take']:.4f}"
        )

        risk = abs(pos["entry"] - pos["stop"]) * pos["qty"]
        reward = abs(pos["take"] - pos["entry"]) * pos["qty"]

        self.notifier.send(
            f"🟢 OPEN {symbol}\n"
            f"Class: {signal_class}\n"
            f"Side: {side}\n"
            f"Entry: {pos['entry']:.6f}\n"
            f"SL: {pos['stop']:.6f}\n"
            f"TP: {pos['take']:.6f}\n"
            f"Qty: {pos['qty']:.4f}\n"
            f"Lev: x{pos['leverage']}\n"
            f"Notional: {pos.get('notional', 0.0):.2f} USDT\n"
            f"Risk: {risk:.2f} USDT\n"
            f"Reward: {reward:.2f} USDT\n"
            f"Reason: {reason}"
        )

        if EXECUTION_MODE == "real" and BINGX_ENABLED:
            try:
                leverage_side = self._exchange_position_side(side)
                self.executor.set_leverage(symbol, leverage_side, int(pos["leverage"]))
                self.executor.place_market_order(
                    symbol=symbol,
                    side=side,
                    quantity=round(pos["qty"], 6),
                    position_side=leverage_side,
                )
                self.notifier.send(f"✅ REAL ORDER SENT {symbol} {side}")
            except Exception as e:
                self.positions[symbol] = None
                self.notifier.send(f"❌ REAL ORDER ERROR {symbol}: {e}")
                return

        level_data = pos.get("level_data")
        if level_data:
            log_green(
                f"LEVELS {symbol} | source={level_data['source']} | "
                f"support={level_data['support']} | resistance={level_data['resistance']} | "
                f"rr={level_data['rr']:.2f}"
            )

        self.save_runtime_state()

    def close_position(self, symbol, price, reason):
        pos = self.positions.get(symbol)

        if pos is None:
            return

        if not self._sync_reduce_on_exchange(symbol, pos, pos["qty"]):
            return

        if pos["side"] == "BUY":
            pnl = (price - pos["entry"]) * pos["qty"]
        else:
            pnl = (pos["entry"] - price) * pos["qty"]

        self.balance += pnl

        append_trade(
            symbol=symbol,
            side=pos["side"],
            entry=pos["entry"],
            exit_price=price,
            qty=pos["qty"],
            pnl=pnl,
            reason=reason,
            balance_after=self.balance,
        )

        result = "PLUS" if pnl >= 0 else "MINUS"

        log_yellow(
            f"CLOSE {symbol} {pos['side']} | class={pos.get('signal_class', 'REJECT')} | entry={pos['entry']:.4f} | "
            f"exit={price:.4f} | qty={pos['qty']:.4f} | pnl={pnl:.2f} | "
            f"{result} | balance={self.balance:.2f} | reason={reason}"
        )

        self.notifier.send(
            f"🔴 CLOSE {symbol}\n"
            f"Class: {pos.get('signal_class', 'REJECT')}\n"
            f"Side: {pos['side']}\n"
            f"Entry: {pos['entry']:.6f}\n"
            f"Exit: {price:.6f}\n"
            f"Qty: {pos['qty']:.4f}\n"
            f"PnL: {pnl:.2f} USDT\n"
            f"Reason: {reason}\n"
            f"Balance: {self.balance:.2f}"
        )

        self.positions[symbol] = None

        if reason == "stop_loss":
            self.cooldown_until[symbol] = time.time() + STOPLOSS_COOLDOWN_SECONDS
        else:
            self.cooldown_until[symbol] = time.time() + COOLDOWN_SECONDS

        self.risk_guard.register_closed_trade(pnl, self.balance)
        self.save_runtime_state()

    def partial_close(self, symbol, price):
        pos = self.positions.get(symbol)

        if pos is None or pos.get("partial_done"):
            return

        fraction = self.exit_manager.get_partial_fraction()

        qty_close = pos["qty"] * fraction
        qty_left = pos["qty"] - qty_close

        if qty_close <= 0 or qty_left <= 0:
            return

        if not self._sync_reduce_on_exchange(symbol, pos, qty_close):
            return

        if pos["side"] == "BUY":
            pnl = (price - pos["entry"]) * qty_close
        else:
            pnl = (pos["entry"] - price) * qty_close

        self.balance += pnl

        append_trade(
            symbol=symbol,
            side=pos["side"],
            entry=pos["entry"],
            exit_price=price,
            qty=qty_close,
            pnl=pnl,
            reason="partial_close",
            balance_after=self.balance,
        )

        pos["qty"] = qty_left
        pos["partial_done"] = True
        pos["margin"] *= (1 - fraction)
        pos["notional"] *= (1 - fraction)

        log_cyan(
            f"PARTIAL {symbol} {pos['side']} | exit={price:.4f} | "
            f"closed_qty={qty_close:.4f} | remain_qty={qty_left:.4f} | "
            f"pnl={pnl:.2f} | balance={self.balance:.2f}"
        )

        self.notifier.send(
            f"🟡 PARTIAL CLOSE {symbol}\n"
            f"Class: {pos.get('signal_class', 'REJECT')}\n"
            f"Side: {pos['side']}\n"
            f"Entry: {pos['entry']:.6f}\n"
            f"Exit: {price:.6f}\n"
            f"Closed qty: {qty_close:.4f}\n"
            f"Remain qty: {qty_left:.4f}\n"
            f"PnL: {pnl:.2f} USDT\n"
            f"Balance: {self.balance:.2f}"
        )

        self.save_runtime_state()

    def manage_position(self, symbol, current_price, signal_side):
        pos = self.positions.get(symbol)
        if pos is None or current_price is None:
            return
        if pos.get("external_sync_only"):
            return

        if self.exit_manager.should_be_and_partial_on_profit(pos, current_price):
            if not pos.get("be_moved"):
                old_stop, new_stop = self.exit_manager.apply_break_even(pos)
                if old_stop != new_stop:
                    log_cyan(f"BE {symbol} | old_SL={old_stop:.4f} | new_SL={new_stop:.4f}")
                    self.notifier.send(f"🟦 BE {symbol}\nOld SL: {old_stop:.6f}\nNew SL: {new_stop:.6f}")

            if not pos.get("partial_done"):
                self.partial_close(symbol, current_price)

        pos = self.positions.get(symbol)
        if pos is None:
            return

        if self.exit_manager.should_move_to_break_even(pos, current_price):
            old_stop, new_stop = self.exit_manager.apply_break_even(pos)
            if old_stop != new_stop:
                log_cyan(f"BE {symbol} | old_SL={old_stop:.4f} | new_SL={new_stop:.4f}")
                self.notifier.send(f"🟦 BE {symbol}\nOld SL: {old_stop:.6f}\nNew SL: {new_stop:.6f}")

        if self.exit_manager.should_partial_close(pos, current_price):
            self.partial_close(symbol, current_price)

        pos = self.positions.get(symbol)
        if pos is None:
            return

        if self.exit_manager.should_activate_trailing(pos, current_price):
            old_stop, new_stop = self.exit_manager.apply_trailing(pos, current_price)
            if old_stop != new_stop:
                log_cyan(f"TRAIL {symbol} | old_SL={old_stop:.4f} | new_SL={new_stop:.4f}")
                self.notifier.send(f"🟪 TRAIL {symbol}\nOld SL: {old_stop:.6f}\nNew SL: {new_stop:.6f}")

        pos = self.positions.get(symbol)
        if pos is None:
            return

        if self.exit_manager.should_early_exit_no_followthrough(pos, current_price):
            self.close_position(symbol, current_price, "early_exit_no_followthrough")
            return

        if pos["side"] == "BUY":
            if current_price <= pos["stop"]:
                self.close_position(symbol, current_price, "stop_loss")
                return
            if current_price >= pos["take"]:
                self.close_position(symbol, current_price, "take_profit")
                return
        else:
            if current_price >= pos["stop"]:
                self.close_position(symbol, current_price, "stop_loss")
                return
            if current_price <= pos["take"]:
                self.close_position(symbol, current_price, "take_profit")
                return

        hold_seconds = self.exit_manager.hold_seconds_for_position(pos)
        if time.time() - pos["opened_at"] < hold_seconds:
            return

        if pos["side"] == "BUY" and signal_side == "SELL":
            self.close_position(symbol, current_price, "reverse_signal")
            return
        if pos["side"] == "SELL" and signal_side == "BUY":
            self.close_position(symbol, current_price, "reverse_signal")
            return

    def print_open_positions(self):
        any_open = False
        for symbol, pos in self.positions.items():
            if pos is None:
                continue

            any_open = True
            candles = fetch_klines(symbol, "15m", 5)
            now_price = candles[-1]["close"] if candles else 0.0

            if pos["side"] == "BUY":
                pnl = (now_price - pos["entry"]) * pos["qty"]
            else:
                pnl = (pos["entry"] - now_price) * pos["qty"]

            log_cyan(
                f"OPEN_POS {symbol} {pos['side']} | class={pos.get('signal_class', 'REJECT')} | entry={pos['entry']:.4f} | "
                f"now={now_price:.4f} | entry_usdt={pos.get('notional', 0.0):.2f} | "
                f"margin={pos.get('margin', 0.0):.2f} | risk_usdt={pos.get('risk_usdt', 0.0):.2f} | "
                f"SL={pos['stop']:.4f} | TP={pos['take']:.4f} | qty={pos['qty']:.4f} | "
                f"lev=x{pos['leverage']} | unrealized_pnl={pnl:.2f}"
            )

        if not any_open:
            log_cyan("OPEN_POS none")

    def analyze_symbol(self, symbol):
        htf_trend = detect_htf_trend(symbol)

        candles = fetch_klines(symbol, "15m", 200)
        if not candles:
            return

        structure = detect_market_structure(candles)
        volume_confirmed, last_vol, avg_vol = breakout_volume_confirms(candles)

        current_price = candles[-1]["close"]

        breakout = detect_range_breakout(candles)
        trendline = detect_trendline_breakout(candles)

        retest = None
        if trendline:
            retest = detect_retest_after_breakout(candles, trendline)
        elif breakout:
            retest = detect_retest_after_breakout(candles, breakout)

        fast_move = detect_fast_move(candles)
        acceleration = detect_price_acceleration(candles)

        trades = []
        imbalance = 0.0
        if self.market_feed is not None:
            trades, _, imbalance = self.market_feed.snapshot(symbol)

        oi_now, oi_prev = self.oi_client.get_oi_pair(symbol)
        self.feed_health.note_oi(symbol, oi_now)

        feed_ready = self.feed_health.feed_ready(self.market_feed)
        symbol_ready = self.feed_health.symbol_ready(self.market_feed, symbol)
        oi_ready = self.feed_health.oi_ready(symbol)

        if not symbol_ready:
            trades = []
            imbalance = 0.0
        if not oi_ready:
            oi_now = None
            oi_prev = None

        breakout_confirmation = confirm_breakout_with_orderflow(
            trades=trades,
            imbalance=imbalance,
            oi_now=oi_now,
            oi_prev=oi_prev,
            breakout=breakout,
        ) or breakout

        trendline_confirmation = confirm_trendline_breakout(
            trades=trades,
            imbalance=imbalance,
            oi_now=oi_now,
            oi_prev=oi_prev,
            breakout=trendline,
        ) or trendline
        retest_confirmation = retest
        pattern = None

        sig = build_signal(
            symbol=symbol,
            trades=trades,
            imbalance=imbalance,
            oi_now=oi_now,
            oi_prev=oi_prev,
            pattern=pattern,
            breakout_confirmation=breakout_confirmation,
            trendline_confirmation=trendline_confirmation,
            retest_confirmation=retest_confirmation,
        )

        if fast_move and sig.side != "HOLD" and fast_move["direction"] == sig.side:
            sig.score = max(sig.score, 0.42)
            sig.reason = f"{sig.reason}|{fast_move['reason']}"

        if acceleration and sig.side != "HOLD" and acceleration["direction"] == sig.side:
            sig.score = max(sig.score, 0.46)
            sig.reason = f"{sig.reason}|{acceleration['reason']}"

        sig.side = self.invert_side_if_needed(sig.side)

        if htf_trend == "BULL" and sig.side == "SELL":
            sig.side = "HOLD"
            sig.reason = "blocked_by_htf_bull"

        if htf_trend == "BEAR" and sig.side == "BUY":
            sig.side = "HOLD"
            sig.reason = "blocked_by_htf_bear"

        structure_ok = structure_allows_side(structure, sig.side) if sig.side in ("BUY", "SELL") else False

        signal_class, quality_reasons = classify_signal_quality(
            side=sig.side,
            score=sig.score,
            breakout_confirmation=breakout,
            trendline_confirmation=trendline,
            retest_confirmation=retest,
            fast_move=fast_move,
            acceleration=acceleration,
            htf_trend=htf_trend,
            volume_confirmed=volume_confirmed,
            structure_ok=structure_ok,
        )

        sig.signal_class = signal_class
        if quality_reasons:
            sig.reason = f"{sig.reason}|class={signal_class}|q={','.join(quality_reasons)}"
        else:
            sig.reason = f"{sig.reason}|class={signal_class}"

        if self.last_signal.get(symbol) != sig.side:
            log(
                f"{symbol} signal {self.last_signal.get(symbol, 'NONE')} -> {sig.side} | "
                f"trend={htf_trend} | class={sig.signal_class} | score={sig.score:.3f} | reason={sig.reason}"
            )
            self.last_signal[symbol] = sig.side

        if self.positions.get(symbol) is not None:
            self.manage_position(symbol, current_price, sig.side)
            return

        if time.time() < self.cooldown_until.get(symbol, 0):
            return

        if sig.side in ("BUY", "SELL"):
            if not feed_ready:
                log_yellow(f"BLOCKED {symbol} | reason=feed_not_ready")
                return
            if not symbol_ready:
                log_yellow(f"BLOCKED {symbol} | reason=symbol_feed_warmup")
                return
            if not oi_ready:
                log_yellow(f"BLOCKED {symbol} | reason=oi_not_ready")
                return

        if sig.side in ("BUY", "SELL"):
            if sig.signal_class == "REJECT":
                log_yellow(f"BLOCKED {symbol} | reason=signal_class_reject")
                return

            if breakout and not volume_confirmed:
                log_yellow(
                    f"BLOCKED {symbol} | reason=breakout_no_volume | last_vol={last_vol:.2f} | avg_vol={avg_vol:.2f}"
                )
                return

            if not structure_ok:
                log_yellow(f"BLOCKED {symbol} | reason=structure_filter | trend={structure['trend']}")
                return

        if LOW_PRICE_REQUIRES_RETEST:
            if is_low_price_coin(current_price, LOW_PRICE_COIN_THRESHOLD):
                if sig.side == "BUY" and retest is None:
                    log_yellow(
                        f"BLOCKED {symbol} | side=BUY | reason=low_price_requires_retest"
                    )
                    return

        if EXTENSION_FILTER_ENABLED and sig.side in ("BUY", "SELL"):
            blocked_ext, ext_value = blocked_by_extension(
                candles=candles,
                side=sig.side,
                lookback=EXTENSION_LOOKBACK,
                max_ext_low_pct=MAX_EXTENSION_FROM_LOCAL_LOW_PCT,
                max_ext_high_pct=MAX_EXTENSION_FROM_LOCAL_HIGH_PCT,
            )

            if blocked_ext:
                log_yellow(
                    f"BLOCKED {symbol} | side={sig.side} | extension={ext_value:.4f} | reason=too_extended"
                )
                return

        if sig.side in ("BUY", "SELL"):
            if ANTI_FOMO_ENABLED:
                blocked, move_pct = blocked_by_anti_fomo(
                    candles=candles,
                    side=sig.side,
                    lookback=ANTI_FOMO_LOOKBACK,
                    max_move_pct=ANTI_FOMO_MAX_MOVE_PCT,
                )

                if blocked:
                    log_yellow(
                        f"BLOCKED {symbol} | side={sig.side} | anti_fomo=True | recent_move={move_pct:.4f}"
                    )
                    return

            entry_price = sig.entry_price if sig.entry_price else current_price

            self.open_position(
                symbol=symbol,
                side=sig.side,
                entry_price=entry_price,
                score=sig.score,
                reason=sig.reason,
                candles=candles,
                signal_class=sig.signal_class,
            )

    def heartbeat(self):
        if self.market_feed is not None:
            self.market_feed.ensure_alive(MAX_SILENCE_SECONDS)
        self.sync_with_exchange_state()
        can_trade, risk_reason = self.risk_guard.can_open_new_position(self.balance)
        log_cyan(
            f"heartbeat | balance={self.balance:.2f} | open={self.count_open_positions()}/{MAX_OPEN_POSITIONS} | "
            f"mode={EXECUTION_MODE} | feed_ready={self.feed_health.feed_ready(self.market_feed)} | "
            f"trading_enabled={can_trade}{'' if can_trade else f' | reason={risk_reason}'}"
        )
        self.print_open_positions()
        self.save_runtime_state()

    def run(self):
        log("Smart Momentum Paper Bot started")

        while True:
            try:
                self.update_symbols()

                for symbol in self.symbols:
                    try:
                        self.analyze_symbol(symbol)
                    except Exception as e:
                        log_red(f"ERROR {symbol}: {e}")

                if time.time() - self.last_heartbeat > HEARTBEAT_SECONDS:
                    self.heartbeat()
                    self.last_heartbeat = time.time()

                time.sleep(SCAN_INTERVAL_SECONDS)

            except KeyboardInterrupt:
                raise
            except Exception as e:
                log_red(f"GLOBAL ERROR: {e}")
                self.notifier.send(f"❌ GLOBAL ERROR: {e}")
                time.sleep(10)


if __name__ == "__main__":
    bot = SmartMomentumPaperBot()
    bot.run()
