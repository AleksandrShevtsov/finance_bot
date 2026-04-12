def classify_signal_quality(
    side,
    score,
    breakout_confirmation=None,
    trendline_confirmation=None,
    retest_confirmation=None,
    fast_move=None,
    acceleration=None,
    htf_trend=None,
    volume_confirmed=False,
    structure_ok=False,
):
    reasons = []

    if retest_confirmation:
        reasons.append("retest")
    if breakout_confirmation:
        reasons.append("breakout")
    if trendline_confirmation:
        reasons.append("trendline")
    if fast_move and fast_move.get("direction") == side:
        reasons.append("fast_move")
    if acceleration and acceleration.get("direction") == side:
        reasons.append("acceleration")
    if volume_confirmed:
        reasons.append("volume")
    if structure_ok:
        reasons.append("structure")

    strong_htf = (
        (side == "BUY" and htf_trend == "BULL") or
        (side == "SELL" and htf_trend == "BEAR")
    )

    if strong_htf:
        reasons.append("htf")

    if retest_confirmation and volume_confirmed and structure_ok and strong_htf and score >= 0.45:
        return "A", reasons

    if (breakout_confirmation or trendline_confirmation) and structure_ok and score >= 0.38:
        return "B", reasons

    if (fast_move or acceleration) and score >= 0.35:
        return "C", reasons

    return "REJECT", reasons


def quality_position_multiplier(signal_class):
    if signal_class == "A":
        return 1.0
    if signal_class == "B":
        return 0.7
    if signal_class == "C":
        return 0.4
    return 0.0
