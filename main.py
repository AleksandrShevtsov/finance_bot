import time

from market_structure import detect_market_structure, structure_allows_side
from breakout_volume_filter import breakout_volume_confirms
from signal_quality import classify_signal_quality

from entry_filters import blocked_by_anti_fomo
from late_entry_filters import is_low_price_coin, blocked_by_extension
from telegram_notifier import TelegramNotifier
from executors.bingx_real_executor import BingXRealExecutor
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
    MAX_OPEN_POSITIONS,
    STOP_LOSS_PCT,
    TAKE_PROFIT_PCT,
    INVERT_SIGNALS,
    HEARTBEAT_SECONDS,
    COOLDOWN_SECONDS,
    STOPLOSS_COOLDOWN_SECONDS,
    LOW_PRICE_REQUIRES_RETEST,
)
from utils import log, log_green, log_red, log_yellow, log_cyan
from exchange_momentum_scanner import ExchangeMomentumScanner
from binance_candles_feed import fetch_klines
from htf_trend_filter import detect_htf_trend
from breakout_detector import detect_range_breakout
from trendline_detector import detect_trendline_breakout
from retest_detector import detect_retest_after_breakout
from fast_move_detector import detect_fast_move
from acceleration_detector import detect_price_acceleration
from strategy import build_signal
from position_manager import PositionManager
from smart_exit_manager import SmartExitManager
from trade_history import ensure_history_files, append_trade


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

        # Оставляю твой текущий риск-процент
        self.position_manager = PositionManager(entry_pct=0.1)
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

        self.notifier.send("🤖 Бот запущен")

    def invert_side_if_needed(self, side: str) -> str:
        if not INVERT_SIGNALS:
            return side
        if side == "BUY":
            return "SELL"
        if side == "SELL":
            return "BUY"
        return side

    def update_symbols(self):
        self.symbols = self.scanner.get_top_symbols(TOP_SYMBOLS_COUNT)

        log_cyan("UPDATED SYMBOL LIST:")
        for s in self.symbols:
            if s not in self.positions:
                self.positions[s] = None
            if s not in self.cooldown_until:
                self.cooldown_until[s] = 0
            if s not in self.last_signal:
                self.last_signal[s] = "NONE"
            print(" -", s)

    def count_open_positions(self):
        return sum(1 for pos in self.positions.values() if pos is not None)

    def open_position(self, symbol, side, entry_price, score, reason, candles, signal_class="REJECT"):
        if self.positions.get(symbol) is not None:
            return

        if self.count_open_positions() >= MAX_OPEN_POSITIONS:
            log_yellow(f"SKIP {symbol} | reason=max_open_positions")
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
                leverage_side = "LONG" if side == "BUY" else "SHORT"
                self.executor.set_leverage(symbol, leverage_side, int(pos["leverage"]))
                self.executor.place_market_order(
                    symbol=symbol,
                    side=side,
                    quantity=round(pos["qty"], 6),
                    position_side=leverage_side,
                )
                self.notifier.send(f"✅ REAL ORDER SENT {symbol} {side}")
            except Exception as e:
                self.notifier.send(f"❌ REAL ORDER ERROR {symbol}: {e}")

        level_data = pos.get("level_data")
        if level_data:
            log_green(
                f"LEVELS {symbol} | source={level_data['source']} | "
                f"support={level_data['support']} | resistance={level_data['resistance']} | "
                f"rr={level_data['rr']:.2f}"
            )

    def close_position(self, symbol, price, reason):
        pos = self.positions.get(symbol)

        if pos is None:
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

    def partial_close(self, symbol, price):
        pos = self.positions.get(symbol)

        if pos is None or pos.get("partial_done"):
            return

        fraction = self.exit_manager.get_partial_fraction()

        qty_close = pos["qty"] * fraction
        qty_left = pos["qty"] - qty_close

        if qty_close <= 0 or qty_left <= 0:
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

    def manage_position(self, symbol, current_price, signal_side):
        pos = self.positions.get(symbol)
        if pos is None or current_price is None:
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

        breakout_confirmation = breakout
        trendline_confirmation = trendline
        retest_confirmation = retest
        pattern = None

        trades = []
        imbalance = 0.0
        oi_now = None
        oi_prev = None

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
        log_cyan(
            f"heartbeat | balance={self.balance:.2f} | open={self.count_open_positions()}/{MAX_OPEN_POSITIONS} | mode={EXECUTION_MODE}"
        )
        self.print_open_positions()

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
