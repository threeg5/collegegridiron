from __future__ import annotations

import gc
import io
import math
import re
import urllib.request
from datetime import datetime, timezone

import pandas as pd
import pyarrow.parquet as pq

from collegegridiron.config import (
    REGULAR_LOOKBACK_GAMES,
    REGULAR_PASS_ATT,
    REGULAR_TOUCHES,
    SEASONS,
    ingest_years,
)
from collegegridiron.db import connect, reset_schema
from collegegridiron.venues import (
    is_altitude_game,
    is_early_window,
    is_primetime,
    set_team_homes,
    surface_group,
    team_travel,
    tz_offset,
)

UA = "collegegridiron-research-desk/0.1 (personal research)"

TEAM_INFO_URLS = [
    "https://raw.githubusercontent.com/sportsdataverse/cfbfastR-data/main/team_info/parquet/cfb_team_info_{year}.parquet",
]
SCHEDULE_URLS = [
    "https://raw.githubusercontent.com/sportsdataverse/cfbfastR-data/main/schedules/parquet/cfb_schedules_{year}.parquet",
]
ROSTER_URLS = [
    "https://raw.githubusercontent.com/sportsdataverse/cfbfastR-data/main/rosters/parquet/cfb_rosters_{year}.parquet",
]
PLAYER_BOX_URLS = [
    "https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_cfb_player_box/player_box_{year}.parquet",
]
TEAM_BOX_URLS = [
    "https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_cfb_team_box/team_box_{year}.parquet",
]
ADV_TEAM_URLS = [
    "https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_cfb_adv_team/adv_team_{year}.parquet",
]
BETTING_URLS = [
    "https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_cfb_betting/betting_{year}.parquet",
]

PLAYER_BOX_COLUMNS = [
    "game_id",
    "athlete_id",
    "athlete_name",
    "team_id",
    "team_abbreviation",
    "season",
    "completions/passingAttempts",
    "passingYards",
    "passingTouchdowns",
    "interceptions",
    "sacks",
    "rushingAttempts",
    "rushingYards",
    "rushingTouchdowns",
    "receptions",
    "receivingYards",
    "receivingTouchdowns",
]
ROSTER_COLUMNS = ["athlete_id", "position", "season", "year"]
PLAYER_WEEK_COLUMNS = [
    "player_id",
    "player_name",
    "position",
    "team",
    "opponent",
    "season",
    "week",
    "season_type",
    "game_id",
    "is_home",
    "completions",
    "attempts",
    "passing_yards",
    "passing_tds",
    "interceptions",
    "sacks",
    "carries",
    "rushing_yards",
    "rushing_tds",
    "targets",
    "receptions",
    "receiving_yards",
    "receiving_tds",
    "rushing_receiving_yards",
    "fantasy_points",
    "practice_status",
]

GAME_COLUMNS = [
    "game_id",
    "season",
    "week",
    "season_type",
    "gameday",
    "weekday",
    "home_team",
    "away_team",
    "home_score",
    "away_score",
    "result",
    "total",
    "roof",
    "surface",
    "temp",
    "wind",
    "home_rest",
    "away_rest",
    "spread_line",
    "total_line",
    "home_moneyline",
    "away_moneyline",
    "home_ml_streak",
    "away_ml_streak",
    "home_ats_streak",
    "away_ats_streak",
    "location",
    "stadium",
    "stadium_id",
    "gametime",
    "div_game",
    "is_overseas",
    "is_primetime",
    "is_early_window",
    "is_altitude",
    "surface_group",
    "home_travel",
    "away_travel",
    "home_travel_miles",
    "away_travel_miles",
    "home_tz_change",
    "away_tz_change",
    "home_road_streak",
    "away_road_streak",
    "home_conference",
    "away_conference",
]


def _num(value) -> float | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    if isinstance(value, bool):
        return float(int(value))
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value) -> int | None:
    num = _num(value)
    if num is None:
        return None
    return int(num)


def _str(value) -> str | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return text or None


def _col(df: pd.DataFrame, *names: str) -> str | None:
    lower = {c.lower(): c for c in df.columns}
    for name in names:
        if name.lower() in lower:
            return lower[name.lower()]
    return None


def _series(df: pd.DataFrame, *names: str) -> pd.Series | None:
    cols = []
    seen = set()
    for name in names:
        col = _col(df, name)
        if col and col not in seen:
            cols.append(df[col])
            seen.add(col)
    if not cols:
        return None
    out = cols[0]
    for col in cols[1:]:
        out = out.combine_first(col)
    return out


def parse_slash(value) -> tuple[float | None, float | None]:
    text = _str(value)
    if not text:
        return None, None
    parts = re.split(r"[\/\-]", text.replace(" ", ""), maxsplit=1)
    if len(parts) != 2:
        num = _num(text)
        return num, None
    return _num(parts[0]), _num(parts[1])


def _mem() -> str:
    try:
        import resource

        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        mb = rss / 1024 if rss < 10_000_000 else rss / (1024 * 1024)
        return f"{mb:.0f}MB"
    except Exception:
        return "?"


