"""How old the college slate refresh is relative to this game / week.

A live pull refreshes ESPN scores on a cooldown (shorter Thu–Sun).
College football has no official injury report.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from collegegridiron.slate import resolve_slate, rows

FRESH_HOURS = 18
STALE_HOURS = 36
LATE_HOURS = 36
NOTE = (
    "No official college injury report. Regulars out are recent high-usage "
    "players who did not appear in the box score. Scores refresh from ESPN."
)


def parse_dt(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        stamp = value
    else:
        text = str(value).strip()
        if not text:
            return None
        try:
            stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            try:
                stamp = datetime.strptime(text[:19], "%Y-%m-%d %H:%M:%S")
            except ValueError:
                try:
                    stamp = datetime.strptime(text[:10], "%Y-%m-%d")
                except ValueError:
                    return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(timezone.utc)


def _hours_ago(stamp: datetime | None, now: datetime | None = None) -> float | None:
    if stamp is None:
        return None
    now = now or datetime.now(timezone.utc)
    return max(0.0, (now - stamp).total_seconds() / 3600.0)


def _meta_stamp(conn, key: str) -> datetime | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    if not row:
        return None
    return parse_dt(row["value"])


def _status(hours: float | None) -> str:
    if hours is None:
        return "none"
    if hours < FRESH_HOURS:
        return "fresh"
    if hours < STALE_HOURS:
        return "aging"
    return "stale"


def _label(status: str, newest: datetime | None, hours: float | None) -> str:
    if status == "none" or newest is None:
        return "No refresh stamp on file"
    when = newest.strftime("%a ") + newest.strftime("%I:%M%p").lstrip("0")
    age = f"{hours:.0f}h old" if hours is not None else ""
    word = {"fresh": "Fresh", "aging": "Aging", "stale": "Stale"}.get(status, "Report")
    return " · ".join(part for part in (f"{word} report {when}", age) if part)


def _late_window(game: dict | None, now: datetime) -> bool:
    if not game:
        return now.weekday() >= 3  # Thu–Sun slate window
    weekday = (game.get("weekday") or "").strip().lower()
    if weekday in {"thursday", "friday", "saturday", "sunday"}:
        return True
    gameday = parse_dt(game.get("gameday"))
    if gameday is None:
        return False
    kick = gameday
    time_text = (game.get("gametime") or "").strip()
    if time_text:
        try:
            hh, mm = time_text.split(":")[:2]
            kick = kick.replace(hour=int(hh), minute=int(mm))
        except (TypeError, ValueError):
            pass
    return kick - now <= timedelta(hours=LATE_HOURS)


def _newest_for(conn, season: int, week: int, teams: list[str] | None) -> datetime | None:
    params: list[object] = [season, week]
    team_sql = ""
    if teams:
        marks = ",".join("?" for _ in teams)
        team_sql = f" AND team IN ({marks})"
        params.extend(teams)
    found = rows(
        conn,
        f"""
        SELECT MAX(date_modified) AS newest
        FROM injuries
        WHERE season = ? AND week = ?{team_sql}
          AND date_modified IS NOT NULL
          AND TRIM(date_modified) != ''
        """,
        tuple(params),
    )
    if found and found[0].get("newest"):
        return parse_dt(found[0]["newest"])
    miss = rows(
        conn,
        f"""
        SELECT MAX(date_modified) AS newest
        FROM missing_regulars
        WHERE season = ? AND week = ?{team_sql}
          AND date_modified IS NOT NULL
          AND TRIM(date_modified) != ''
        """,
        tuple(params),
    )
    if miss and miss[0].get("newest"):
        return parse_dt(miss[0]["newest"])
    return None


def injury_freshness(conn, game: dict | None = None, season: int | None = None, week: int | None = None) -> dict:
    now = datetime.now(timezone.utc)
    slate = None
    if game:
        season = int(game["season"])
        week = int(game["week"])
        teams = [game.get("away_team"), game.get("home_team")]
        teams = [team for team in teams if team]
    else:
        if season is None or week is None:
            current = resolve_slate(conn)
            if current:
                season = int(current["season"])
                week = int(current["week"])
        teams = None
    newest = _newest_for(conn, season, week, teams) if season is not None and week is not None else None
    ingested = _meta_stamp(conn, "injuries_ingested_at") or _meta_stamp(conn, "ingested_at")
    hours = _hours_ago(newest, now)
    ingest_hours = _hours_ago(ingested, now)
    if hours is None:
        hours = ingest_hours
    status = _status(hours)
    late = _late_window(game, now)
    stamp = newest or ingested
    if newest is None and ingested is not None:
        label = _label(status, ingested, hours).replace("report", "ingest", 1)
    else:
        label = _label(status, stamp, hours)
    return {
        "ingested_at": ingested.isoformat() if ingested else None,
        "newest_modified": newest.isoformat() if newest else None,
        "hours_old": round(hours, 1) if hours is not None else None,
        "ingest_hours_old": round(ingest_hours, 1) if ingest_hours is not None else None,
        "status": status,
        "late_window": late,
        "label": label,
        "note": None if status == "fresh" and not late else NOTE,
    }
