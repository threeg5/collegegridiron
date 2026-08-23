"""FBS schedule from ESPN when sportsdataverse has not published the season parquet."""

from __future__ import annotations

import json
import urllib.request

import pandas as pd

UA = "collegegridiron-research-desk/0.1 (personal research)"
SCOREBOARD = (
    "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard"
)


def _get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _completed(competition: dict) -> bool:
    status = ((competition.get("status") or {}).get("type") or {})
    return bool(status.get("completed"))


def _score(side: dict, completed: bool):
    if not completed:
        return None
    raw = side.get("score")
    if raw in (None, "", "0") and not completed:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _side(competition: dict, home_away: str) -> dict:
    for item in competition.get("competitors") or []:
        if str(item.get("homeAway") or "").lower() == home_away:
            return item
    return {}


def events_to_raw(events: list[dict], season: int, week: int) -> pd.DataFrame:
    rows = []
    for event in events:
        comps = event.get("competitions") or []
        if not comps:
            continue
        comp = comps[0]
        home = _side(comp, "home")
        away = _side(comp, "away")
        home_team = home.get("team") or {}
        away_team = away.get("team") or {}
        if not home_team or not away_team:
            continue
        done = _completed(comp)
        venue = comp.get("venue") or {}
        rows.append(
            {
                "game_id": str(event.get("id") or comp.get("id") or ""),
                "season": season,
                "week": week,
                "season_type": 2,
                "home_id": str(home_team.get("id") or home.get("id") or ""),
                "away_id": str(away_team.get("id") or away.get("id") or ""),
                "home_team": home_team.get("location") or home_team.get("displayName"),
                "away_team": away_team.get("location") or away_team.get("displayName"),
                "home_division": "fbs",
                "away_division": "fbs",
                "home_points": _score(home, done),
                "away_points": _score(away, done),
                "venue": venue.get("fullName"),
                "venue_id": str(venue.get("id") or "") or None,
                "home_conference": None,
                "away_conference": None,
                "conference_game": bool(comp.get("conferenceCompetition")),
                "neutral_site": bool(comp.get("neutralSite")),
                "start_date": event.get("date") or comp.get("startDate") or comp.get("date"),
            }
        )
    return pd.DataFrame(rows)


def _regular_weeks(payload: dict) -> list[int]:
    leagues = payload.get("leagues") or []
    calendar = (leagues[0].get("calendar") if leagues else None) or []
    for block in calendar:
        if str(block.get("value")) == "2" or str(block.get("label") or "").lower() == "regular season":
            values = []
            for entry in block.get("entries") or []:
                try:
                    values.append(int(entry.get("value")))
                except (TypeError, ValueError):
                    continue
            if values:
                return values
    return list(range(1, 16))


def fetch_espn_week(season: int, week: int, season_type: int = 2) -> dict:
    url = (
        f"{SCOREBOARD}?groups=80&limit=300"
        f"&year={season}&week={week}&seasontype={season_type}"
    )
    print(f"  fetching {url}", flush=True)
    return _get(url)


def load_espn_schedule(season: int) -> pd.DataFrame:
    first = fetch_espn_week(season, 1)
    weeks = _regular_weeks(first)
    frames = [events_to_raw(first.get("events") or [], season, 1)]
    for week in weeks:
        if week == 1:
            continue
        try:
            payload = fetch_espn_week(season, week)
        except Exception as exc:
            print(f"  skip ESPN {season} W{week}: {exc}", flush=True)
            continue
        frames.append(events_to_raw(payload.get("events") or [], season, week))
    frames = [frame for frame in frames if frame is not None and not frame.empty]
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    out = out.drop_duplicates("game_id", keep="last")
    print(f"  ESPN schedule {season}: {len(out)} games", flush=True)
    return out