def fetch_parquet(url: str, columns: list[str] | None = None) -> pd.DataFrame:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=180) as resp:
        payload = resp.read()
    buf = io.BytesIO(payload)
    if not columns:
        return pd.read_parquet(buf)
    names = pq.read_schema(buf).names
    buf.seek(0)
    lower = {name.lower(): name for name in names}
    selected = []
    seen = set()
    for name in columns:
        hit = lower.get(name.lower())
        if hit and hit not in seen:
            selected.append(hit)
            seen.add(hit)
    table = pq.read_table(buf, columns=selected or None)
    return table.to_pandas()


def load_years(
    url_templates: list[str] | str,
    years: list[int],
    columns: list[str] | None = None,
) -> pd.DataFrame:
    templates = [url_templates] if isinstance(url_templates, str) else url_templates
    frames = []
    for year in years:
        loaded = False
        last_error = None
        for template in templates:
            url = template.format(year=year)
            try:
                print(f"  fetching {url}", flush=True)
                frames.append(fetch_parquet(url, columns=columns))
                loaded = True
                break
            except Exception as exc:
                last_error = exc
        if not loaded:
            print(f"  skip {year}: {last_error}", flush=True)
    if not frames:
        return pd.DataFrame()
    if len(frames) == 1:
        return frames[0]
    out = pd.concat(frames, ignore_index=True)
    del frames
    gc.collect()
    return out


def normalize_season_type(value) -> str:
    text = str(value or "").strip().lower()
    if text in {"3", "post", "postseason", "bowl", "playoff"}:
        return "POST"
    if text in {"1", "pre", "preseason"}:
        return "PRE"
    return "REG"


def infer_position(row: pd.Series) -> str | None:
    attempts = _num(row.get("attempts")) or 0
    carries = _num(row.get("carries")) or 0
    receptions = _num(row.get("receptions")) or 0
    if attempts >= 8:
        return "QB"
    if carries >= 8 and carries >= receptions:
        return "RB"
    if receptions >= 3:
        return "WR"
    if carries >= 3:
        return "RB"
    return None


def fantasy_points(row: dict) -> float:
    return round(
        (_num(row.get("passing_yards")) or 0) / 25
        + (_num(row.get("passing_tds")) or 0) * 4
        - (_num(row.get("interceptions")) or 0) * 2
        + (_num(row.get("rushing_yards")) or 0) / 10
        + (_num(row.get("rushing_tds")) or 0) * 6
        + (_num(row.get("receptions")) or 0)
        + (_num(row.get("receiving_yards")) or 0) / 10
        + (_num(row.get("receiving_tds")) or 0) * 6,
        2,
    )


def prepare_team_venues(raw: pd.DataFrame) -> pd.DataFrame:
    if raw.empty:
        return raw
    school = _series(raw, "school", "team")
    abbr = _series(raw, "abbreviation")
    classification = _series(raw, "classification")
    frame = pd.DataFrame(
        {
            "team": abbr if abbr is not None else school,
            "team_id": _series(raw, "team_id"),
            "school": school,
            "mascot": _series(raw, "mascot"),
            "conference": _series(raw, "conference"),
            "classification": classification,
            "lat": pd.to_numeric(_series(raw, "latitude"), errors="coerce") if _series(raw, "latitude") is not None else None,
            "lon": pd.to_numeric(_series(raw, "longitude"), errors="coerce") if _series(raw, "longitude") is not None else None,
            "tz_offset": None,
            "elevation": pd.to_numeric(_series(raw, "elevation"), errors="coerce") if _series(raw, "elevation") is not None else None,
            "venue_name": _series(raw, "venue_name", "venue"),
            "city": _series(raw, "city"),
            "state": _series(raw, "state"),
            "grass": None,
            "dome": None,
        }
    )
    zone = _series(raw, "timezone")
    if zone is not None:
        frame["tz_offset"] = zone.map(lambda z: tz_offset(_str(z)))
    grass = _series(raw, "grass")
    dome = _series(raw, "dome")
    if grass is not None:
        frame["grass"] = grass.map(lambda v: 1 if bool(v) and not (isinstance(v, float) and math.isnan(v)) else 0)
    if dome is not None:
        frame["dome"] = dome.map(lambda v: 1 if bool(v) and not (isinstance(v, float) and math.isnan(v)) else 0)
    class_text = frame["classification"].fillna("").astype(str).str.lower()
    frame = frame[class_text.str.contains("fbs")]
    frame = frame.dropna(subset=["team"])
    frame["team"] = frame["team"].astype(str).str.strip()
    frame["team_id"] = frame["team_id"].map(lambda v: _str(v))
    return frame.drop_duplicates("team", keep="last")


def compute_rest(games: pd.DataFrame) -> pd.DataFrame:
    work = games.copy()
    work["sort_day"] = pd.to_datetime(work["gameday"], errors="coerce")
    work = work.sort_values(["sort_day", "game_id"])
    last_played: dict[str, pd.Timestamp] = {}
    home_rest, away_rest = [], []
    for row in work.itertuples(index=False):
        day = getattr(row, "sort_day")
        home = row.home_team
        away = row.away_team
        if pd.isna(day):
            home_rest.append(None)
            away_rest.append(None)
            continue
        prev_home = last_played.get(home)
        prev_away = last_played.get(away)
        home_rest.append(None if prev_home is None else int((day - prev_home).days))
        away_rest.append(None if prev_away is None else int((day - prev_away).days))
        if _num(getattr(row, "home_score", None)) is not None:
            last_played[home] = day
            last_played[away] = day
    work["home_rest"] = home_rest
    work["away_rest"] = away_rest
    return work.drop(columns=["sort_day"])


