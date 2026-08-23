from __future__ import annotations

from datetime import date, datetime, timedelta

from collegegridiron.config import TEAM_LOOKBACK_GAMES, TEAM_RECENT_GAMES
from collegegridiron.venues import team_name

TEAM_GAMES_SQL = """
SELECT
  game_id, season, week, season_type, gameday,
  home_team AS team, away_team AS opponent,
  1 AS is_home,
  home_score AS points_for, away_score AS points_against
FROM games
WHERE home_score IS NOT NULL AND away_score IS NOT NULL
UNION ALL
SELECT
  game_id, season, week, season_type, gameday,
  away_team AS team, home_team AS opponent,
  0 AS is_home,
  away_score AS points_for, home_score AS points_against
FROM games
WHERE home_score IS NOT NULL AND away_score IS NOT NULL
"""

SLATE_GAME_COLS = """
  game_id, season, week, season_type, gameday, weekday, gametime,
  home_team, away_team, home_score, away_score,
  roof, surface, surface_group, temp, wind, stadium, location,
  home_rest, away_rest, div_game, is_primetime, is_early_window,
  is_altitude, is_overseas,
  home_travel, away_travel, home_travel_miles, away_travel_miles,
  home_tz_change, away_tz_change, home_conference, away_conference
"""


def rows(conn, sql: str, params: tuple = ()) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def one(conn, sql: str, params: tuple = ()) -> dict | None:
    found = conn.execute(sql, params).fetchone()
    return dict(found) if found else None


def _round(value, digits: int = 1):
    if value is None:
        return None
    try:
        if value != value:
            return None
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None


def _mean(values: list[float], digits: int = 1):
    nums = [float(v) for v in values if v is not None]
    if not nums:
        return None
    return round(sum(nums) / len(nums), digits)


def _as_date(value) -> date | None:
    if value is None:
        return None
    text = str(value)[:10]
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def week_label(season: int, week: int, season_type: str | None) -> str:
    kind = (season_type or "REG").upper()
    if kind == "POST":
        return f"{season} · Bowl / CFP {week}"
    if kind == "PRE":
        return f"{season} · Preseason {week}"
    return f"{season} · Week {week}"


def list_weeks(conn) -> list[dict]:
    found = rows(
        conn,
        """
        SELECT season, week, season_type,
               COUNT(*) AS games,
               MIN(gameday) AS first_gameday,
               MAX(gameday) AS last_gameday,
               SUM(CASE WHEN home_score IS NULL THEN 1 ELSE 0 END) AS unplayed
        FROM games
        GROUP BY season, week, season_type
        ORDER BY MIN(gameday) DESC, season DESC, week DESC
        """,
    )
    for item in found:
        item["label"] = week_label(item["season"], item["week"], item["season_type"])
    return found


def resolve_slate(
    conn,
    season: int | None = None,
    week: int | None = None,
    season_type: str | None = None,
) -> dict | None:
    weeks = list_weeks(conn)
    if not weeks:
        return None
    if season is not None and week is not None:
        kind = (season_type or "REG").upper()
        match = next(
            (
                w
                for w in weeks
                if w["season"] == season
                and w["week"] == week
                and (w["season_type"] or "REG").upper() == kind
            ),
            None,
        )
        if match:
            return match
        return next(
            (w for w in weeks if w["season"] == season and w["week"] == week),
            None,
        )

    today = date.today()
    window = timedelta(days=1)

    def in_progress(item: dict) -> bool:
        start = _as_date(item["first_gameday"])
        end = _as_date(item["last_gameday"])
        if not start or not end:
            return False
        return start - window <= today <= end + window

    live = [w for w in weeks if in_progress(w)]
    live_main = [w for w in live if (w["season_type"] or "").upper() != "PRE"]
    if live_main:
        return live_main[0]
    if live:
        return live[0]

    upcoming = []
    for item in weeks:
        start = _as_date(item["first_gameday"])
        if start and start > today:
            upcoming.append(item)
    upcoming.sort(
        key=lambda w: (
            _as_date(w["first_gameday"]) or date.max,
            0 if (w["season_type"] or "") != "PRE" else 1,
        )
    )
    if upcoming:
        first_day = _as_date(upcoming[0]["first_gameday"])
        near_reg = [
            w
            for w in upcoming
            if (w["season_type"] or "").upper() != "PRE"
            and _as_date(w["first_gameday"])
            and first_day
            and (_as_date(w["first_gameday"]) - today).days <= 21
        ]
        return near_reg[0] if near_reg else upcoming[0]

    return weeks[0]


def decorate_game(game: dict) -> dict:
    game = dict(game)
    game["home_name"] = team_name(game.get("home_team"))
    game["away_name"] = team_name(game.get("away_team"))
    game["played"] = game.get("home_score") is not None and game.get("away_score") is not None
    game["neutral"] = str(game.get("location") or "Home").lower() == "neutral" or bool(
        game.get("is_overseas")
    )
    return game


