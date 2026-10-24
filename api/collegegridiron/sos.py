"""Comparable team score and strength of schedule from games already stored.

The desk score is points better than an average FBS team on a neutral field.
It adds three pieces on that same scale: offense, defense, and special teams.
Conference strength is the average desk score of that league, shown beside the
team so two conferences can be matched the same way two teams can.

Offense and defense are solved together: points scored depend on the opponent's
defense, and points allowed depend on the opponent's offense. Special teams is
expected points from kicking, punts, and kickoffs. An opponent that is not an
FBS program sits one score under an average FBS team.
"""

from __future__ import annotations

from collegegridiron.config import TEAM_LOOKBACK_GAMES

MIN_GAMES = 4
ITERATIONS = 8
MARGIN_CAP = 28.0
FCS_NOTCH = -7.0
SHIFT_CAP = 7.0
HARD_AT = 3.0
SOFT_AT = -3.0
ST_CAP = 8.0
POINT_CAP = 49.0
HFA_HALF = 1.25
ADV_URL = (
    "https://github.com/sportsdataverse/sportsdataverse-data/releases/download/"
    "espn_cfb_adv_team/adv_team_{year}.parquet"
)

_SPECIAL: dict[tuple[str, str], float] | None = None


def _ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _fbs_teams(conn) -> set[str]:
    found = conn.execute("SELECT team FROM team_venues").fetchall()
    return {str(row["team"]) for row in found if row["team"]}


def _results(conn) -> list[dict]:
    from collegegridiron.slate import TEAM_GAMES_SQL, rows

    return rows(
        conn,
        f"""
        SELECT game_id, team, opponent, points_for, points_against, gameday, is_home
        FROM ({TEAM_GAMES_SQL}) tg
        WHERE COALESCE(tg.season_type, 'REG') = 'REG'
          AND tg.gameday IS NOT NULL
        ORDER BY tg.gameday DESC, tg.game_id DESC
        """,
    )


def _logs_before(results: list[dict], before: str | None, fbs: set[str]) -> dict[str, list[dict]]:
    logs: dict[str, list[dict]] = {}
    cutoff = before or "9999-99-99"
    for game in results:
        team = game.get("team")
        if team not in fbs:
            continue
        day = str(game.get("gameday") or "")
        if day >= cutoff:
            continue
        bucket = logs.setdefault(team, [])
        if len(bucket) >= TEAM_LOOKBACK_GAMES:
            continue
        bucket.append(game)
    return logs


def _rate(logs: dict[str, list[dict]], fbs: set[str]) -> dict[str, float]:
    ratings = {team: 0.0 for team in logs}
    for _ in range(ITERATIONS):
        raw: dict[str, float] = {}
        for team, games in logs.items():
            total = 0.0
            for game in games:
                margin = float(game["points_for"]) - float(game["points_against"])
                margin = max(-MARGIN_CAP, min(MARGIN_CAP, margin))
                opponent = game.get("opponent")
                if opponent in ratings:
                    opp_rating = ratings[opponent]
                elif opponent in fbs:
                    opp_rating = 0.0
                else:
                    opp_rating = FCS_NOTCH
                total += margin + opp_rating
            shrink = min(1.0, len(games) / MIN_GAMES)
            raw[team] = shrink * (total / len(games))
        full = [value for team, value in raw.items() if len(logs[team]) >= MIN_GAMES]
        center = sum(full) / len(full) if full else 0.0
        ratings = {team: value - center for team, value in raw.items()}
    return ratings


def _opponent_rating(opponent: str, ratings: dict[str, float], fbs: set[str]) -> float:
    if opponent in ratings:
        return ratings[opponent]
    if opponent in fbs:
        return 0.0
    return FCS_NOTCH


def _label(sos: float) -> str:
    if sos >= HARD_AT:
        return "hard"
    if sos <= SOFT_AT:
        return "soft"
    return "average"


