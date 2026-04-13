class SmartExitManager:
    def __init__(self):
        self.break_even_trigger = 0.4
        self.partial_tp_trigger = 0.6
        self.partial_close_fraction = 0.5
        self.trail_trigger = 0.8
        self.trail_gap_pct = 0.006

        self.min_hold_seconds = 120
        self.strong_hold_seconds = 300
        self.strong_signal_score = 0.85
        self.reverse_signal_confirmations = 3

        self.profit_be_partial_trigger = 0.30

        self.early_exit_enabled = False
        self.early_exit_check_seconds = 180
        self.early_exit_min_progress = 0.12
        self.adverse_orderflow_threshold = 0.18
        self.adverse_oi_bias_threshold = 0.12

    def progress_to_take(self, pos, price):
        entry = pos["entry"]
        take = pos["take"]

        if pos["side"] == "BUY":
            if take == entry:
                return 0.0
            return (price - entry) / (take - entry)

        if take == entry:
            return 0.0
        return (entry - price) / (entry - take)

    def unrealized_pnl(self, pos, price):
        if pos["side"] == "BUY":
            return (price - pos["entry"]) * pos["qty"]
        return (pos["entry"] - price) * pos["qty"]

    def pnl_pct_on_margin(self, pos, price):
        margin = pos.get("margin", 0.0)
        if margin <= 0:
            return 0.0
        return self.unrealized_pnl(pos, price) / margin

    def should_be_and_partial_on_profit(self, pos, price):
        if pos.get("partial_done"):
            return False
        return self.pnl_pct_on_margin(pos, price) >= self.profit_be_partial_trigger

    def should_move_to_break_even(self, pos, price):
        if pos.get("be_moved"):
            return False
        return self.progress_to_take(pos, price) >= self.break_even_trigger

    def apply_break_even(self, pos):
        old_stop = pos["stop"]

        if pos["side"] == "BUY":
            pos["stop"] = max(old_stop, pos["entry"])
        else:
            pos["stop"] = min(old_stop, pos["entry"])

        pos["be_moved"] = True
        return old_stop, pos["stop"]

    def should_partial_close(self, pos, price):
        if pos.get("partial_done"):
            return False
        return self.progress_to_take(pos, price) >= self.partial_tp_trigger

    def get_partial_fraction(self):
        return self.partial_close_fraction

    def should_activate_trailing(self, pos, price):
        return self.progress_to_take(pos, price) >= self.trail_trigger

    def apply_trailing(self, pos, price):
        old_stop = pos["stop"]

        if pos["side"] == "BUY":
            new_stop = price * (1 - self.trail_gap_pct)
            pos["stop"] = max(old_stop, new_stop, pos["entry"])
        else:
            new_stop = price * (1 + self.trail_gap_pct)
            pos["stop"] = min(old_stop, new_stop, pos["entry"])

        return old_stop, pos["stop"]

    def hold_seconds_for_position(self, pos):
        score = pos.get("signal_score", 0)

        if score >= self.strong_signal_score:
            return self.strong_hold_seconds

        return self.min_hold_seconds

    def should_early_exit_no_followthrough(self, pos, price):
        if not self.early_exit_enabled:
            return False

        opened_at = pos.get("opened_at", 0)
        if opened_at <= 0:
            return False

        if pos.get("partial_done"):
            return False

        elapsed = __import__("time").time() - opened_at
        if elapsed < self.early_exit_check_seconds:
            return False

        progress = self.progress_to_take(pos, price)
        return progress < self.early_exit_min_progress

    def should_exit_on_adverse_flow(self, pos, orderflow_bias=0.0, oi_bias=0.0):
        if pos.get("external_sync_only"):
            return False

        if pos["side"] == "BUY":
            return orderflow_bias <= -self.adverse_orderflow_threshold or oi_bias <= -self.adverse_oi_bias_threshold

        return orderflow_bias >= self.adverse_orderflow_threshold or oi_bias >= self.adverse_oi_bias_threshold

    def should_take_liquidity_target(self, pos, price):
        target = pos.get("liquidity_target")
        if target is None:
            return False
        if pos["side"] == "BUY":
            return price >= target
        return price <= target