def slate_games(conn, season: int, week: int, season_type: str) -> list[dict]:
    games = rows(
        conn,
        f"""
        SELECT {SLATE_GAME_COLS}
        FROM games
        WHERE season = ? AND week = ? AND COALESCE(season_type, 'REG') = ?
        ORDER BY gameday, gametime, away_team
        """,
        (season, week, season_type),
    )
    return [decorate_game(game) for game in games]


def missing_for(conn, season: int, week: int, team: str) -> list[dict]:
    return rows(
        conn,
        """
        SELECT player_name, position, side, snap_pct_recent, status, injury
        FROM missing_regulars
        WHERE season = ? AND week = ? AND team = ?
        ORDER BY snap_pct_recent DESC
        """,
        (season, week, team),
    )


def _profile_from_games(games: list[dict], limit: int) -> dict | None:
    sample = games[:limit]
    if not sample:
        return None
    points_for = [g["points_for"] for g in sample]
    points_against = [g["points_against"] for g in sample]
    pass_yards = [g.get("passing_yards") for g in sample]
    rush_yards = [g.get("rushing_yards") for g in sample]
    yards = []
    yards_allowed = []
    for game in sample:
        py, ry = game.get("passing_yards"), game.get("rushing_yards")
        if py is not None or ry is not None:
            yards.append((py or 0) + (ry or 0))
        opy, ory = game.get("opp_passing_yards"), game.get("opp_rushing_yards")
        if opy is not None or ory is not None:
            yards_allowed.append((opy or 0) + (ory or 0))
    turnovers = []
    for game in sample:
        ints = game.get("interceptions")
        rush_fum = game.get("rushing_fumbles_lost")
        sack_fum = game.get("sack_fumbles_lost")
        if ints is None and rush_fum is None and sack_fum is None:
            continue
        turnovers.append((ints or 0) + (rush_fum or 0) + (sack_fum or 0))
    plays = []
    for game in sample:
        att = game.get("attempts")
        sacks = game.get("sacks_suffered")
        carries = game.get("carries")
        if att is None and carries is None:
            continue
        plays.append((att or 0) + (sacks or 0) + (carries or 0))
    ppg = _mean(points_for)
    papg = _mean(points_against)
    margin = None if ppg is None or papg is None else round(ppg - papg, 1)
    first = sample[-1]
    last = sample[0]
    return {
        "games": len(sample),
        "from_gameday": first.get("gameday"),
        "to_gameday": last.get("gameday"),
        "from_season": first.get("season"),
        "from_week": first.get("week"),
        "to_season": last.get("season"),
        "to_week": last.get("week"),
        "ppg": ppg,
        "papg": papg,
        "margin": margin,
        "pass_yards": _mean(pass_yards, 1),
        "rush_yards": _mean(rush_yards, 1),
        "yards": _mean(yards, 1),
        "yards_allowed": _mean(yards_allowed, 1),
        "pass_epa": _mean([g.get("passing_epa") for g in sample], 2),
        "rush_epa": _mean([g.get("rushing_epa") for g in sample], 2),
        "turnovers": _mean(turnovers, 2),
        "sacks_suffered": _mean([g.get("sacks_suffered") for g in sample], 2),
        "def_sacks": _mean([g.get("def_sacks") for g in sample], 2),
        "plays": _mean(plays, 1),
    }


def load_team_log(conn, team: str, before: str | None, season_type: str = "REG") -> list[dict]:
    params: list = [team, season_type]
    before_clause = ""
    if before:
        before_clause = "AND tg.gameday < ?"
        params.append(before)
    return rows(
        conn,
        f"""
        SELECT
          tg.game_id, tg.season, tg.week, tg.season_type, tg.gameday,
          tg.team, tg.opponent, tg.is_home, tg.points_for, tg.points_against,
          tw.completions, tw.attempts, tw.passing_yards, tw.passing_tds,
          tw.interceptions, tw.sacks_suffered, tw.passing_epa,
          tw.carries, tw.rushing_yards, tw.rushing_tds, tw.rushing_epa,
          tw.rushing_fumbles_lost, tw.sack_fumbles_lost, tw.def_sacks,
          tw.def_interceptions,
          opp.passing_yards AS opp_passing_yards,
          opp.rushing_yards AS opp_rushing_yards
        FROM ({TEAM_GAMES_SQL}) tg
        LEFT JOIN team_weeks tw
          ON tw.team = tg.team
         AND tw.season = tg.season
         AND tw.week = tg.week
         AND COALESCE(tw.season_type, 'REG') = COALESCE(tg.season_type, 'REG')
        LEFT JOIN team_weeks opp
          ON opp.team = tg.opponent
         AND opp.season = tg.season
         AND opp.week = tg.week
         AND COALESCE(opp.season_type, 'REG') = COALESCE(tg.season_type, 'REG')
        WHERE tg.team = ?
          AND COALESCE(tg.season_type, 'REG') = ?
          {before_clause}
        ORDER BY tg.gameday DESC, tg.game_id DESC
        """,
        tuple(params),
    )


