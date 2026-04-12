from config import LEVERAGE_MODE, FIXED_LEVERAGE
from entry_filters import signal_size_multiplier
from levels import calculate_sl_tp_from_levels


class PositionManager:
    def __init__(self, entry_pct=0.03):
        self.entry_pct = entry_pct

    def dynamic_leverage(self, score):
        if score >= 0.8:
            return 20
        if score >= 0.6:
            return 15
        return 10

    def get_leverage(self, score):
        if LEVERAGE_MODE == "fixed":
            return FIXED_LEVERAGE
        return self.dynamic_leverage(score)

    def build_position(self, balance, side, price, sl_pct, tp_pct, score, candles=None):
        lev = self.get_leverage(score)

        size_mult = signal_size_multiplier(score)
        margin = balance * self.entry_pct * size_mult
        notional = margin * lev
        qty = notional / price if price else 0.0

        level_data = None

        if candles:
            level_data = calculate_sl_tp_from_levels(
                side=side,
                entry_price=price,
                candles=candles,
                fallback_sl_pct=sl_pct,
                fallback_tp_pct=tp_pct,
                level_buffer_pct=0.002,
                min_rr=1.5,
            )
            stop = level_data["stop"]
            take = level_data["take"]
        else:
            if side == "BUY":
                stop = price * (1 - sl_pct)
                take = price * (1 + tp_pct)
            else:
                stop = price * (1 + sl_pct)
                take = price * (1 - tp_pct)

        if side == "BUY":
            risk_usdt = max(0.0, (price - stop) * qty)
        else:
            risk_usdt = max(0.0, (stop - price) * qty)

        return {
            "side": side,
            "entry": price,
            "qty": qty,
            "stop": stop,
            "take": take,
            "leverage": lev,
            "margin": margin,
            "notional": notional,
            "risk_usdt": risk_usdt,
            "level_data": level_data,
            "be_moved": False,
            "partial_done": False,
            "trail_active": False,
        }