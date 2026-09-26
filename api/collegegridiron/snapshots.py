"""First FanDuel snapshot on this desk vs the latest refresh.

This is not the book's week-open unless the game was pulled that early.
"""

from __future__ import annotations

def _implied(odds: int | None) -> float | None:
    if odds is None:
        return None
    try:
        price = int(odds)
    except (TypeError, ValueError):
        return None
    if price >= 100:
        return round(100.0 / (price + 100.0), 3)
    if price <= -100:
        return round(abs(price) / (abs(price) + 100.0), 3)
    return None

LINE_EPS = 0.24
PCT_EPS = 0.015


def _num(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _odds_text(odds: int | None) -> str:
    if odds is None:
        return "—"
    return f"+{odds}" if odds > 0 else str(odds)


def _line_text(line: float | None) -> str:
    if line is None:
        return "—"
    value = float(line)
    if abs(value) < 1e-9:
        return "PK"
    if value == int(value):
        return f"{value:+g}" if value != 0 else "PK"
    return f"{value:g}"


def same_line(left: float | None, right: float | None) -> bool:
    if left is None or right is None:
        return left is None and right is None
    return abs(float(left) - float(right)) < 1e-9


def first_open(existing: dict | None, incoming: dict, pairs: list[tuple[str, str]], now: str) -> dict:
    """Keep the first stored numbers. Null opens backfill from the prior current."""
    if not existing:
        out = {open_key: incoming.get(cur_key) for cur_key, open_key in pairs}
        out["opened_at"] = now
        return out
    out = {}
    had_open = False
    for cur_key, open_key in pairs:
        prev_open = existing.get(open_key)
        if prev_open is not None:
            out[open_key] = prev_open
            had_open = True
        elif existing.get(cur_key) is not None:
            out[open_key] = existing.get(cur_key)
            had_open = True
        else:
            out[open_key] = incoming.get(cur_key)
    out["opened_at"] = existing.get("opened_at") or existing.get("created_at") or now
    if not had_open and not existing.get("opened_at"):
        out["opened_at"] = now
    return out


def move_kind(open_line: float | None, current_line: float | None, open_odds: int | None, current_odds: int | None) -> str:
    line_changed = not same_line(open_line, current_line) and (open_line is not None or current_line is not None)
    odds_changed = open_odds is not None and current_odds is not None and int(open_odds) != int(current_odds)
    if line_changed and odds_changed:
        return "both"
    if line_changed:
        return "number"
    if odds_changed:
        return "juice"
    return "flat"


def vs_tpe_line(open_line: float | None, current_line: float | None, fair: float | None) -> str | None:
    if fair is None or open_line is None or current_line is None:
        return None
    open_gap = abs(float(open_line) - float(fair))
    now_gap = abs(float(current_line) - float(fair))
    if abs(open_gap - now_gap) <= LINE_EPS:
        return "flat"
    return "toward" if now_gap < open_gap else "away"


def vs_tpe_pct(open_odds: int | None, current_odds: int | None, tpe_pct: float | None) -> str | None:
    if tpe_pct is None:
        return None
    open_p = _implied(open_odds)
    now_p = _implied(current_odds)
    if open_p is None or now_p is None:
        return None
    open_gap = abs(open_p - float(tpe_pct))
    now_gap = abs(now_p - float(tpe_pct))
    if abs(open_gap - now_gap) <= PCT_EPS:
        return "flat"
    return "toward" if now_gap < open_gap else "away"


def describe_move(
    *,
    open_line: float | None,
    current_line: float | None,
    open_odds: int | None,
    current_odds: int | None,
    opened_at: str | None = None,
    fair_line: float | None = None,
    tpe_pct: float | None = None,
    line_style: str = "number",
) -> dict:
    kind = move_kind(open_line, current_line, open_odds, current_odds)
    vs = vs_tpe_line(open_line, current_line, fair_line)
    if vs in (None, "flat"):
        vs = vs_tpe_pct(open_odds, current_odds, tpe_pct) or vs
    line_delta = None
    if open_line is not None and current_line is not None:
        line_delta = round(float(current_line) - float(open_line), 3)
    odds_delta = None
    if open_odds is not None and current_odds is not None:
        odds_delta = int(current_odds) - int(open_odds)

    if line_style == "spread":
        open_txt = _line_text(open_line)
        now_txt = _line_text(current_line)
    elif open_line is None and current_line is None:
        open_txt = ""
        now_txt = ""
    else:
        open_txt = f"{float(open_line):g}" if open_line is not None else "—"
        now_txt = f"{float(current_line):g}" if current_line is not None else "—"

    if kind == "flat" or (open_line is None and open_odds is None):
        label = "No move since first snapshot"
    else:
        kind_word = {"number": "number", "juice": "juice", "both": "number + juice"}.get(kind, kind)
        vs_word = f" · {vs} TPE" if vs in {"toward", "away"} else ""
        left = " ".join(part for part in (open_txt, _odds_text(open_odds)) if part and part != "—")
        right = " ".join(part for part in (now_txt, _odds_text(current_odds)) if part and part != "—")
        label = f"Open {left or '—'} -> {right or '—'} ({kind_word}{vs_word})"
    return {
        "open_line": _num(open_line),
        "open_odds": _int(open_odds),
        "opened_at": opened_at,
        "line_move": line_delta,
        "odds_move": odds_delta,
        "move_kind": kind,
        "vs_tpe": vs,
        "move_label": label,
    }