def build_team_card(
    conn,
    team: str,
    is_home: bool,
    season: int,
    week: int,
    before: str | None,
    season_type: str = "REG",
) -> dict:
    log = load_team_log(conn, team, before, "REG")
    if not log:
        log = load_team_log(conn, team, before, season_type or "REG")
    overall = _profile_from_games(log, TEAM_LOOKBACK_GAMES)
    recent = _profile_from_games(log, TEAM_RECENT_GAMES)
    role_games = [g for g in log if bool(g.get("is_home")) == is_home]
    role = _profile_from_games(role_games, TEAM_LOOKBACK_GAMES)
    return {
        "team": team,
        "name": team_name(team),
        "is_home": int(is_home),
        "overall": overall,
        "recent": recent,
        "role": role,
        "missing": missing_for(conn, season, week, team),
    }


def league_environment(conn, since: str | None, before: str | None, season_type: str = "REG") -> dict:
    clauses = [
        "home_score IS NOT NULL",
        "away_score IS NOT NULL",
        "COALESCE(season_type, 'REG') = ?",
    ]
    params: list = [season_type]
    if since:
        clauses.append("gameday >= ?")
        params.append(since)
    if before:
        clauses.append("gameday < ?")
        params.append(before)
    where = " AND ".join(clauses)
    env = one(
        conn,
        f"""
        SELECT
          AVG((home_score + away_score) / 2.0) AS league_ppg,
          AVG(CASE
                WHEN LOWER(COALESCE(location, 'Home')) = 'home' AND COALESCE(is_overseas, 0) = 0
                THEN home_score - away_score
              END) AS hfa,
          COUNT(*) AS games
        FROM games
        WHERE {where}
        """,
        tuple(params),
    ) or {}
    return {
        "league_ppg": _round(env.get("league_ppg"), 2),
        "hfa": _round(env.get("hfa"), 2),
        "games": env.get("games") or 0,
    }


def expected_points(offense_ppg, defense_papg, league_ppg, extra: float = 0.0):
    if offense_ppg is None or defense_papg is None or league_ppg is None:
        return None
    return round(float(offense_ppg) + float(defense_papg) - float(league_ppg) + extra, 1)


def expected_from_profiles(home: dict, away: dict, env: dict, neutral: bool) -> dict | None:
    home_over = (home or {}).get("overall") or {}
    away_over = (away or {}).get("overall") or {}
    league = env.get("league_ppg")
    hfa = 0.0 if neutral else float(env.get("hfa") or 0)
    home_pts = expected_points(home_over.get("ppg"), away_over.get("papg"), league, hfa)
    away_pts = expected_points(away_over.get("ppg"), home_over.get("papg"), league, 0.0)
    if home_pts is None or away_pts is None:
        return None
    home_recent = (home or {}).get("recent") or {}
    away_recent = (away or {}).get("recent") or {}
    recent_home = expected_points(home_recent.get("ppg"), away_recent.get("papg"), league, hfa)
    recent_away = expected_points(away_recent.get("ppg"), home_recent.get("papg"), league, 0.0)
    recent = None
    if recent_home is not None and recent_away is not None:
        recent = {
            "away_points": recent_away,
            "home_points": recent_home,
            "total": round(recent_away + recent_home, 1),
            "margin": round(recent_home - recent_away, 1),
        }
    return {
        "away_points": away_pts,
        "home_points": home_pts,
        "total": round(away_pts + home_pts, 1),
        "margin": round(home_pts - away_pts, 1),
        "hfa": round(hfa, 2),
        "league_ppg": league,
        "recent": recent,
        "method": "team PPG + opponent PAPG - league PPG, plus home-field from the same window",
    }


def get_slate(
    conn,
    season: int | None = None,
    week: int | None = None,
    season_type: str | None = None,
) -> dict:
    current = resolve_slate(conn, season, week, season_type)
    if not current:
        return {"slate": None, "weeks": [], "games": []}
    games = slate_games(conn, current["season"], current["week"], current["season_type"] or "REG")
    return {"slate": current, "weeks": list_weeks(conn), "games": games}


def get_matchup(conn, game_id: str) -> dict | None:
    game = one(conn, f"SELECT {SLATE_GAME_COLS} FROM games WHERE game_id = ?", (game_id,))
    if not game:
        return None
    game = decorate_game(game)
    before = game.get("gameday")
    away = build_team_card(
        conn, game["away_team"], False, game["season"], game["week"], before, "REG"
    )
    home = build_team_card(
        conn, game["home_team"], True, game["season"], game["week"], before, "REG"
    )
    since_candidates = [
        (away.get("overall") or {}).get("from_gameday"),
        (home.get("overall") or {}).get("from_gameday"),
    ]
    since = min((d for d in since_candidates if d), default=None)
    env = league_environment(conn, since, before, "REG")
    expected = expected_from_profiles(home, away, env, bool(game.get("neutral")))
    return {
        "game": game,
        "away": away,
        "home": home,
        "environment": env,
        "expected": expected,
        "lookback_games": TEAM_LOOKBACK_GAMES,
        "recent_games": TEAM_RECENT_GAMES,
    }
