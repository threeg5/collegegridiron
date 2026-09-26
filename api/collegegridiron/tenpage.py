"""TENPAGE: $10 on TPE's side of every stored FanDuel line for a week, graded after kickoff."""

from __future__ import annotations

from collegegridiron.pricing import american_profit
from collegegridiron.markets import list_game_lines, list_game_markets
from collegegridiron.slate import get_matchup, get_slate, rows
from collegegridiron.tpe_board import ALLOWED_STATS, build_tpe_board, _odds_text, _spread_label

STAKE = 10.0


def _cmp(left: float, right: float) -> str:
    if abs(left - right) < 1e-9:
        return "push"
    return "win" if left > right else "loss"


def _grade_game_side(game: dict, ticket: str, lines: list[dict]) -> tuple[str | None, str | None]:
    home_s = game.get("home_score")
    away_s = game.get("away_score")
    if home_s is None or away_s is None:
        return None, None
    home = float(home_s)
    away = float(away_s)
    by_market = {row["market"]: row for row in lines}
    home_team = game.get("home_team") or "HOME"
    away_team = game.get("away_team") or "AWAY"
    if ticket.startswith("spread-"):
        spread = by_market.get("spread") or {}
        home_line = spread.get("home_line")
        away_line = spread.get("away_line")
        if home_line is None or away_line is None:
            return None, f"{away_team} {away_s}–{home_team} {home_s}"
        actual = f"{away_team} {away_s}–{home_team} {home_s}"
        if ticket == "spread-home":
            return _cmp(home + float(home_line), away), actual
        return _cmp(away + float(away_line), home), actual
    if ticket.startswith("total-"):
        total = by_market.get("total") or {}
        line = total.get("home_line")
        combined = home + away
        actual = f"Total {combined:g}"
        if line is None:
            return None, actual
        if ticket == "total-over":
            return _cmp(combined, float(line)), actual
        return _cmp(float(line), combined), actual
    if ticket.startswith("ml-"):
        actual = f"{away_team} {away_s}–{home_team} {home_s}"
        if home == away:
            return "push", actual
        home_win = home > away
        if ticket == "ml-home":
            return ("win" if home_win else "loss"), actual
        return ("loss" if home_win else "win"), actual
    return None, None


def _grade_prop(actual: float | None, line: float, over: bool) -> str | None:
    if actual is None:
        return None
    if over:
        return _cmp(float(actual), float(line))
    return _cmp(float(line), float(actual))


def _tpe_takes_displayed(row: dict) -> bool | None:
    if row.get("tpe_pct") is None or row.get("odds") is None:
        return None
    implied = row.get("implied")
    if implied is None:
        return True
    return float(row["tpe_pct"]) >= float(implied)


def _game_opposite(row: dict, game: dict, lines: list[dict]) -> dict | None:
    by_market = {item["market"]: item for item in lines}
    home = game.get("home_team") or "HOME"
    away = game.get("away_team") or "AWAY"
    rid = row.get("id") or ""
    if rid == "spread-home":
        spread = by_market.get("spread") or {}
        odds = spread.get("away_odds")
        if odds is None:
            return None
        return {
            "side": _spread_label(away, spread.get("away_line")),
            "odds": odds,
            "ticket": "spread-away",
        }
    if rid == "spread-away":
        spread = by_market.get("spread") or {}
        odds = spread.get("home_odds")
        if odds is None:
            return None
        return {
            "side": _spread_label(home, spread.get("home_line")),
            "odds": odds,
            "ticket": "spread-home",
        }
    if rid == "total-over":
        total = by_market.get("total") or {}
        odds = total.get("under_odds")
        line = total.get("home_line")
        if odds is None or line is None:
            return None
        return {"side": f"Under {float(line):g}", "odds": odds, "ticket": "total-under"}
    if rid == "total-under":
        total = by_market.get("total") or {}
        odds = total.get("over_odds")
        line = total.get("home_line")
        if odds is None or line is None:
            return None
        return {"side": f"Over {float(line):g}", "odds": odds, "ticket": "total-over"}
    if rid == "ml-home":
        ml = by_market.get("moneyline") or {}
        odds = ml.get("away_odds")
        if odds is None:
            return None
        return {"side": f"{away} {_odds_text(odds)}", "odds": odds, "ticket": "ml-away"}
    if rid == "ml-away":
        ml = by_market.get("moneyline") or {}
        odds = ml.get("home_odds")
        if odds is None:
            return None
        return {"side": f"{home} {_odds_text(odds)}", "odds": odds, "ticket": "ml-home"}
    return None


def _prop_actuals(conn, game_ids: list[str], stats: list[str]) -> dict[tuple[str, str, str], float]:
    if not game_ids or not stats:
        return {}
    g_ph = ",".join("?" for _ in game_ids)
    cols = ", ".join(stats)
    found = rows(
        conn,
        f"""
        SELECT player_id, game_id, {cols}
        FROM player_weeks
        WHERE game_id IN ({g_ph})
          AND COALESCE(season_type, 'REG') = 'REG'
        """,
        tuple(game_ids),
    )
    out: dict[tuple[str, str, str], float] = {}
    for row in found:
        for stat in stats:
            value = row.get(stat)
            if value is None:
                continue
            out[(row["player_id"], row["game_id"], stat)] = float(value)
    return out


