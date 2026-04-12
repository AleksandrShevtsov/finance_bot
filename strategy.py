from dataclasses import dataclass


@dataclass
class Signal:
    symbol: str
    side: str
    score: float
    reason: str
    entry_price: float | None = None
    signal_class: str = "REJECT"


def build_signal(
    symbol,
    trades,
    imbalance,
    oi_now,
    oi_prev,
    pattern=None,
    breakout_confirmation=None,
    trendline_confirmation=None,
    retest_confirmation=None,
):
    score = 0.0
    reasons = []
    entry_override = None

    if trades:
        buy = sum(t["usd_size"] for t in trades if t["side"] == "buy")
        sell = sum(t["usd_size"] for t in trades if t["side"] == "sell")

        if buy > sell * 1.15:
            score += 0.30
        if sell > buy * 1.15:
            score -= 0.30

        if imbalance > 0.10:
            score += 0.20
        if imbalance < -0.10:
            score -= 0.20

        if imbalance > 0.30:
            score += 0.15
        if imbalance < -0.30:
            score -= 0.15

        if oi_now and oi_prev:
            if oi_now > oi_prev * 1.001:
                score += 0.15
            if oi_now < oi_prev * 0.999:
                score -= 0.15

    if pattern:
        if pattern["direction"] == "BUY":
            score += 0.20
            reasons.append(pattern["pattern"])
        if pattern["direction"] == "SELL":
            score -= 0.20
            reasons.append(pattern["pattern"])

    if breakout_confirmation:
        if breakout_confirmation["direction"] == "BUY":
            score += 0.25
            reasons.append(breakout_confirmation.get("reason", "breakout"))
        if breakout_confirmation["direction"] == "SELL":
            score -= 0.25
            reasons.append(breakout_confirmation.get("reason", "breakout"))

    if trendline_confirmation:
        if trendline_confirmation["direction"] == "BUY":
            score += 0.25
            reasons.append(trendline_confirmation.get("reason", "trendline"))
            entry_override = trendline_confirmation.get("entry_price")
        if trendline_confirmation["direction"] == "SELL":
            score -= 0.25
            reasons.append(trendline_confirmation.get("reason", "trendline"))
            entry_override = trendline_confirmation.get("entry_price")

    if retest_confirmation:
        if retest_confirmation["direction"] == "BUY":
            score += 0.20
            reasons.append(retest_confirmation.get("reason", "retest"))
            entry_override = retest_confirmation.get("entry_price")
        if retest_confirmation["direction"] == "SELL":
            score -= 0.20
            reasons.append(retest_confirmation.get("reason", "retest"))
            entry_override = retest_confirmation.get("entry_price")

    if score >= 0.35:
        return Signal(symbol, "BUY", round(score, 3), "|".join(reasons) if reasons else "buy_setup", entry_override, "REJECT")

    if score <= -0.35:
        return Signal(symbol, "SELL", round(abs(score), 3), "|".join(reasons) if reasons else "sell_setup", entry_override, "REJECT")

    return Signal(symbol, "HOLD", round(abs(score), 3), "weak_signal", None, "REJECT")
