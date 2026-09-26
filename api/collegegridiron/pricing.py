from __future__ import annotations


def american_profit(stake: float, odds: int, result: str) -> float | None:
    if result == "pending":
        return None
    if result == "push" or stake is None:
        return 0.0
    if result == "loss":
        return -abs(stake)
    if odds >= 100:
        return abs(stake) * (odds / 100.0)
    if odds <= -100:
        return abs(stake) * (100.0 / abs(odds))
    return abs(stake)