def compute_streaks(games: pd.DataFrame) -> pd.DataFrame:
    games = games.copy()
    games["gameday_sort"] = pd.to_datetime(games["gameday"], errors="coerce")
    games = games.sort_values(["gameday_sort", "game_id"])

    home_ml, away_ml, home_ats, away_ats = [], [], [], []
    ml_streak: dict[str, int] = {}
    ats_streak: dict[str, int] = {}

    def next_streak(current: int, won: bool | None) -> int:
        if won is None:
            return current
        if won:
            return current + 1 if current >= 0 else 1
        return current - 1 if current <= 0 else -1

    for row in games.itertuples(index=False):
        home = row.home_team
        away = row.away_team
        home_ml.append(ml_streak.get(home, 0))
        away_ml.append(ml_streak.get(away, 0))
        home_ats.append(ats_streak.get(home, 0))
        away_ats.append(ats_streak.get(away, 0))

        result = _num(getattr(row, "result", None))
        spread = _num(getattr(row, "spread_line", None))
        if result is None:
            continue

        home_won = True if result > 0 else False if result < 0 else None
        ml_streak[home] = next_streak(ml_streak.get(home, 0), home_won)
        ml_streak[away] = next_streak(
            ml_streak.get(away, 0), None if home_won is None else not home_won
        )

        if spread is None:
            continue
        if result > spread:
            home_cover, away_cover = True, False
        elif result < spread:
            home_cover, away_cover = False, True
        else:
            home_cover = away_cover = None
        ats_streak[home] = next_streak(ats_streak.get(home, 0), home_cover)
        ats_streak[away] = next_streak(ats_streak.get(away, 0), away_cover)

    games["home_ml_streak"] = home_ml
    games["away_ml_streak"] = away_ml
    games["home_ats_streak"] = home_ats
    games["away_ats_streak"] = away_ats
    return games.drop(columns=["gameday_sort"])


def enrich_games(games: pd.DataFrame) -> pd.DataFrame:
    games = games.copy()
    home_travel, away_travel = [], []
    home_miles, away_miles = [], []
    home_tz, away_tz = [], []
    overseas, primetime, early, altitude, surfaces = [], [], [], [], []

    for row in games.itertuples(index=False):
        stadium = getattr(row, "stadium", None)
        stadium_id = getattr(row, "stadium_id", None)
        location = getattr(row, "location", "Home")
        home = team_travel(row.home_team, True, row.home_team, stadium, stadium_id, location)
        away = team_travel(row.away_team, False, row.home_team, stadium, stadium_id, location)
        home_travel.append(home["travel"])
        away_travel.append(away["travel"])
        home_miles.append(home["travel_miles"])
        away_miles.append(away["travel_miles"])
        home_tz.append(home["tz_change"])
        away_tz.append(away["tz_change"])
        overseas.append(home["is_overseas"])
        primetime.append(is_primetime(getattr(row, "weekday", None), getattr(row, "gametime", None)))
        early.append(is_early_window(getattr(row, "weekday", None), getattr(row, "gametime", None)))
        altitude.append(is_altitude_game(row.home_team, stadium, stadium_id))
        surfaces.append(surface_group(getattr(row, "surface", None)))

    games["home_travel"] = home_travel
    games["away_travel"] = away_travel
    games["home_travel_miles"] = home_miles
    games["away_travel_miles"] = away_miles
    games["home_tz_change"] = home_tz
    games["away_tz_change"] = away_tz
    games["is_overseas"] = overseas
    games["is_primetime"] = primetime
    games["is_early_window"] = early
    games["is_altitude"] = altitude
    games["surface_group"] = surfaces
    games["div_game"] = pd.to_numeric(games["div_game"], errors="coerce").fillna(0).astype(int)
    games["home_moneyline"] = None
    games["away_moneyline"] = None
    games["temp"] = None
    games["wind"] = None
    return add_road_streaks(games)


def add_road_streaks(games: pd.DataFrame) -> pd.DataFrame:
    work = games.copy()
    work["sort_day"] = pd.to_datetime(work["gameday"], errors="coerce")
    work = work.sort_values(["sort_day", "game_id"])
    home_streaks, away_streaks = [], []
    road_streak: dict[str, int] = {}
    for row in work.itertuples(index=False):
        home_streaks.append(road_streak.get(row.home_team, 0))
        away_streaks.append(road_streak.get(row.away_team, 0))
        home_on_road = row.home_travel != "none"
        away_on_road = row.away_travel != "none"
        if _num(getattr(row, "result", None)) is None:
            continue
        road_streak[row.home_team] = road_streak.get(row.home_team, 0) + 1 if home_on_road else 0
        road_streak[row.away_team] = road_streak.get(row.away_team, 0) + 1 if away_on_road else 0
    work["home_road_streak"] = home_streaks
    work["away_road_streak"] = away_streaks
    return work.drop(columns=["sort_day"])


