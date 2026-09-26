"""Keep ESPN scores and opened FanDuel snapshots current without a manual click.

Thursday through Sunday use a short cooldown. Unopened games are never purchased.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone

from collegegridiron.config import live_odds_enabled, live_pull_enabled
from collegegridiron.db import connect
from collegegridiron.freshness import _hours_ago, _late_window, _meta_stamp

LATE_MINUTES = 90
QUIET_MINUTES = 360

_lock = threading.Lock()
_busy = False


def _due(stamp, minutes: int) -> bool:
    hours = _hours_ago(stamp)
    if hours is None:
        return True
    return hours * 60 >= minutes


def _cooldown_minutes(now: datetime) -> int:
    return LATE_MINUTES if _late_window(None, now) else QUIET_MINUTES


def live_status(conn=None) -> dict:
    own = conn is None
    conn = conn or connect()
    try:
        now = datetime.now(timezone.utc)
        injury_at = _meta_stamp(conn, "live_injury_pulled_at") or _meta_stamp(conn, "injuries_ingested_at")
        odds_at = _meta_stamp(conn, "live_odds_pulled_at")
        late = _late_window(None, now)
        wait = _cooldown_minutes(now)
        return {
            "enabled": live_pull_enabled(),
            "odds_enabled": live_odds_enabled(),
            "late_window": late,
            "cooldown_minutes": wait,
            "injury_pulled_at": injury_at.isoformat() if injury_at else None,
            "odds_pulled_at": odds_at.isoformat() if odds_at else None,
            "injury_due": live_pull_enabled() and _due(injury_at, wait),
            "odds_due": live_odds_enabled() and _due(odds_at, wait),
            "busy": _busy,
        }
    finally:
        if own:
            conn.close()


def run_live_pull(*, force: bool = False, reason: str = "auto") -> dict:
    """Refresh injuries, then opened FanDuel games if those pulls are due."""
    global _busy
    if not live_pull_enabled() and not live_odds_enabled():
        return {"ok": True, "skipped": "off", "reason": reason}
    if not _lock.acquire(blocking=False):
        return {"ok": True, "skipped": "busy", "reason": reason}
    _busy = True
    result: dict = {"ok": True, "reason": reason, "force": force}
    try:
        now = datetime.now(timezone.utc)
        wait = _cooldown_minutes(now)
        conn = connect()
        try:
            injury_at = _meta_stamp(conn, "live_injury_pulled_at") or _meta_stamp(conn, "injuries_ingested_at")
            odds_at = _meta_stamp(conn, "live_odds_pulled_at")
            if live_pull_enabled() and (force or _due(injury_at, wait)):
                from collegegridiron.ingest import refresh_upcoming_schedules

                schedule = refresh_upcoming_schedules()
                stamp = datetime.now(timezone.utc).isoformat()
                conn.execute(
                    "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
                    ("live_injury_pulled_at", stamp),
                )
                conn.commit()
                result["schedule"] = schedule
                result["schedule"]["pulled_at"] = stamp
            else:
                result["schedule"] = {"skipped": "fresh"}
            if live_odds_enabled() and (force or _due(odds_at, wait)):
                from collegegridiron.markets import import_current_slate

                odds = import_current_slate(conn, force=True)
                stamp = datetime.now(timezone.utc).isoformat()
                conn.execute(
                    "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
                    ("live_odds_pulled_at", stamp),
                )
                conn.commit()
                result["odds"] = {k: odds.get(k) for k in ("ok", "fetched", "skipped", "error", "snapshot_at")}
                result["odds"]["pulled_at"] = stamp
            else:
                result["odds"] = {"skipped": "off" if not live_odds_enabled() else "fresh"}
        finally:
            conn.close()
        return result
    except Exception as exc:
        result["ok"] = False
        result["error"] = str(exc)
        return result
    finally:
        _busy = False
        _lock.release()


def kick_live_pull(*, force: bool = False, reason: str = "auto") -> None:
    if _busy:
        return
    threading.Thread(
        target=run_live_pull,
        kwargs={"force": force, "reason": reason},
        daemon=True,
        name="tpe-live-pull",
    ).start()
