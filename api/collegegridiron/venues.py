from __future__ import annotations

import math
import re

# Populated from team_venues at ingest and on DB connect.
TEAM_HOMES: dict[str, tuple[float, float, int]] = {}
TEAM_NAMES: dict[str, str] = {}
TEAM_ELEVATION: dict[str, float] = {}
PACIFIC_TEAMS: set[str] = set()
ALTITUDE_TEAMS: set[str] = set()

TZ_OFFSETS = {
    "america/new_york": -5,
    "america/detroit": -5,
    "america/indiana/indianapolis": -5,
    "america/kentucky/louisville": -5,
    "america/chicago": -6,
    "america/denver": -7,
    "america/phoenix": -7,
    "america/boise": -7,
    "america/los_angeles": -8,
    "america/anchorage": -9,
    "pacific/honolulu": -10,
}

OVERSEAS_STADIUMS: list[tuple[str, float, float, int]] = [
    ("avondale", 53.456, -6.220, 0),
    ("croke", 53.361, -6.251, 0),
    ("dublin", 53.361, -6.251, 0),
    ("melbourne", -37.820, 144.983, 10),
    ("sydney", -33.847, 151.063, 10),
    ("tottenham", 51.604, -0.066, 0),
    ("wembley", 51.556, -0.279, 0),
    ("azteca", 19.303, -99.151, -6),
]
SHORT_MILES = 700.0
ALTITUDE_FEET = 4000.0


def tz_offset(zone: str | None, fallback: int = -5) -> int:
    if not zone:
        return fallback
    return TZ_OFFSETS.get(str(zone).strip().lower(), fallback)


def set_team_homes(rows: list[dict]) -> None:
    TEAM_HOMES.clear()
    TEAM_NAMES.clear()
    TEAM_ELEVATION.clear()
    PACIFIC_TEAMS.clear()
    ALTITUDE_TEAMS.clear()
    for row in rows:
        abbr = str(row.get("team") or "").strip()
        if not abbr:
            continue
        school = row.get("school") or abbr
        mascot = row.get("mascot") or ""
        TEAM_NAMES[abbr] = f"{school} {mascot}".strip()
        lat = row.get("lat")
        lon = row.get("lon")
        tz = row.get("tz_offset")
        if lat is not None and lon is not None and tz is not None:
            TEAM_HOMES[abbr] = (float(lat), float(lon), int(tz))
        elev = row.get("elevation")
        if elev is not None:
            try:
                TEAM_ELEVATION[abbr] = float(elev)
            except (TypeError, ValueError):
                pass
        if tz == -8:
            PACIFIC_TEAMS.add(abbr)
        if elev is not None:
            try:
                if float(elev) >= ALTITUDE_FEET:
                    ALTITUDE_TEAMS.add(abbr)
            except (TypeError, ValueError):
                pass


def load_homes_from_db(conn) -> None:
    try:
        found = conn.execute(
            """
            SELECT team, school, mascot, lat, lon, tz_offset, elevation
            FROM team_venues
            """
        ).fetchall()
    except Exception:
        return
    rows = [dict(row) for row in found]
    if rows:
        set_team_homes(rows)


def team_name(abbr: str | None) -> str:
    if not abbr:
        return "—"
    return TEAM_NAMES.get(abbr, abbr)


def pacific_teams() -> set[str]:
    return set(PACIFIC_TEAMS)


def haversine_miles(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 3958.8 * 2 * math.asin(min(1.0, math.sqrt(h)))


def _norm(text) -> str:
    if text is None:
        return ""
    if isinstance(text, float) and math.isnan(text):
        return ""
    return re.sub(r"\s+", " ", str(text).strip().lower())


def overseas_venue(stadium: str | None, stadium_id: str | None) -> tuple[float, float, int] | None:
    name = _norm(stadium)
    for hint, lat, lon, tz in OVERSEAS_STADIUMS:
        if hint in name:
            return (lat, lon, tz)
    sid = _norm(stadium_id)
    if sid.startswith(("ire", "uk", "aus", "mex")):
        return (51.5, -0.12, 0)
    return None


def venue_for_game(
    home_team: str,
    stadium: str | None,
    stadium_id: str | None,
    location: str | None,
) -> tuple[tuple[float, float], int, bool]:
    overseas = overseas_venue(stadium, stadium_id)
    if overseas:
        lat, lon, tz = overseas
        return (lat, lon), tz, True
    home = TEAM_HOMES.get(home_team)
    if home:
        return (home[0], home[1]), home[2], False
    return (39.0, -98.0), -6, False


def classify_travel(miles: float, is_overseas: bool, at_true_home: bool) -> str:
    if is_overseas:
        return "overseas"
    if at_true_home:
        return "none"
    if miles < SHORT_MILES:
        return "short"
    return "long"


def team_travel(
    team: str,
    is_home_side: bool,
    home_team: str,
    stadium: str | None,
    stadium_id: str | None,
    location: str | None,
) -> dict:
    origin = TEAM_HOMES.get(team)
    venue_xy, venue_tz, is_overseas = venue_for_game(
        home_team, stadium, stadium_id, location
    )
    true_home = (
        bool(is_home_side)
        and not is_overseas
        and (location or "Home").lower() != "neutral"
    )
    if origin is None:
        miles = 0.0 if true_home else None
        tz_change = 0
    else:
        miles = 0.0 if true_home else round(haversine_miles((origin[0], origin[1]), venue_xy), 0)
        tz_change = abs(venue_tz - origin[2])
        if true_home:
            tz_change = 0
    return {
        "travel": classify_travel(miles or 0.0, is_overseas, true_home),
        "travel_miles": miles,
        "tz_change": tz_change,
        "is_overseas": int(is_overseas),
    }


def is_primetime(weekday: str | None, gametime: str | None) -> int:
    day = (weekday or "").title()
    if day in {"Monday", "Tuesday", "Wednesday", "Thursday", "Friday"}:
        hour = _hour(gametime)
        if hour is None or hour >= 17:
            return 1
    hour = _hour(gametime)
    if hour is not None and hour >= 19:
        return 1
    return 0


def is_early_window(weekday: str | None, gametime: str | None) -> int:
    day = (weekday or "").title()
    hour = _hour(gametime)
    if hour is None:
        return 0
    return int(day == "Saturday" and hour <= 13)


def is_altitude_game(home_team: str, stadium: str | None, stadium_id: str | None) -> int:
    if overseas_venue(stadium, stadium_id):
        return 0
    if home_team in ALTITUDE_TEAMS:
        return 1
    name = _norm(stadium)
    if any(token in name for token in ("falcon stadium", "folsom", "war memorial")):
        return 1
    return 0


def surface_group(surface: str | None) -> str | None:
    text = _norm(surface)
    if not text:
        return None
    if "grass" in text:
        return "grass"
    if any(token in text for token in ("turf", "astro", "fieldturf", "a_turf")):
        return "turf"
    return text


def _hour(gametime: str | None) -> int | None:
    if not gametime or ":" not in str(gametime):
        return None
    try:
        return int(str(gametime).split(":")[0])
    except ValueError:
        return None