def prepare_games(raw: pd.DataFrame, venues: pd.DataFrame, betting: pd.DataFrame) -> pd.DataFrame:
    if raw.empty:
        return raw
    school_to_abbr = {}
    id_to_abbr = {}
    venue_by_abbr = {}
    for row in venues.itertuples(index=False):
        abbr = _str(row.team)
        if not abbr:
            continue
        if _str(row.school):
            school_to_abbr[_str(row.school).lower()] = abbr
        if _str(row.team_id):
            id_to_abbr[_str(row.team_id)] = abbr
        venue_by_abbr[abbr] = row

    home_id = _series(raw, "home_id")
    away_id = _series(raw, "away_id")
    home_school = _series(raw, "home_team")
    away_school = _series(raw, "away_team")
    home_div = _series(raw, "home_division", "home_classification")
    away_div = _series(raw, "away_division", "away_classification")

    def map_team(team_id, school):
        abbr = id_to_abbr.get(_str(team_id) or "")
        if abbr:
            return abbr
        return school_to_abbr.get((_str(school) or "").lower(), _str(school))

    frame = pd.DataFrame(
        {
            "game_id": _series(raw, "game_id").map(lambda v: _str(v)),
            "season": pd.to_numeric(_series(raw, "season"), errors="coerce"),
            "week": pd.to_numeric(_series(raw, "week"), errors="coerce"),
            "season_type": _series(raw, "season_type").map(normalize_season_type)
            if _series(raw, "season_type") is not None
            else "REG",
            "home_team": [map_team(i, s) for i, s in zip(home_id, home_school)],
            "away_team": [map_team(i, s) for i, s in zip(away_id, away_school)],
            "home_score": pd.to_numeric(_series(raw, "home_points", "home_score"), errors="coerce"),
            "away_score": pd.to_numeric(_series(raw, "away_points", "away_score"), errors="coerce"),
            "stadium": _series(raw, "venue"),
            "stadium_id": _series(raw, "venue_id").map(lambda v: _str(v)) if _series(raw, "venue_id") is not None else None,
            "home_conference": _series(raw, "home_conference"),
            "away_conference": _series(raw, "away_conference"),
            "div_game": _series(raw, "conference_game").map(lambda v: 1 if bool(v) and not (isinstance(v, float) and math.isnan(v)) else 0)
            if _series(raw, "conference_game") is not None
            else 0,
            "neutral": _series(raw, "neutral_site") if _series(raw, "neutral_site") is not None else False,
        }
    )
    fbs_abbrs = set(venues["team"].astype(str))
    home_is_fbs = frame["home_team"].isin(fbs_abbrs)
    away_is_fbs = frame["away_team"].isin(fbs_abbrs)
    if home_div is not None:
        home_div_fbs = home_div.fillna("").astype(str).str.lower().str.contains("fbs")
        away_div_fbs = (
            away_div.fillna("").astype(str).str.lower().str.contains("fbs")
            if away_div is not None
            else False
        )
        frame = frame[home_is_fbs | away_is_fbs | home_div_fbs | away_div_fbs]
    else:
        frame = frame[home_is_fbs | away_is_fbs]
    frame = frame.dropna(subset=["game_id", "home_team", "away_team", "season", "week"])

    start = _series(raw, "start_date")
    kick = pd.to_datetime(start, errors="coerce", utc=True) if start is not None else pd.NaT
    if isinstance(kick, pd.Series):
        kick = kick.reindex(raw.index)
        aligned = kick.loc[frame.index] if hasattr(frame.index, "isin") else kick
        try:
            eastern = aligned.dt.tz_convert("America/New_York")
        except Exception:
            eastern = aligned
        frame["gameday"] = eastern.dt.strftime("%Y-%m-%d")
        frame["weekday"] = eastern.dt.day_name()
        frame["gametime"] = eastern.dt.strftime("%H:%M")
    else:
        frame["gameday"] = None
        frame["weekday"] = None
        frame["gametime"] = None

    frame["location"] = [
        "Neutral" if bool(n) and not (isinstance(n, float) and math.isnan(n)) else "Home"
        for n in frame["neutral"]
    ]
    frame["result"] = frame["home_score"] - frame["away_score"]
    frame["total"] = frame["home_score"] + frame["away_score"]

    roof, surface = [], []
    for team in frame["home_team"]:
        info = venue_by_abbr.get(team)
        if info is None:
            roof.append(None)
            surface.append(None)
            continue
        dome = getattr(info, "dome", None)
        grass = getattr(info, "grass", None)
        roof.append("dome" if dome else "outdoors")
        surface.append("grass" if grass else "turf")
    frame["roof"] = roof
    frame["surface"] = surface

    if not betting.empty:
        bet = betting.copy()
        gid = _series(bet, "game_id")
        if gid is not None:
            bet["game_id"] = gid.map(lambda v: _str(v))
            spread = _series(bet, "home_team_spread")
            total_line = _series(bet, "over_under")
            available = _series(bet, "game_spread_available")
            slim = pd.DataFrame({"game_id": bet["game_id"]})
            slim["spread_line"] = spread if spread is not None else None
            slim["total_line"] = total_line if total_line is not None else None
            if available is not None:
                ok = available.fillna(False).astype(bool)
                slim.loc[~ok, "spread_line"] = None
            slim = slim.drop_duplicates("game_id", keep="last")
            frame = frame.merge(slim, on="game_id", how="left")
    if "spread_line" not in frame.columns:
        frame["spread_line"] = None
    if "total_line" not in frame.columns:
        frame["total_line"] = None

    frame = compute_rest(frame)
    frame = compute_streaks(frame)
    frame = enrich_games(frame)
    for col in GAME_COLUMNS:
        if col not in frame.columns:
            frame[col] = None
    return frame[GAME_COLUMNS].drop_duplicates("game_id", keep="last")