def _ticket_from_row(row: dict, game: dict, lines: list[dict], stored: list[dict]) -> dict | None:
    takes = _tpe_takes_displayed(row)
    if takes is None:
        return None
    if takes:
        pick_side = row["side"]
        pick_odds = row["odds"]
        ticket = row["id"]
        over = True
    else:
        if row.get("player_id"):
            market = next(
                (
                    item
                    for item in stored
                    if item.get("player_id") == row.get("player_id") and item.get("stat") == row.get("stat")
                ),
                None,
            )
            under_odds = (market or {}).get("under_odds")
            line = row.get("line")
            if under_odds is None or line is None:
                return None
            name = row.get("player_name") or row["side"]
            pick_side = f"{name} under {float(line):g}"
            pick_odds = under_odds
            ticket = row["id"]
            over = False
        else:
            opp = _game_opposite(row, game, lines)
            if not opp:
                return None
            pick_side = opp["side"]
            pick_odds = opp["odds"]
            ticket = opp["ticket"]
            over = True
    return {
        "id": row["id"],
        "market": row["market"],
        "board_side": row["side"],
        "pick": pick_side,
        "odds": pick_odds,
        "odds_text": _odds_text(pick_odds),
        "tpe": row.get("tpe"),
        "tpe_pct": row.get("tpe_pct"),
        "implied": row.get("implied"),
        "ev": row.get("ev"),
        "ticket": ticket,
        "player_id": row.get("player_id"),
        "stat": row.get("stat"),
        "line": row.get("line"),
        "open_line": row.get("open_line"),
        "open_odds": row.get("open_odds"),
        "move_kind": row.get("move_kind"),
        "vs_tpe": row.get("vs_tpe"),
        "move_label": row.get("move_label"),
        "over": over if row.get("player_id") else None,
        "stake": STAKE,
    }


def _settle(ticket: dict, result: str | None, actual: str | None) -> dict:
    if result is None:
        winner = None
        profit = None
        status = "pending"
    elif result == "push":
        winner = "push"
        profit = 0.0
        status = "push"
    elif result == "win":
        winner = "tpe"
        profit = round(american_profit(STAKE, int(ticket["odds"]), "win") or 0.0, 2)
        status = "tpe"
    else:
        winner = "book"
        profit = round(american_profit(STAKE, int(ticket["odds"]), "loss") or 0.0, 2)
        status = "book"
    return {
        **ticket,
        "actual": actual,
        "result": result,
        "winner": winner,
        "profit": profit,
        "status": status,
    }


def build_tenpage(
    conn,
    stats: dict[str, str],
    season: int | None = None,
    week: int | None = None,
    season_type: str | None = None,
) -> dict:
    slate = get_slate(conn, season, week, season_type)
    current = slate.get("slate")
    games = slate.get("games") or []
    game_ids = [game["game_id"] for game in games]
    needed_stats = sorted(ALLOWED_STATS)
    actuals = _prop_actuals(conn, game_ids, needed_stats)
    groups = []
    tpe_wins = 0
    book_wins = 0
    pushes = 0
    pending = 0
    total = 0.0
    graded_profit = 0.0
    tickets_n = 0

    for game in games:
        lines = list_game_lines(game["game_id"])
        stored = [row for row in list_game_markets(game["game_id"]) if row.get("stat") in ALLOWED_STATS]
        if not lines and not stored:
            continue
        found = get_matchup(conn, game["game_id"])
        if not found:
            continue
        board = build_tpe_board(conn, found["game"], found.get("expected"), stats)
        played = bool(game.get("played"))
        score = None
        if played:
            score = f"{game.get('away_team')} {game.get('away_score')}–{game.get('home_team')} {game.get('home_score')}"
        rows_out = []
        for row in (board.get("game_rows") or []) + (board.get("prop_rows") or []):
            ticket = _ticket_from_row(row, game, lines, stored)
            if not ticket:
                continue
            tickets_n += 1
            result = None
            actual = score
            if ticket.get("player_id"):
                value = actuals.get((ticket["player_id"], game["game_id"], ticket["stat"]))
                if value is not None:
                    actual = f"{value:g}"
                    result = _grade_prop(value, float(ticket["line"]), bool(ticket.get("over")))
                elif played:
                    actual = "No stat yet"
            elif played:
                result, actual = _grade_game_side(game, ticket["ticket"], lines)
            settled = _settle(ticket, result, actual)
            if settled["status"] == "tpe":
                tpe_wins += 1
                graded_profit += settled["profit"] or 0.0
            elif settled["status"] == "book":
                book_wins += 1
                graded_profit += settled["profit"] or 0.0
            elif settled["status"] == "push":
                pushes += 1
            else:
                pending += 1
            if settled["profit"] is not None:
                total += settled["profit"]
            rows_out.append(settled)
        if not rows_out:
            continue
        groups.append(
            {
                "game_id": game["game_id"],
                "label": f"{game.get('away_team')} @ {game.get('home_team')}",
                "kickoff": game.get("gameday"),
                "played": played,
                "score": score,
                "rows": rows_out,
            }
        )

    return {
        "stake": STAKE,
        "slate": current,
        "weeks": slate.get("weeks") or [],
        "games": groups,
        "tickets": tickets_n,
        "pending": pending,
        "tpe_wins": tpe_wins,
        "book_wins": book_wins,
        "pushes": pushes,
        "total": round(total, 2),
        "graded_total": round(graded_profit, 2),
        "method": (
            f"${STAKE:g} on TPE's side of every stored FanDuel line this week "
            "(the displayed side if TPE is at or above the price, the other side if TPE fades). "
            "Graded after the game from the snapshot line, not a backtest."
        ),
    }