def _cap_st(value) -> float:
    if value is None:
        return 0.0
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(-ST_CAP, min(ST_CAP, number))


def _conferences(conn) -> dict[str, str]:
    found = conn.execute(
        "SELECT team, conference FROM team_venues WHERE conference IS NOT NULL AND conference != ''"
    ).fetchall()
    return {str(row["team"]): str(row["conference"]) for row in found}


def ensure_special_teams(conn) -> None:
    """Load kicking, punt, and kickoff expected points once. The box we store has no special teams."""
    global _SPECIAL
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS special_teams (
          game_id TEXT NOT NULL,
          team TEXT NOT NULL,
          epa REAL,
          PRIMARY KEY (game_id, team)
        )
        """
    )
    count = conn.execute("SELECT COUNT(*) AS n FROM special_teams").fetchone()["n"]
    if count and count > 500:
        if _SPECIAL is None:
            _SPECIAL = {
                (str(row["game_id"]), str(row["team"])): float(row["epa"] or 0)
                for row in conn.execute("SELECT game_id, team, epa FROM special_teams")
            }
        return
    import io
    import urllib.request

    import pyarrow.parquet as pq

    venues = conn.execute("SELECT team, team_id, school, mascot FROM team_venues").fetchall()
    by_id = {str(row["team_id"]): str(row["team"]) for row in venues if row["team_id"]}
    by_name = {}
    for row in venues:
        team = str(row["team"])
        school = str(row["school"] or "").strip()
        mascot = str(row["mascot"] or "").strip()
        if school and mascot:
            by_name[f"{school} {mascot}".lower()] = team
        if school:
            by_name[school.lower()] = team
    years = conn.execute(
        "SELECT DISTINCT season FROM games WHERE season IS NOT NULL ORDER BY season"
    ).fetchall()
    rows_out = []
    for year_row in years:
        year = int(year_row["season"])
        req = urllib.request.Request(ADV_URL.format(year=year), headers={"User-Agent": "collegegridiron-desk"})
        try:
            with urllib.request.urlopen(req, timeout=60) as response:
                payload = response.read()
        except Exception:
            continue
        table = pq.read_table(
            io.BytesIO(payload),
            columns=["game_id", "pos_team_id", "pos_team", "EPA_special_teams"],
        )
        data = table.to_pydict()
        for game_id, team_id, name, epa in zip(
            data["game_id"], data["pos_team_id"], data["pos_team"], data["EPA_special_teams"]
        ):
            team = by_id.get(str(team_id) if team_id is not None else "")
            if not team and name:
                team = by_name.get(str(name).strip().lower())
            if not team or epa is None:
                continue
            rows_out.append((str(game_id), team, float(epa)))
    if rows_out:
        conn.executemany(
            "INSERT OR REPLACE INTO special_teams (game_id, team, epa) VALUES (?, ?, ?)",
            rows_out,
        )
        conn.commit()
    _SPECIAL = {
        (str(row["game_id"]), str(row["team"])): float(row["epa"] or 0)
        for row in conn.execute("SELECT game_id, team, epa FROM special_teams")
    }


def special_index(conn) -> dict[tuple[str, str], float]:
    ensure_special_teams(conn)
    return _SPECIAL or {}


def _fit_units(
    logs: dict[str, list[dict]],
    fbs: set[str],
    special: dict[tuple[str, str], float],
) -> tuple[dict[str, float], dict[str, float]]:
    offense = {team: 0.0 for team in logs}
    defense = {team: 0.0 for team in logs}
    for _ in range(ITERATIONS):
        new_off: dict[str, float] = {}
        new_def: dict[str, float] = {}
        for team, games in logs.items():
            off_total = 0.0
            def_total = 0.0
            for game in games:
                points_for = float(game["points_for"])
                points_against = float(game["points_against"])
                if game.get("is_home"):
                    points_for -= HFA_HALF
                    points_against += HFA_HALF
                own_st = _cap_st(special.get((str(game.get("game_id")), team)))
                opponent = game.get("opponent")
                opp_st = _cap_st(special.get((str(game.get("game_id")), opponent)))
                points_for = max(0.0, min(POINT_CAP, points_for - own_st))
                points_against = max(0.0, min(POINT_CAP, points_against - opp_st))
                if opponent in defense:
                    opp_def = defense[opponent]
                    opp_off = offense[opponent]
                elif opponent in fbs:
                    opp_def = 0.0
                    opp_off = 0.0
                else:
                    opp_def = FCS_NOTCH
                    opp_off = FCS_NOTCH
                off_total += points_for + opp_def
                def_total += opp_off - points_against
            shrink = min(1.0, len(games) / MIN_GAMES)
            new_off[team] = shrink * off_total / len(games)
            new_def[team] = shrink * def_total / len(games)
        full = [team for team in logs if len(logs[team]) >= MIN_GAMES]
        off_center = sum(new_off[team] for team in full) / len(full) if full else 0.0
        def_center = sum(new_def[team] for team in full) / len(full) if full else 0.0
        offense = {team: value - off_center for team, value in new_off.items()}
        defense = {team: value - def_center for team, value in new_def.items()}
    return offense, defense


def _special_ratings(
    logs: dict[str, list[dict]],
    special: dict[tuple[str, str], float],
) -> dict[str, float]:
    raw: dict[str, float] = {}
    for team, games in logs.items():
        if len(games) < MIN_GAMES:
            continue
        total = sum(_cap_st(special.get((str(game.get("game_id")), team))) for game in games)
        raw[team] = total / len(games)
    if not raw:
        return {}
    center = sum(raw.values()) / len(raw)
    return {team: value - center for team, value in raw.items()}


def views_before(
    results: list[dict],
    before: str | None,
    fbs: set[str],
    special: dict[tuple[str, str], float] | None = None,
    conferences: dict[str, str] | None = None,
) -> dict[str, dict]:
    logs = _logs_before(results, before, fbs)
    ratings = _rate(logs, fbs)
    sos_map: dict[str, float] = {}
    for team, games in logs.items():
        if len(games) < MIN_GAMES:
            continue
        sos_map[team] = sum(
            _opponent_rating(game.get("opponent"), ratings, fbs) for game in games
        ) / len(games)
    ranked = sorted(sos_map, key=lambda team: (-sos_map[team], team))
    rank = {team: index for index, team in enumerate(ranked, start=1)}
    of = len(ranked)
    special = special or {}
    conferences = conferences or {}
    offense, defense = _fit_units(logs, fbs, special)
    specials = _special_ratings(logs, special)
    parts: dict[str, tuple[float, float, float, float]] = {}
    for team in sos_map:
        off = round(offense.get(team, 0.0), 1)
        deff = round(defense.get(team, 0.0), 1)
        st = round(specials.get(team, 0.0), 1)
        parts[team] = (off, deff, st, round(off + deff + st, 1))
    power_order = sorted(parts, key=lambda team: (-parts[team][3], team))
    power_rank = {team: index for index, team in enumerate(power_order, start=1)}
    power_of = len(power_order)
    conf_values: dict[str, list[float]] = {}
    for team, (_off, _deff, _st, score) in parts.items():
        conf = conferences.get(team)
        if conf:
            conf_values.setdefault(conf, []).append(score)
    conf_rating = {
        conf: round(sum(values) / len(values), 1) for conf, values in conf_values.items()
    }
    views: dict[str, dict] = {}
    for team, games in logs.items():
        conf = conferences.get(team)
        conf_score = conf_rating.get(conf) if conf else None
        if team not in sos_map:
            views[team] = {
                "games": len(games),
                "opponent_rating": None,
                "team_rating": None,
                "rank": None,
                "of": of,
                "label": "thin",
                "rank_label": None,
                "text": "Not enough games for a slate read",
                "score": None,
                "offense": None,
                "defense": None,
                "special": None,
                "conference": conf,
                "conference_rating": conf_score,
                "power_rank": None,
                "power_of": power_of,
                "power_label": None,
            }
            continue
        sos = round(sos_map[team], 1)
        label = _label(sos)
        word = {"hard": "Hard", "soft": "Soft", "average": "Average"}[label]
        place = _ordinal(rank[team])
        off, deff, st, score = parts[team]
        power_place = _ordinal(power_rank[team])
        views[team] = {
            "games": len(games),
            "opponent_rating": sos,
            "team_rating": round(ratings[team], 1),
            "rank": rank[team],
            "of": of,
            "label": label,
            "rank_label": f"{place} hardest",
            "text": (
                f"{word} slate, {place} hardest. "
                f"Opponents {sos:+.1f} vs an average FBS slate."
            ),
            "score": score,
            "offense": off,
            "defense": deff,
            "special": st,
            "conference": conf,
            "conference_rating": conf_score,
            "power_rank": power_rank[team],
            "power_of": power_of,
            "power_label": f"{power_place} of {power_of}",
        }
    return views


def slate_views(conn, before: str | None) -> dict[str, dict]:
    return views_before(
        _results(conn),
        before,
        _fbs_teams(conn),
        special_index(conn),
        _conferences(conn),
    )


def annotate_slate(conn, games: list[dict]) -> None:
    if not games:
        return
    results = _results(conn)
    fbs = _fbs_teams(conn)
    special = special_index(conn)
    conferences = _conferences(conn)
    by_day: dict[str, list[dict]] = {}
    for game in games:
        day = str(game.get("gameday") or "")[:10]
        by_day.setdefault(day, []).append(game)
    for day, group in by_day.items():
        views = views_before(results, day or None, fbs, special, conferences)
        for game in group:
            away = views.get(game.get("away_team")) or {}
            home = views.get(game.get("home_team")) or {}
            game["away_slate"] = away.get("label")
            game["home_slate"] = home.get("label")
            game["away_score_rating"] = away.get("score")
            game["home_score_rating"] = home.get("score")


def apply_schedule(expected: dict | None, home_view: dict | None, away_view: dict | None) -> dict | None:
    """Shift the pre-context score by each side's past slate, then keep the same rest gates."""
    if not expected:
        return expected
    expected["schedule"] = None
    if not home_view or not away_view:
        return expected
    if home_view.get("label") == "thin" or away_view.get("label") == "thin":
        return expected
    home_sos = home_view.get("opponent_rating")
    away_sos = away_view.get("opponent_rating")
    if home_sos is None or away_sos is None:
        return expected
    home_shift = max(-SHIFT_CAP, min(SHIFT_CAP, float(home_sos)))
    away_shift = max(-SHIFT_CAP, min(SHIFT_CAP, float(away_sos)))
    # One point of slate gap moves the margin by one point, split across the two scores.
    gap = (home_shift - away_shift) / 2
    raw_home = float(expected.get("raw_home_points", expected["home_points"]))
    raw_away = float(expected.get("raw_away_points", expected["away_points"]))
    home_mult = (float(expected["home_points"]) / raw_home) if raw_home else 1.0
    away_mult = (float(expected["away_points"]) / raw_away) if raw_away else 1.0
    home_pts = max(0.0, round((raw_home + gap) * home_mult, 1))
    away_pts = max(0.0, round((raw_away - gap) * away_mult, 1))
    expected["schedule"] = {
        "away_points": away_pts,
        "home_points": home_pts,
        "total": round(away_pts + home_pts, 1),
        "margin": round(home_pts - away_pts, 1),
        "away_sos": round(float(away_sos), 1),
        "home_sos": round(float(home_sos), 1),
        "away_label": away_view.get("label"),
        "home_label": home_view.get("label"),
        "away_text": away_view.get("text"),
        "home_text": home_view.get("text"),
    }
    return expected