def prepare_team_weeks(
    box: pd.DataFrame, adv: pd.DataFrame, games: pd.DataFrame, venues: pd.DataFrame
) -> pd.DataFrame:
    if box.empty or games.empty:
        return pd.DataFrame()
    id_to_abbr = {
        _str(row.team_id): row.team
        for row in venues.itertuples(index=False)
        if _str(row.team_id)
    }
    team_id = _series(box, "team_id")
    abbr_col = _series(box, "team_abbreviation")
    mapped = team_id.map(lambda v: id_to_abbr.get(_str(v))) if team_id is not None else None
    team = mapped.combine_first(abbr_col) if mapped is not None and abbr_col is not None else mapped or abbr_col
    gid = _series(box, "game_id").map(lambda v: _str(v))
    home_away = _series(box, "home_away")
    comp_att = _series(box, "completionAttempts")
    comps, atts = [], []
    if comp_att is not None:
        for value in comp_att:
            c, a = parse_slash(value)
            comps.append(c)
            atts.append(a)
    else:
        comps = [None] * len(box)
        atts = [None] * len(box)

    frame = pd.DataFrame(
        {
            "game_id": gid,
            "team": team,
            "is_home": home_away.fillna("").astype(str).str.lower().eq("home").astype(int)
            if home_away is not None
            else None,
            "season": pd.to_numeric(_series(box, "season"), errors="coerce"),
            "completions": comps,
            "attempts": atts,
            "passing_yards": pd.to_numeric(_series(box, "netPassingYards", "passingYards"), errors="coerce"),
            "interceptions": pd.to_numeric(_series(box, "interceptions"), errors="coerce"),
            "carries": pd.to_numeric(_series(box, "rushingAttempts"), errors="coerce"),
            "rushing_yards": pd.to_numeric(_series(box, "rushingYards"), errors="coerce"),
            "rushing_fumbles_lost": pd.to_numeric(_series(box, "fumblesLost"), errors="coerce"),
            "def_interceptions": None,
            "passing_tds": None,
            "rushing_tds": None,
            "sacks_suffered": None,
            "sack_fumbles_lost": None,
            "def_sacks": None,
            "passing_epa": None,
            "rushing_epa": None,
        }
    )
    frame = frame.dropna(subset=["game_id", "team"])
    lookup = {}
    for row in games.itertuples(index=False):
        lookup[row.game_id] = (row.season, row.week, row.season_type, row.home_team, row.away_team)
    seasons, weeks, types, opponents, is_home = [], [], [], [], []
    for row in frame.itertuples(index=False):
        hit = lookup.get(row.game_id)
        if not hit:
            seasons.append(row.season)
            weeks.append(None)
            types.append("REG")
            opponents.append(None)
            is_home.append(row.is_home)
            continue
        seasons.append(hit[0])
        weeks.append(hit[1])
        types.append(hit[2])
        home, away = hit[3], hit[4]
        if row.team == home:
            opponents.append(away)
            is_home.append(1)
        else:
            opponents.append(home)
            is_home.append(0)
    frame["season"] = seasons
    frame["week"] = weeks
    frame["season_type"] = types
    frame["opponent"] = opponents
    frame["is_home"] = is_home
    frame = frame.dropna(subset=["team", "season", "week"])

    if not adv.empty:
        adv_gid = _series(adv, "game_id").map(lambda v: _str(v))
        adv_team_id = _series(adv, "pos_team_id")
        adv_team = adv_team_id.map(lambda v: id_to_abbr.get(_str(v))) if adv_team_id is not None else None
        if adv_team is None:
            adv_team = _series(adv, "pos_team")
        epa_pass = _series(adv, "EPA_passing_overall")
        epa_rush = _series(adv, "EPA_rushing_overall")
        slim = pd.DataFrame(
            {
                "game_id": adv_gid,
                "team": adv_team,
                "passing_epa": epa_pass,
                "rushing_epa": epa_rush,
            }
        ).dropna(subset=["game_id", "team"])
        slim = slim.drop_duplicates(["game_id", "team"], keep="last")
        frame = frame.drop(columns=["passing_epa", "rushing_epa"])
        frame = frame.merge(slim, on=["game_id", "team"], how="left")

    return frame.drop_duplicates(["season", "week", "season_type", "team"], keep="last")


