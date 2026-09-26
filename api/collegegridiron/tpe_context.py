"""Rest, weather, and missing regulars as capped gates on TPE expected values."""

from __future__ import annotations

SKILL = {
    "QB": {"QB"},
    "RB": {"RB", "FB", "HB"},
    "WR": {"WR"},
    "TE": {"TE"},
}
OL = {"T", "G", "C", "OT", "OG", "OL"}
FRONT = {"DE", "DT", "NT", "DL", "EDGE", "LB", "OLB", "ILB", "MLB"}
SECONDARY = {"CB", "S", "FS", "SS", "DB", "SAF"}
PASS_STATS = {
    "passing_yards",
    "passing_tds",
    "receptions",
    "receiving_yards",
    "receiving_tds",
}
RUSH_STATS = {"carries", "rushing_yards", "rushing_tds"}


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _pos(row: dict) -> str:
    return str(row.get("position") or "").upper().strip()


def _indoor(roof: str | None) -> bool:
    text = (roof or "").lower()
    if not text or text in {"outdoors", "outdoor", "open"}:
        return False
    if "open" in text:
        return False
    return "dome" in text or text in {"indoor", "closed"} or "retract" in text


def _num(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _rest_mult(days: float | None) -> tuple[float, float, str | None]:
    if days is None:
        return 1.0, 1.0, None
    if days <= 4:
        return 0.96, 0.97, f"short rest ({days:.0f}d)"
    if days <= 5:
        return 0.98, 0.99, f"short rest ({days:.0f}d)"
    if days >= 10:
        return 1.02, 1.015, f"extra rest ({days:.0f}d)"
    return 1.0, 1.0, None


def _weather(game: dict) -> dict:
    indoor = _indoor(game.get("roof"))
    wind = _num(game.get("wind"))
    temp = _num(game.get("temp"))
    pass_m = 1.0
    rush_m = 1.0
    score_m = 1.0
    sd_m = 1.0
    notes: list[str] = []
    if indoor:
        if game.get("roof"):
            notes.append(str(game.get("roof")))
        return {"pass": pass_m, "rush": rush_m, "score": score_m, "sd": sd_m, "notes": notes, "indoor": True}
    if wind is not None and wind >= 25:
        pass_m *= 0.88
        rush_m *= 1.06
        score_m *= 0.92
        sd_m *= 0.86
        notes.append(f"wind {wind:.0f} mph")
    elif wind is not None and wind >= 18:
        pass_m *= 0.93
        rush_m *= 1.04
        score_m *= 0.95
        sd_m *= 0.90
        notes.append(f"wind {wind:.0f} mph")
    elif wind is not None and wind >= 12:
        pass_m *= 0.97
        rush_m *= 1.02
        score_m *= 0.98
        sd_m *= 0.95
        notes.append(f"wind {wind:.0f} mph")
    if temp is not None and temp <= 20:
        pass_m *= 0.96
        score_m *= 0.97
        notes.append(f"{temp:.0f}°")
    elif temp is not None and temp <= 32:
        pass_m *= 0.98
        notes.append(f"{temp:.0f}°")
    return {"pass": pass_m, "rush": rush_m, "score": score_m, "sd": sd_m, "notes": notes, "indoor": False}


def _travel_note(game: dict, home: bool) -> tuple[float, str | None]:
    key = "home_travel" if home else "away_travel"
    travel = (game.get(key) or "none").lower()
    if travel == "overseas":
        return 0.97, "overseas"
    if travel == "long":
        return 0.99, "long travel"
    return 1.0, None


def _share(missing: list[dict], positions: set[str]) -> float:
    total = 0.0
    for row in missing:
        if _pos(row) in positions:
            total += float(row.get("snap_pct_recent") or 0) / 100.0
    return total


def _names(missing: list[dict], positions: set[str], limit: int = 2) -> str:
    found = [row.get("player_name") for row in missing if _pos(row) in positions and row.get("player_name")]
    return ", ".join(str(name) for name in found[:limit])


def _missing_team(own: list[dict]) -> dict:
    notes: list[str] = []
    pass_m = 1.0
    rush_m = 1.0
    rec_m = 1.0
    score_m = 1.0
    qb_out = _share(own, SKILL["QB"]) >= 0.40 or any(_pos(row) == "QB" for row in own)
    if qb_out:
        pass_m *= 0.86
        rec_m *= 0.92
        rush_m *= 1.05
        score_m *= 0.90
        notes.append(f"QB out ({_names(own, SKILL['QB']) or 'starter'})")
    ol = sum(1 for row in own if _pos(row) in OL)
    if ol >= 2:
        pass_m *= 0.92
        score_m *= 0.96
        notes.append(f"{ol} OL out")
    elif ol == 1:
        pass_m *= 0.96
        notes.append(f"OL out ({_names(own, OL)})")
    rb_share = _share(own, SKILL["RB"])
    if rb_share >= 0.45:
        rush_m *= 0.90
        notes.append(f"RB out ({_names(own, SKILL['RB'])})")
    wr_share = _share(own, SKILL["WR"]) + _share(own, SKILL["TE"])
    if wr_share >= 0.50:
        rec_m *= 0.94
        pass_m *= 0.97
        notes.append(f"pass-catcher out ({_names(own, SKILL['WR'] | SKILL['TE'])})")
    return {
        "pass": pass_m,
        "rush": rush_m,
        "rec": rec_m,
        "score": score_m,
        "qb_out": qb_out,
        "notes": notes,
        "rb_share": rb_share,
        "wr_share": wr_share,
        "te_share": _share(own, SKILL["TE"]),
    }


def _missing_opp(opp: list[dict]) -> dict:
    notes: list[str] = []
    pass_m = 1.0
    rush_m = 1.0
    rec_m = 1.0
    score_m = 1.0
    front = sum(1 for row in opp if _pos(row) in FRONT)
    db = sum(1 for row in opp if _pos(row) in SECONDARY)
    if front >= 2:
        rush_m *= 1.05
        pass_m *= 1.03
        score_m *= 1.03
        notes.append("opponent front seven thinned")
    elif front == 1:
        rush_m *= 1.02
        notes.append(f"opponent front out ({_names(opp, FRONT)})")
    if db >= 2:
        rec_m *= 1.05
        pass_m *= 1.04
        score_m *= 1.02
        notes.append("opponent secondary thinned")
    elif db == 1:
        rec_m *= 1.02
        notes.append(f"opponent DB out ({_names(opp, SECONDARY)})")
    return {"pass": pass_m, "rush": rush_m, "rec": rec_m, "score": score_m, "notes": notes}


def usage_mult(player: dict, stat: str, own: list[dict], own_pack: dict) -> tuple[float, str | None]:
    player_id = player.get("player_id")
    name = (player.get("player_name") or "").lower()
    for row in own:
        rid = row.get("player_id")
        rname = (row.get("player_name") or "").lower()
        if (player_id and rid and str(rid) == str(player_id)) or (name and rname == name):
            return 0.15, f"{player.get('player_name')} is out/doubtful"
    pos = str(player.get("position") or "").upper()
    if pos in SKILL["QB"] and own_pack.get("qb_out") and stat in PASS_STATS:
        return 1.0, None
    if pos in SKILL["RB"] and stat in RUSH_STATS:
        bump = min(0.38, float(own_pack.get("rb_share") or 0) * 0.70)
        if bump >= 0.08:
            return 1.0 + bump, "RB snaps open"
    if pos in SKILL["WR"] and stat in PASS_STATS - {"passing_yards", "passing_tds"}:
        bump = min(0.28, float(own_pack.get("wr_share") or 0) * 0.45)
        if bump >= 0.08:
            return 1.0 + bump, "WR snaps open"
    if pos in SKILL["TE"] and stat in PASS_STATS - {"passing_yards", "passing_tds"}:
        bump = min(0.32, float(own_pack.get("te_share") or 0) * 0.55 + float(own_pack.get("wr_share") or 0) * 0.12)
        if bump >= 0.08:
            return 1.0 + bump, "TE snaps open"
    if pos in SKILL["QB"] and own_pack.get("qb_out"):
        return 1.15, "backup volume"
    return 1.0, None


def team_pack(game: dict, home: bool, own: list[dict], opp: list[dict]) -> dict:
    rest_days = _num(game.get("home_rest") if home else game.get("away_rest"))
    opp_rest = _num(game.get("away_rest") if home else game.get("home_rest"))
    pass_rest, score_rest, rest_note = _rest_mult(rest_days)
    weather = _weather(game)
    travel_m, travel_note = _travel_note(game, home)
    own_m = _missing_team(own)
    opp_m = _missing_opp(opp)
    score_gap = 1.0
    if rest_days is not None and opp_rest is not None:
        score_gap = 1.0 + _clamp((rest_days - opp_rest) * 0.006, -0.03, 0.03)
    pass_m = _clamp(pass_rest * weather["pass"] * travel_m * own_m["pass"] * opp_m["pass"], 0.80, 1.18)
    rush_m = _clamp(1.0 * weather["rush"] * own_m["rush"] * opp_m["rush"], 0.82, 1.18)
    rec_m = _clamp(weather["pass"] * own_m["rec"] * opp_m["rec"], 0.82, 1.18)
    score_m = _clamp(score_rest * weather["score"] * travel_m * own_m["score"] * opp_m["score"] * score_gap, 0.82, 1.16)
    notes = [item for item in [rest_note, travel_note] if item]
    notes.extend(weather["notes"])
    notes.extend(own_m["notes"])
    notes.extend(opp_m["notes"])
    team = game.get("home_team") if home else game.get("away_team")
    tagged = [f"{team} {note}" if note and not note.startswith(str(team)) else note for note in notes]
    return {
        "pass": pass_m,
        "rush": rush_m,
        "rec": rec_m,
        "score": score_m,
        "sd": weather["sd"],
        "notes": [note for note in tagged if note],
        "missing": own_m,
        "own": own,
        "indoor": weather["indoor"],
    }


def stat_mult(stat: str, pack: dict) -> float:
    if stat in PASS_STATS and stat in {"passing_yards", "passing_tds"}:
        return pack["pass"]
    if stat in RUSH_STATS:
        return pack["rush"]
    if stat in PASS_STATS:
        return pack["rec"]
    return 1.0


def load_game_context(conn, game: dict, home_missing: list[dict] | None = None, away_missing: list[dict] | None = None) -> dict:
    from collegegridiron.slate import missing_for

    season = int(game["season"])
    week = int(game["week"])
    home_miss = home_missing if home_missing is not None else missing_for(conn, season, week, game["home_team"])
    away_miss = away_missing if away_missing is not None else missing_for(conn, season, week, game["away_team"])
    home = team_pack(game, True, home_miss, away_miss)
    away = team_pack(game, False, away_miss, home_miss)
    notes = []
    for pack in (away, home):
        for note in pack["notes"]:
            if note not in notes:
                notes.append(note)
    return {
        "home": home,
        "away": away,
        "notes": notes,
        "sd": min(home["sd"], away["sd"]),
    }


def apply_expected(expected: dict | None, ctx: dict) -> dict | None:
    if not expected:
        return expected
    raw_home = float(expected["home_points"])
    raw_away = float(expected["away_points"])
    home_pts = round(raw_home * float(ctx["home"]["score"]), 1)
    away_pts = round(raw_away * float(ctx["away"]["score"]), 1)
    out = dict(expected)
    out["raw_home_points"] = raw_home
    out["raw_away_points"] = raw_away
    out["raw_total"] = expected.get("total")
    out["raw_margin"] = expected.get("margin")
    out["home_points"] = home_pts
    out["away_points"] = away_pts
    out["total"] = round(home_pts + away_pts, 1)
    out["margin"] = round(home_pts - away_pts, 1)
    out["context_notes"] = ctx.get("notes") or []
    out["method"] = (
        "Team PPG + opponent PAPG − league + HFA, then rest/weather/missing-regular gates, "
        "then 5,000 game-script simulations."
    )
    return out


def pack_for_player(ctx: dict, player: dict, game: dict) -> dict:
    team = player.get("latest_team")
    if team == game.get("home_team"):
        return ctx["home"]
    if team == game.get("away_team"):
        return ctx["away"]
    return ctx["home"]


def context_for_player(ctx: dict, player: dict, game: dict, stat: str) -> dict:
    pack = pack_for_player(ctx, player, game)
    usage, usage_note = usage_mult(player, stat, pack.get("own") or [], pack.get("missing") or {})
    notes = list(pack.get("notes") or [])
    if usage_note:
        notes.append(usage_note)
    return {
        "situation": stat_mult(stat, pack),
        "usage": usage,
        "notes": notes,
        "is_home": player.get("latest_team") == game.get("home_team"),
        "listed_out": usage <= 0.20 and usage_note is not None,
    }
