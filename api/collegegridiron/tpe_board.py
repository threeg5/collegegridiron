"""TPE vs FanDuel board: expected score, player form vs defense, value vs price."""

from __future__ import annotations

import math

from collegegridiron.freshness import injury_freshness
from collegegridiron.markets import american_implied, list_game_lines, list_game_markets
from collegegridiron.slate import rows
from collegegridiron.snapshots import describe_move
from collegegridiron.tpe_context import apply_expected, context_for_player, load_game_context
from collegegridiron.tpe_sim import TEAM_SD, game_probs, score_draws
from collegegridiron.tpe_model import (
    ev_for_price,
    load_defense_book,
    load_player_weeks,
    load_position_priors,
    player_prop_model,
    value_lean,
)

BOOK = "FanDuel"
# NFL score-margin and total spread used only to turn TPE expected points into a %.
MARGIN_SD = 13.5
TOTAL_SD = 13.5
ALLOWED_STATS = {
    "passing_yards",
    "passing_tds",
    "carries",
    "rushing_yards",
    "rushing_tds",
    "receptions",
    "receiving_yards",
    "receiving_tds",
}


def _phi(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _p_greater(mean: float, threshold: float, sd: float) -> float:
    if sd <= 0:
        return 1.0 if mean > threshold else 0.0
    return 1.0 - _phi((threshold - mean) / sd)


def _round_p(value: float | None) -> float | None:
    if value is None:
        return None
    return round(max(0.0, min(1.0, value)), 3)


def _lean(tpe_pct: float | None, implied: float | None, ev: float | None, odds: int | None) -> str:
    return value_lean(tpe_pct, implied, ev, odds)


def _gap_pts(tpe_pct: float | None, implied: float | None) -> int | None:
    if tpe_pct is None or implied is None:
        return None
    return round((tpe_pct - implied) * 100)


def _pct_label(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{round(value * 100)}%"


def _spread_label(team: str, line: float | None) -> str:
    if line is None:
        return team
    if abs(float(line)) < 1e-9:
        return f"{team} PK"
    return f"{team} {float(line):+g}"


def _row(
    *,
    id: str,
    market: str,
    side: str,
    book: str,
    odds: int | None,
    implied: float | None,
    tpe: str,
    tpe_pct: float | None,
    sample: str,
    read: str,
    player_id: str | None = None,
    stat: str | None = None,
    ev: float | None = None,
    extra: dict | None = None,
) -> dict:
    lean = _lean(tpe_pct, implied, ev, odds)
    payload = {
        "id": id,
        "market": market,
        "side": side,
        "book": book,
        "odds": odds,
        "implied": implied,
        "tpe": tpe,
        "tpe_pct": tpe_pct,
        "gap_pts": _gap_pts(tpe_pct, implied),
        "ev": ev,
        "lean": lean,
        "sample": sample,
        "read": read,
        "player_id": player_id,
        "stat": stat,
    }
    if extra:
        payload.update(extra)
    return payload


def _with_move(extra: dict | None, move: dict | None) -> dict:
    payload = dict(extra or {})
    if move:
        payload.update(move)
    return payload


def _game_rows(game: dict, expected: dict | None, lines: list[dict], sim: dict | None = None) -> list[dict]:
    home = game.get("home_team") or "HOME"
    away = game.get("away_team") or "AWAY"
    by_market = {row["market"]: row for row in lines}
    μ = float(expected["margin"]) if expected and expected.get("margin") is not None else None
    total_μ = float(expected["total"]) if expected and expected.get("total") is not None else None
    notes = (expected or {}).get("context_notes") or []
    note_text = f" Gates: {'; '.join(notes[:6])}." if notes else ""
    sample = "5,000 game-script sims · rest/weather/outs in the expected"
    sim = sim or {}
    rows_out: list[dict] = []

    spread = by_market.get("spread")
    if spread:
        home_line = spread.get("home_line")
        away_line = spread.get("away_line")
        home_p = None
        away_p = None
        if sim.get("home_cover") is not None:
            home_p = _round_p(sim["home_cover"])
            away_p = _round_p(1.0 - home_p) if home_p is not None else None
        elif μ is not None and home_line is not None:
            home_p = _round_p(_p_greater(μ, -float(home_line), MARGIN_SD))
            away_p = _round_p(1.0 - home_p) if home_p is not None else None
        tpe_margin = (
            f"TPE {home} by {abs(μ):.1f}"
            if μ is not None and μ > 0.4
            else f"TPE {away} by {abs(μ):.1f}"
            if μ is not None and μ < -0.4
            else "TPE pick 'em"
            if μ is not None
            else "No TPE score yet"
        )
        if μ is None:
            read_spread = "FanDuel spread is in. TPE needs completed games before it can lean a side."
        else:
            read_spread = (
                f"TPE expected margin is {home} by {μ:.1f} after rest, weather, and missing regulars. "
                f"FanDuel hangs {_spread_label(home, home_line)}. "
                f"% comes from 5,000 simulated scores, not a single 13.5-point curve.{note_text}"
            )
        home_imp = american_implied(spread.get("home_odds"))
        away_imp = american_implied(spread.get("away_odds"))
        away_odds = spread.get("away_odds")
        home_odds = spread.get("home_odds")
        away_ev = ev_for_price(away_p, away_odds)
        home_ev = ev_for_price(home_p, home_odds)
        away_fair = float(μ) if μ is not None else None
        home_fair = -float(μ) if μ is not None else None
        away_move = describe_move(
            open_line=spread.get("open_away_line"),
            current_line=away_line,
            open_odds=spread.get("open_away_odds"),
            current_odds=away_odds,
            opened_at=spread.get("opened_at"),
            fair_line=away_fair,
            tpe_pct=away_p,
            line_style="spread",
        )
        home_move = describe_move(
            open_line=spread.get("open_home_line"),
            current_line=home_line,
            open_odds=spread.get("open_home_odds"),
            current_odds=home_odds,
            opened_at=spread.get("opened_at"),
            fair_line=home_fair,
            tpe_pct=home_p,
            line_style="spread",
        )
        rows_out.append(
            _row(
                id="spread-away",
                market="Spread",
                side=_spread_label(away, away_line),
                book=_odds_text(away_odds),
                odds=away_odds,
                implied=away_imp,
                tpe=tpe_margin,
                tpe_pct=away_p,
                ev=away_ev,
                sample=sample,
                read=_side_read("spread", away, away_imp, away_p, away_ev, away_odds, read_spread, away_move),
                extra=_with_move(None, away_move),
            )
        )
        rows_out.append(
            _row(
                id="spread-home",
                market="Spread",
                side=_spread_label(home, home_line),
                book=_odds_text(home_odds),
                odds=home_odds,
                implied=home_imp,
                tpe=tpe_margin,
                tpe_pct=home_p,
                ev=home_ev,
                sample=sample,
                read=_side_read("spread", home, home_imp, home_p, home_ev, home_odds, read_spread, home_move),
                extra=_with_move(None, home_move),
            )
        )

    total = by_market.get("total")
    if total and total.get("home_line") is not None:
        line = float(total["home_line"])
        if sim.get("over") is not None:
            over_p = _round_p(sim["over"])
        else:
            over_p = _round_p(_p_greater(total_μ, line, TOTAL_SD)) if total_μ is not None else None
        under_p = _round_p(1.0 - over_p) if over_p is not None else None
        tpe_total = f"TPE total {total_μ:.1f}" if total_μ is not None else "No TPE score yet"
        base = (
            f"FanDuel total is {line:g}. TPE’s expected score sums to {total_μ:.1f} after rest, weather, and outs. "
            f"Over/under % is 5,000 simulated games.{note_text}"
            if total_μ is not None
            else "FanDuel total is in. TPE needs completed games before it can lean over or under."
        )
        over_odds = total.get("over_odds")
        under_odds = total.get("under_odds")
        over_imp = american_implied(over_odds)
        under_imp = american_implied(under_odds)
        over_ev = ev_for_price(over_p, over_odds)
        under_ev = ev_for_price(under_p, under_odds)
        over_move = describe_move(
            open_line=total.get("open_home_line"),
            current_line=line,
            open_odds=total.get("open_over_odds"),
            current_odds=over_odds,
            opened_at=total.get("opened_at"),
            fair_line=total_μ,
            tpe_pct=over_p,
        )
        under_move = describe_move(
            open_line=total.get("open_home_line"),
            current_line=line,
            open_odds=total.get("open_under_odds"),
            current_odds=under_odds,
            opened_at=total.get("opened_at"),
            fair_line=total_μ,
            tpe_pct=under_p,
        )
        rows_out.append(
            _row(
                id="total-over",
                market="Total",
                side=f"Over {line:g}",
                book=_odds_text(over_odds),
                odds=over_odds,
                implied=over_imp,
                tpe=tpe_total,
                tpe_pct=over_p,
                ev=over_ev,
                sample=sample,
                read=_side_read("total", "Over", over_imp, over_p, over_ev, over_odds, base, over_move),
                extra=_with_move(None, over_move),
            )
        )
        rows_out.append(
            _row(
                id="total-under",
                market="Total",
                side=f"Under {line:g}",
                book=_odds_text(under_odds),
                odds=under_odds,
                implied=under_imp,
                tpe=tpe_total,
                tpe_pct=under_p,
                ev=under_ev,
                sample=sample,
                read=_side_read("total", "Under", under_imp, under_p, under_ev, under_odds, base, under_move),
                extra=_with_move(None, under_move),
            )
        )

    ml = by_market.get("moneyline")
    if ml:
        if sim.get("home_ml") is not None:
            home_p = _round_p(sim["home_ml"])
            away_p = _round_p(1.0 - home_p) if home_p is not None else None
        else:
            home_p = _round_p(_p_greater(μ, 0.0, MARGIN_SD)) if μ is not None else None
            away_p = _round_p(1.0 - home_p) if home_p is not None else None
        tpe_ml = (
            f"TPE ~{_pct_label(home_p)} {home}"
            if home_p is not None
            else "No TPE score yet"
        )
        base = (
            "Moneyline % is the share of 5,000 simulated scores where that team wins, using the same gated expected."
            if μ is not None
            else "FanDuel moneyline is in. TPE needs completed games before it can sketch a win rate."
        )
        home_odds = ml.get("home_odds")
        away_odds = ml.get("away_odds")
        home_imp = american_implied(home_odds)
        away_imp = american_implied(away_odds)
        home_ev = ev_for_price(home_p, home_odds)
        away_ev = ev_for_price(away_p, away_odds)
        away_move = describe_move(
            open_line=None,
            current_line=None,
            open_odds=ml.get("open_away_odds"),
            current_odds=away_odds,
            opened_at=ml.get("opened_at"),
            tpe_pct=away_p,
        )
        home_move = describe_move(
            open_line=None,
            current_line=None,
            open_odds=ml.get("open_home_odds"),
            current_odds=home_odds,
            opened_at=ml.get("opened_at"),
            tpe_pct=home_p,
        )
        rows_out.append(
            _row(
                id="ml-away",
                market="Moneyline",
                side=f"{away} {_odds_text(away_odds)}",
                book=_odds_text(away_odds),
                odds=away_odds,
                implied=away_imp,
                tpe=tpe_ml,
                tpe_pct=away_p,
                ev=away_ev,
                sample=sample,
                read=_side_read("moneyline", away, away_imp, away_p, away_ev, away_odds, base, away_move),
                extra=_with_move(None, away_move),
            )
        )
        rows_out.append(
            _row(
                id="ml-home",
                market="Moneyline",
                side=f"{home} {_odds_text(home_odds)}",
                book=_odds_text(home_odds),
                odds=home_odds,
                implied=home_imp,
                tpe=tpe_ml,
                tpe_pct=home_p,
                ev=home_ev,
                sample=sample,
                read=_side_read("moneyline", home, home_imp, home_p, home_ev, home_odds, base, home_move),
                extra=_with_move(None, home_move),
            )
        )
    return _featured_game_rows(rows_out)


def _featured_game_rows(rows_out: list[dict]) -> list[dict]:
    """One row per market — the side with more value (higher EV)."""
    picked: dict[str, dict] = {}
    rank = {"value": 3, "juiced": 2, "close": 1, "book": 0, "none": 0, "tpe": 3}
    for row in rows_out:
        key = row["market"]
        score = row.get("ev")
        score = float(score) if score is not None else -99.0
        prev = picked.get(key)
        if prev is None:
            picked[key] = row
            continue
        prev_score = prev.get("ev")
        prev_score = float(prev_score) if prev_score is not None else -99.0
        if score > prev_score or (
            score == prev_score and rank.get(row.get("lean") or "", 0) > rank.get(prev.get("lean") or "", 0)
        ):
            picked[key] = row
    order = ("Spread", "Total", "Moneyline")
    return [picked[name] for name in order if name in picked]


def _odds_text(odds: int | None) -> str:
    if odds is None:
        return "—"
    return f"+{odds}" if odds > 0 else str(odds)


def _side_read(
    _kind: str,
    side: str,
    implied: float | None,
    tpe_pct: float | None,
    ev: float | None,
    odds: int | None,
    base: str,
    move: dict | None = None,
) -> str:
    parts = [base]
    if implied is None or tpe_pct is None:
        parts.append("TPE helps you read the spot. You still make the price decision.")
        return " ".join(parts)
    parts.append(f"FanDuel prices {side} around {_pct_label(implied)} (juice still in).")
    parts.append(f"TPE sits near {_pct_label(tpe_pct)}.")
    parts.append(_value_sentence(tpe_pct, implied, ev, odds))
    if move and move.get("move_kind") not in (None, "flat") and move.get("move_label"):
        parts.append(move["move_label"] + ".")
    parts.append("TPE helps you read the spot. You still make the price decision.")
    return " ".join(parts)


def _ev_label(ev: float | None) -> str:
    if ev is None:
        return "—"
    return f"{ev:+.2f}"


def _value_sentence(tpe_pct: float, implied: float, ev: float | None, odds: int | None) -> str:
    lean = value_lean(tpe_pct, implied, ev, odds)
    price = _odds_text(odds)
    if lean == "value":
        return (
            f"Value: TPE is above the break-even at {price} "
            f"(EV {_ev_label(ev)} per $1). That can be a small number, not a lock."
        )
    if lean == "juiced":
        return (
            f"Likely is not enough here. {price} already asks {_pct_label(implied)}; "
            f"EV {_ev_label(ev)}. Heavy juice can make a probable play a bad wager."
        )
    if lean == "book":
        return f"The price is hotter than TPE (EV {_ev_label(ev)}). Not worth it at this number."
    return f"TPE and the price are close (EV {_ev_label(ev)}). The spot still has to earn the bet."


def _opp_label(mult: float | None, opponent: str | None) -> str:
    if mult is None or not opponent:
        return "this week's defense is not on file"
    if mult >= 1.06:
        return f"{opponent}'s defense has been softer than last year's league ({mult:.2f}×)"
    if mult <= 0.94:
        return f"{opponent}'s defense has been tighter than last year's league ({mult:.2f}×)"
    return f"{opponent}'s defense is near last year's league ({mult:.2f}×)"


def _prop_read(
    player_name: str,
    stat_label: str,
    line: float,
    model: dict,
    opponent: str | None,
    odds: int | None,
    move: dict | None = None,
) -> str:
    if not model.get("last_year_mean") and not model.get("sample_size"):
        return f"No regular-season games on file for {player_name} {stat_label}. Keep this as a sketch."
    parts: list[str] = []
    prior = model.get("last_year_mean")
    if model.get("prior_source") == "last_year" and prior is not None:
        parts.append(
            f"Last year {player_name} sat at {prior:g} {stat_label} per game — that is 1.00, the expectation."
        )
    elif model.get("prior_source") == "position" and prior is not None:
        parts.append(
            f"No last-year sample for {player_name}. TPE starts at the position picture ({prior:g} {stat_label})."
        )
    if model.get("this_year_games"):
        parts.append(
            f"Form is {model.get('form_index'):.2f} after {model['this_year_games']} game"
            f"{'s' if model['this_year_games'] != 1 else ''} this year "
            "(remembers last year, leans on recent weeks, each week vs that week's defense)."
        )
    elif prior is not None:
        parts.append("No completed games this year yet — the number is still last year's picture.")
    if model.get("expected") is not None:
        extra = []
        if model.get("situation_mult") not in (None, 1.0) or model.get("usage_mult") not in (None, 1.0):
            extra.append(
                f"spot/usage {model.get('situation_mult') or 1:.2f}× / {model.get('usage_mult') or 1:.2f}×"
            )
        parts.append(
            f"This week expected {model['expected']:g} after {_opp_label(model.get('opp_mult'), opponent)}"
            + (f", then {', '.join(extra)}" if extra else "")
            + "."
        )
        notes = [note for note in (model.get("context_notes") or []) if note]
        if notes:
            parts.append("In the number: " + "; ".join(notes[:6]) + ".")
    if model.get("sims"):
        parts.append(
            f"TPE % is {model['sims']:,} game-script draws (trailing throws, leading runs), not a one-shot curve."
        )
    if model.get("tpe_pct") is not None:
        parts.append(f"TPE puts the over {line:g} near {_pct_label(model['tpe_pct'])}.")
    implied = model.get("implied")
    if implied is None:
        parts.append("FanDuel odds are missing on this row.")
    else:
        parts.append(f"FanDuel prices the over around {_pct_label(implied)} at {_odds_text(odds)} (juice still in).")
        if model.get("overround") is not None:
            parts.append(f"Both sides take {_pct_label(model['overround'])} juice.")
        if model.get("tpe_pct") is not None:
            parts.append(_value_sentence(model["tpe_pct"], implied, model.get("ev"), odds))
    sample = model.get("sample_size") or 0
    if sample:
        parts.append(
            f"Raw history: cleared {line:g} in {model.get('hits')}/{sample} REG games "
            f"({_pct_label(model.get('hit_rate'))}) — that is the old count, not this week's number."
        )
    if move and move.get("move_kind") not in (None, "flat") and move.get("move_label"):
        parts.append(move["move_label"] + ".")
    parts.append("TPE helps you read the spot. You still make the price decision.")
    return " ".join(parts)


def _player_opponent(player: dict, game: dict) -> str | None:
    team = player.get("latest_team")
    home = game.get("home_team")
    away = game.get("away_team")
    if team == home:
        return away
    if team == away:
        return home
    return None


def _prop_tpe_label(model: dict) -> str:
    if model.get("tpe_pct") is None:
        return "—"
    if model.get("expected") is not None:
        return f"{_pct_label(model['tpe_pct'])} · exp {model['expected']:g}"
    return _pct_label(model["tpe_pct"])


def _prop_sample(model: dict) -> str:
    games = model.get("this_year_games") or 0
    sims = model.get("sims") or 0
    tail = f" · {sims:,} sims" if sims else ""
    if model.get("prior_source") == "last_year":
        return f"LY + {games} this year{tail}" if games else f"Last year (1.00){tail}"
    if model.get("prior_source") == "position":
        return f"Position prior + {games} this year{tail}" if games else f"Position prior{tail}"
    if model.get("sample_size"):
        return f"{model['sample_size']} REG games{tail}"
    return "No REG sample"


def _prop_rows(
    conn,
    game: dict,
    stats: dict[str, str],
    stored: list[dict],
    homes_away: tuple | None = None,
    ctx: dict | None = None,
) -> list[dict]:
    if not stored:
        return []
    ids = sorted({row["player_id"] for row in stored})
    needed_stats = sorted({row["stat"] for row in stored if row.get("stat") in ALLOWED_STATS})
    names: dict[str, dict] = {}
    if ids:
        placeholders = ",".join("?" for _ in ids)
        for row in rows(
            conn,
            f"""
            SELECT player_id, player_name, position, latest_team
            FROM players
            WHERE player_id IN ({placeholders})
            """,
            tuple(ids),
        ):
            names[row["player_id"]] = row
    season = int(game["season"])
    week = int(game["week"])
    last_year = season - 1
    defense = load_defense_book(conn, last_year, season)
    priors = load_position_priors(conn, last_year, needed_stats)
    by_player = load_player_weeks(conn, ids, needed_stats, last_year, season)
    ctx = ctx or load_game_context(conn, game)
    homes = homes_away[0] if homes_away else None
    aways = homes_away[1] if homes_away else None
    out = []
    home = game.get("home_team")
    away = game.get("away_team")
    pos_rank = {"QB": 0, "RB": 1, "WR": 2, "TE": 3}
    for market in stored:
        player = names.get(market["player_id"]) or {
            "player_id": market["player_id"],
            "player_name": market["player_id"],
            "position": None,
            "latest_team": None,
        }
        opponent = _player_opponent(player, game)
        spot = context_for_player(ctx, player, game, market["stat"])
        model = player_prop_model(
            weeks=by_player.get(market["player_id"]) or [],
            stat=market["stat"],
            line=float(market["line"]),
            season=season,
            week=week,
            opponent=opponent,
            defense=defense,
            priors=priors,
            odds=market.get("over_odds"),
            under_odds=market.get("under_odds"),
            situation_mult=spot["situation"],
            usage_mult=spot["usage"],
            context_notes=spot["notes"],
            is_home=spot["is_home"],
            homes=homes,
            aways=aways,
            game_id=game.get("game_id"),
        )
        implied = model.get("implied")
        label = stats.get(market["stat"], market["stat"])
        move = describe_move(
            open_line=market.get("open_line"),
            current_line=float(market["line"]),
            open_odds=market.get("open_over_odds"),
            current_odds=market.get("over_odds"),
            opened_at=market.get("opened_at"),
            fair_line=model.get("expected"),
            tpe_pct=model.get("tpe_pct"),
        )
        out.append(
            {
                **_row(
                    id=f"prop-{market['player_id']}-{market['stat']}",
                    market=label,
                    side=f"{player['player_name']} over {market['line']:g}",
                    book=_odds_text(market.get("over_odds")),
                    odds=market.get("over_odds"),
                    implied=implied,
                    tpe=_prop_tpe_label(model),
                    tpe_pct=model.get("tpe_pct"),
                    ev=model.get("ev"),
                    sample=_prop_sample(model),
                    read=_prop_read(
                        player["player_name"],
                        label,
                        float(market["line"]),
                        model,
                        opponent,
                        market.get("over_odds"),
                        move,
                    ),
                    player_id=player["player_id"],
                    stat=market["stat"],
                    extra=_with_move(
                        {
                            "form_index": model.get("form_index"),
                            "last_year_mean": model.get("last_year_mean"),
                            "expected": model.get("expected"),
                            "opp_mult": model.get("opp_mult"),
                            "situation_mult": model.get("situation_mult"),
                            "usage_mult": model.get("usage_mult"),
                            "opp_team": opponent,
                            "this_year_games": model.get("this_year_games"),
                            "hit_rate": model.get("hit_rate"),
                        },
                        move,
                    ),
                ),
                "player_name": player["player_name"],
                "position": player.get("position"),
                "latest_team": player.get("latest_team"),
                "line": market["line"],
                "_sort": (
                    0 if player.get("latest_team") == away else 1 if player.get("latest_team") == home else 2,
                    pos_rank.get(player.get("position") or "", 9),
                    player.get("player_name") or "",
                    label,
                ),
            }
        )
    out.sort(key=lambda row: row.pop("_sort"))
    return out


def build_tpe_board(conn, game: dict, expected: dict | None, stats: dict[str, str]) -> dict:
    game_id = game.get("game_id") or ""
    lines = list_game_lines(game_id)
    stored = [row for row in list_game_markets(game_id) if row.get("stat") in ALLOWED_STATS]
    ctx = load_game_context(conn, game)
    if expected and not expected.get("context_notes"):
        expected = apply_expected(expected, ctx)
    homes_away = None
    sim = None
    if expected and expected.get("home_points") is not None and expected.get("away_points") is not None:
        sd = TEAM_SD * float(ctx.get("sd") or 1.0)
        homes_away = score_draws(
            float(expected["home_points"]),
            float(expected["away_points"]),
            game_id=game_id,
            sd=sd,
        )
        spread = next((row for row in lines if row["market"] == "spread"), None)
        total = next((row for row in lines if row["market"] == "total"), None)
        sim = game_probs(
            homes_away[0],
            homes_away[1],
            home_spread=spread.get("home_line") if spread else None,
            total_line=total.get("home_line") if total else None,
        )
    game_rows = _game_rows(game, expected, lines, sim)
    prop_rows = _prop_rows(conn, game, stats, stored, homes_away, ctx)
    stamps = [row.get("updated_at") for row in lines + stored if row.get("updated_at")]
    spread = next((row for row in lines if row["market"] == "spread"), None)
    total = next((row for row in lines if row["market"] == "total"), None)
    return {
        "book": BOOK,
        "snapshot_at": max(stamps) if stamps else None,
        "method": (
            "Expected points start at team PPG + opponent PAPG − league + home field, then rest, "
            "weather, travel, and missing regulars (capped gates). Player props still start at last "
            "year (1.00) and form vs defense, then the same gates plus usage if a teammate is out. "
            "Spread, total, moneyline, and prop % are 5,000 simulated scores with game script "
            "(trailing throws, leading runs) versus the juiced FanDuel price. Open is the first "
            "FanDuel snapshot stored on this desk, not the book's week-open unless that pull was early."
        ),
        "context_notes": (expected or {}).get("context_notes") or ctx.get("notes") or [],
        "fanduel_spread": spread.get("home_line") if spread else None,
        "fanduel_total": total.get("home_line") if total else None,
        "fanduel_spread_open": spread.get("open_home_line") if spread else None,
        "fanduel_total_open": total.get("open_home_line") if total else None,
        "injury_freshness": injury_freshness(conn, game),
        "game_rows": game_rows,
        "prop_rows": prop_rows,
    }