def prepare_player_weeks(
    box: pd.DataFrame,
    rosters: pd.DataFrame,
    games: pd.DataFrame,
    venues: pd.DataFrame,
) -> pd.DataFrame:
    if box.empty or games.empty:
        return pd.DataFrame()
    id_to_abbr = {
        _str(row.team_id): row.team
        for row in venues.itertuples(index=False)
        if _str(row.team_id)
    }
    keep_ids = set(games["game_id"].astype(str))
    gid = _series(box, "game_id")
    if gid is None:
        return pd.DataFrame()
    gid = gid.map(lambda v: _str(v))
    mask = gid.isin(keep_ids)
    work = box.loc[mask]
    if work.empty:
        return pd.DataFrame()
    work = work.copy()
    work["_gid"] = gid.loc[mask]

    player_id = _series(work, "athlete_id").map(lambda v: _str(v))
    name = _series(work, "athlete_name")
    team_id = _series(work, "team_id")
    team = team_id.map(lambda v: id_to_abbr.get(_str(v))) if team_id is not None else None
    if team is None:
        team = _series(work, "team_abbreviation")

    comp_att = _series(work, "completions/passingAttempts")
    comps, atts = [], []
    if comp_att is not None:
        for value in comp_att:
            c, a = parse_slash(value)
            comps.append(c)
            atts.append(a)
    else:
        comps = [None] * len(work)
        atts = [None] * len(work)

    raw = pd.DataFrame(
        {
            "player_id": player_id,
            "player_name": name,
            "team": team,
            "game_id": work["_gid"],
            "season": pd.to_numeric(_series(work, "season"), errors="coerce"),
            "completions": comps,
            "attempts": atts,
            "passing_yards": pd.to_numeric(_series(work, "passingYards"), errors="coerce"),
            "passing_tds": pd.to_numeric(_series(work, "passingTouchdowns"), errors="coerce"),
            "interceptions": pd.to_numeric(_series(work, "interceptions"), errors="coerce"),
            "sacks": pd.to_numeric(_series(work, "sacks"), errors="coerce"),
            "carries": pd.to_numeric(_series(work, "rushingAttempts"), errors="coerce"),
            "rushing_yards": pd.to_numeric(_series(work, "rushingYards"), errors="coerce"),
            "rushing_tds": pd.to_numeric(_series(work, "rushingTouchdowns"), errors="coerce"),
            "receptions": pd.to_numeric(_series(work, "receptions"), errors="coerce"),
            "receiving_yards": pd.to_numeric(_series(work, "receivingYards"), errors="coerce"),
            "receiving_tds": pd.to_numeric(_series(work, "receivingTouchdowns"), errors="coerce"),
        }
    )
    raw = raw.dropna(subset=["player_id", "player_name", "game_id"])
    stat_cols = [
        "completions",
        "attempts",
        "passing_yards",
        "passing_tds",
        "interceptions",
        "sacks",
        "carries",
        "rushing_yards",
        "rushing_tds",
        "receptions",
        "receiving_yards",
        "receiving_tds",
    ]
    grouped = raw.groupby(["player_id", "game_id"], as_index=False).agg(
        {
            "player_name": "first",
            "team": "first",
            "season": "first",
            **{col: "max" for col in stat_cols},
        }
    )
    grouped["targets"] = grouped["receptions"]
    grouped["rushing_receiving_yards"] = grouped["rushing_yards"].fillna(0) + grouped[
        "receiving_yards"
    ].fillna(0)
    grouped["fantasy_points"] = (
        grouped["passing_yards"].fillna(0) / 25
        + grouped["passing_tds"].fillna(0) * 4
        - grouped["interceptions"].fillna(0) * 2
        + grouped["rushing_yards"].fillna(0) / 10
        + grouped["rushing_tds"].fillna(0) * 6
        + grouped["receptions"].fillna(0)
        + grouped["receiving_yards"].fillna(0) / 10
        + grouped["receiving_tds"].fillna(0) * 6
    ).round(2)
    grouped["practice_status"] = "none"

    lookup = {
        row.game_id: (row.season, row.week, row.season_type, row.home_team, row.away_team)
        for row in games.itertuples(index=False)
    }
    weeks, types, opponents, is_home, seasons = [], [], [], [], []
    for row in grouped.itertuples(index=False):
        hit = lookup.get(row.game_id)
        if not hit:
            weeks.append(None)
            types.append("REG")
            opponents.append(None)
            is_home.append(None)
            seasons.append(row.season)
            continue
        seasons.append(hit[0])
        weeks.append(hit[1])
        types.append(hit[2])
        home, away = hit[3], hit[4]
        if row.team == home:
            opponents.append(away)
            is_home.append(1)
        else:
            opponents.append(home)
            is_home.append(0)
    grouped["season"] = seasons
    grouped["week"] = weeks
    grouped["season_type"] = types
    grouped["opponent"] = opponents
    grouped["is_home"] = is_home

    pos_map = {}
    if not rosters.empty:
        rid = _series(rosters, "athlete_id")
        rpos = _series(rosters, "position")
        rseason = _series(rosters, "season", "year")
        if rid is not None and rpos is not None:
            for pid, pos, season in zip(rid, rpos, rseason if rseason is not None else [None] * len(rid)):
                key = (_str(pid), _int(season))
                if key[0] and _str(pos):
                    pos_map[key] = _str(pos)
                    pos_map[key[0]] = _str(pos)
    grouped["position"] = [
        pos_map.get((row.player_id, _int(row.season))) or pos_map.get(row.player_id)
        for row in grouped.itertuples(index=False)
    ]
    missing_pos = grouped["position"].isna()
    if missing_pos.any():
        grouped.loc[missing_pos, "position"] = grouped.loc[missing_pos].apply(infer_position, axis=1)

    grouped = grouped.dropna(subset=["player_id", "player_name", "week"])
    return grouped.drop_duplicates(["player_id", "season", "week", "season_type"], keep="last")


def prepare_missing_regulars(player_weeks: pd.DataFrame, games: pd.DataFrame) -> pd.DataFrame:
    if player_weeks.empty or games.empty:
        return pd.DataFrame()
    work = player_weeks.copy()
    work["touches"] = (
        work["carries"].fillna(0) + work["receptions"].fillna(0) + work["attempts"].fillna(0)
    )
    work["_ord"] = (work["season"] * 100 + work["week"]).astype("int64")
    work = work.sort_values(["player_id", "team", "_ord"])
    work["touches_recent"] = work.groupby(["player_id", "team"])["touches"].transform(
        lambda s: s.rolling(REGULAR_LOOKBACK_GAMES, min_periods=2).mean()
    )
    work["attempts_recent"] = work.groupby(["player_id", "team"])["attempts"].transform(
        lambda s: s.rolling(REGULAR_LOOKBACK_GAMES, min_periods=2).mean()
    )
    appeared = work[["player_id", "season", "week", "team"]].drop_duplicates()
    appeared["appeared"] = 1

    team_games = pd.concat(
        [
            games[["season", "week", "home_team"]].rename(columns={"home_team": "team"}),
            games[["season", "week", "away_team"]].rename(columns={"away_team": "team"}),
        ],
        ignore_index=True,
    ).drop_duplicates()
    team_games["_ord"] = (team_games["season"] * 100 + team_games["week"]).astype("int64")

    usage_hist = (
        work.dropna(subset=["player_id", "team", "_ord"])
        .sort_values("_ord")
        .drop_duplicates(["player_id", "team", "_ord"], keep="last")[
            ["player_id", "player_name", "position", "team", "_ord", "touches_recent", "attempts_recent"]
        ]
    )
    seasons_played = work[["player_id", "team", "season"]].drop_duplicates()
    players = work[["player_id", "player_name", "position", "team"]].drop_duplicates()
    grid = players.merge(seasons_played, on=["player_id", "team"])
    grid = grid.merge(team_games, on=["team", "season"], how="inner")
    grid = grid.merge(appeared, on=["player_id", "season", "week", "team"], how="left")
    hist = usage_hist.sort_values("_ord")
    grid = grid.sort_values("_ord")
    merged = pd.merge_asof(
        grid,
        hist.rename(
            columns={
                "touches_recent": "touches_join",
                "attempts_recent": "attempts_join",
                "player_name": "name_join",
                "position": "pos_join",
            }
        ),
        by=["player_id", "team"],
        on="_ord",
        direction="backward",
        allow_exact_matches=True,
    )
    merged["touches_recent"] = pd.to_numeric(merged["touches_join"], errors="coerce")
    merged["attempts_recent"] = pd.to_numeric(merged["attempts_join"], errors="coerce")
    missing = merged[merged["appeared"].isna()].copy()
    missing = missing[
        (missing["touches_recent"].fillna(0) >= REGULAR_TOUCHES)
        | (missing["attempts_recent"].fillna(0) >= REGULAR_PASS_ATT)
    ]
    if missing.empty:
        return pd.DataFrame()
    missing["player_name"] = missing["player_name"].combine_first(missing["name_join"])
    missing["position"] = missing["position"].combine_first(missing["pos_join"])
    missing["side"] = "offense"
    missing["snap_pct_recent"] = missing["touches_recent"].round(1)
    missing["status"] = "DNP"
    missing["injury"] = "Did not appear in box score"
    return missing[
        [
            "season",
            "week",
            "team",
            "player_id",
            "player_name",
            "position",
            "side",
            "snap_pct_recent",
            "status",
            "injury",
        ]
    ].drop_duplicates(["season", "week", "team", "player_id"])


def _cell(value):
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "isoformat") and not isinstance(value, (str, bytes)):
        try:
            return value.isoformat()
        except (TypeError, ValueError):
            pass
    if hasattr(value, "item"):
        try:
            return value.item()
        except (ValueError, AttributeError):
            pass
    return value


def write_frame(
    conn, table: str, frame: pd.DataFrame, columns: list[str], replace: bool = True
) -> None:
    if replace:
        conn.execute(f"DELETE FROM {table}")
    if frame is None or frame.empty:
        conn.commit()
        print(f"  {table}: 0 rows", flush=True)
        return
    subset = frame.reindex(columns=columns)
    records = [
        tuple(_cell(v) for v in row)
        for row in subset.itertuples(index=False, name=None)
    ]
    placeholders = ",".join("?" for _ in columns)
    conn.executemany(
        f"INSERT INTO {table} ({','.join(columns)}) VALUES ({placeholders})",
        records,
    )
    conn.commit()
    print(f"  {table}: {len(records)} rows", flush=True)


def run_ingest(years: list[int] | None = None) -> dict:
    years = years or ingest_years() or SEASONS
    print(f"Ingesting FBS seasons {years[0]}-{years[-1]} (rss={_mem()})", flush=True)
    conn = connect()
    reset_schema(conn)

    print("Team directory", flush=True)
    info = load_years(TEAM_INFO_URLS, years)
    venues = prepare_team_venues(info)
    del info
    gc.collect()
    set_team_homes(venues.to_dict("records"))
    write_frame(
        conn,
        "team_venues",
        venues,
        [
            "team",
            "team_id",
            "school",
            "mascot",
            "conference",
            "classification",
            "lat",
            "lon",
            "tz_offset",
            "elevation",
            "venue_name",
            "city",
            "state",
            "grass",
            "dome",
        ],
    )

    print("Schedules", flush=True)
    schedules = load_years(SCHEDULE_URLS, years)
    print("Betting lines", flush=True)
    betting = load_years(BETTING_URLS, years)
    games = prepare_games(schedules, venues, betting)
    del schedules, betting
    gc.collect()
    write_frame(conn, "games", games, GAME_COLUMNS)

    print("Weekly team stats", flush=True)
    team_box = load_years(TEAM_BOX_URLS, years)
    adv = load_years(ADV_TEAM_URLS, years)
    team_weeks = prepare_team_weeks(team_box, adv, games, venues)
    del team_box, adv
    gc.collect()
    write_frame(
        conn,
        "team_weeks",
        team_weeks,
        [
            "season",
            "week",
            "season_type",
            "game_id",
            "team",
            "opponent",
            "is_home",
            "completions",
            "attempts",
            "passing_yards",
            "passing_tds",
            "interceptions",
            "sacks_suffered",
            "passing_epa",
            "carries",
            "rushing_yards",
            "rushing_tds",
            "rushing_epa",
            "rushing_fumbles_lost",
            "sack_fumbles_lost",
            "def_sacks",
            "def_interceptions",
        ],
    )
    team_week_count = 0 if team_weeks is None else len(team_weeks)
    del team_weeks
    gc.collect()
    print(f"  after team weeks rss={_mem()}", flush=True)

    latest_players: dict[str, tuple] = {}
    player_week_count = 0
    for year in years:
        print(f"Weekly player stats {year} (rss={_mem()})", flush=True)
        player_box = load_years(PLAYER_BOX_URLS, [year], columns=PLAYER_BOX_COLUMNS)
        rosters = load_years(ROSTER_URLS, [year], columns=ROSTER_COLUMNS)
        player_weeks = prepare_player_weeks(player_box, rosters, games, venues)
        del player_box, rosters
        gc.collect()
        print(f"  player_weeks {year}: {len(player_weeks)} rss={_mem()}", flush=True)
        if not player_weeks.empty:
            for row in player_weeks.itertuples(index=False):
                latest_players[row.player_id] = (
                    row.player_id,
                    row.player_name,
                    row.position,
                    row.team,
                )
            write_frame(conn, "player_weeks", player_weeks, PLAYER_WEEK_COLUMNS, replace=False)
            player_week_count += len(player_weeks)
        del player_weeks
        gc.collect()

    if latest_players:
        latest = pd.DataFrame(
            latest_players.values(),
            columns=["player_id", "player_name", "position", "latest_team"],
        )
        write_frame(conn, "players", latest, ["player_id", "player_name", "position", "latest_team"])
        del latest, latest_players
        gc.collect()

    print(f"Missing regulars (box-score DNPs) rss={_mem()}", flush=True)
    player_weeks = pd.read_sql_query(
        """
        SELECT player_id, player_name, position, team, season, week,
               carries, receptions, attempts
        FROM player_weeks
        """,
        conn,
    )
    missing = prepare_missing_regulars(player_weeks, games)
    del player_weeks
    gc.collect()
    write_frame(
        conn,
        "missing_regulars",
        missing,
        [
            "season",
            "week",
            "team",
            "player_id",
            "player_name",
            "position",
            "side",
            "snap_pct_recent",
            "status",
            "injury",
        ],
    )
    del missing
    gc.collect()

    conn.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
        ("ingested_at", datetime.now(timezone.utc).isoformat()),
    )
    conn.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
        ("seasons", ",".join(str(y) for y in years)),
    )
    conn.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
        ("ingest_complete", "1"),
    )
    conn.commit()
    conn.close()
    print(f"Done. rss={_mem()}", flush=True)
    return {
        "seasons": years,
        "games": 0 if games is None else len(games),
        "team_weeks": team_week_count,
        "player_weeks": player_week_count,
    }


if __name__ == "__main__":
    run_ingest()
