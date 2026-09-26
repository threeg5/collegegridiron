from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone

from collegegridiron.config import ODDS_API_KEY, fanduel_props_enabled, odds_first_look_enabled
from collegegridiron.db import connect as connect_accounts
from collegegridiron.slate import decorate_game, resolve_slate, rows, slate_games, week_label
from collegegridiron.snapshots import first_open
from collegegridiron.venues import TEAM_NAMES, TEAM_SCHOOLS

PLAYER_MARKET_COLS = """
  id, player_id, game_id, book, stat, line, over_odds, under_odds,
  open_line, open_over_odds, open_under_odds, opened_at, source, created_at, updated_at
"""
GAME_MARKET_COLS = """
  id, game_id, book, market, home_line, away_line, home_odds, away_odds,
  over_odds, under_odds, open_home_line, open_away_line, open_home_odds, open_away_odds,
  open_over_odds, open_under_odds, opened_at, source, created_at, updated_at
"""
PLAYER_OPEN_PAIRS = [("line", "open_line"), ("over_odds", "open_over_odds"), ("under_odds", "open_under_odds")]
GAME_OPEN_PAIRS = [
    ("home_line", "open_home_line"),
    ("away_line", "open_away_line"),
    ("home_odds", "open_home_odds"),
    ("away_odds", "open_away_odds"),
    ("over_odds", "open_over_odds"),
    ("under_odds", "open_under_odds"),
]

BOOK = "FanDuel"
ODDS_SPORT = "americanfootball_ncaaf"
ODDS_HOST = "https://api.the-odds-api.com"
EVENTS_TTL = 3600
MARKET_CHUNK = 10
POS_RANK = {"QB": 0, "RB": 1, "WR": 2, "TE": 3}

# Core FanDuel card only. Odds API charges 1 credit per region per market returned.
ODDS_STAT = {
    "player_pass_yds": "passing_yards",
    "player_pass_tds": "passing_tds",
    "player_rush_yds": "rushing_yards",
    "player_rush_attempts": "carries",
    "player_rush_tds": "rushing_tds",
    "player_receptions": "receptions",
    "player_reception_yds": "receiving_yards",
    "player_reception_tds": "receiving_tds",
}

SUGGESTED = {
    "QB": (
        "passing_yards",
        "passing_tds",
        "completions",
        "attempts",
        "interceptions",
        "rushing_yards",
    ),
    "RB": (
        "rushing_yards",
        "carries",
        "receptions",
        "receiving_yards",
        "rushing_tds",
        "rushing_receiving_yards",
    ),
    "WR": (
        "receiving_yards",
        "receptions",
        "targets",
        "receiving_tds",
        "rushing_receiving_yards",
    ),
    "TE": (
        "receiving_yards",
        "receptions",
        "targets",
        "receiving_tds",
    ),
}

_events_cache: tuple[float, list] | None = None
_last_quota: dict[str, str | None] = {"remaining": None, "used": None}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def american_implied(odds: int | None) -> float | None:
    if odds is None:
        return None
    try:
        price = int(odds)
    except (TypeError, ValueError):
        return None
    if price >= 100:
        return round(100.0 / (price + 100.0), 3)
    if price <= -100:
        return round(abs(price) / (abs(price) + 100.0), 3)
    return None


def _norm_name(value: str | None) -> str:
    text = re.sub(r"\b(jr|sr|iii|ii|iv)\b", "", (value or "").lower())
    return re.sub(r"[^a-z0-9]", "", text)


def _roof_group(roof: str | None) -> str | None:
    if roof in {"outdoors", "open"}:
        return "outdoors"
    if roof in {"dome", "closed", "retractable"}:
        return "indoor"
    return None


def player_slate_game(conn, team: str | None) -> tuple[dict | None, dict | None]:
    slate = resolve_slate(conn)
    if not slate:
        return None, None
    games = slate_games(conn, slate["season"], slate["week"], slate["season_type"] or "REG")
    if not team:
        return slate, None
    for game in games:
        if game["home_team"] == team or game["away_team"] == team:
            return slate, game
    return slate, None


def situation_from_game(game: dict, team: str) -> dict:
    is_home = game["home_team"] == team
    return {
        "is_home": int(is_home),
        "opponent": game["away_team"] if is_home else game["home_team"],
        "opponent_name": (game["away_name"] if is_home else game["home_name"]),
        "rest_days": game["home_rest"] if is_home else game["away_rest"],
        "travel": game["home_travel"] if is_home else game["away_travel"],
        "travel_miles": game["home_travel_miles"] if is_home else game["away_travel_miles"],
        "roof": game.get("roof"),
        "roof_group": _roof_group(game.get("roof")),
        "wind": game.get("wind"),
        "temp": game.get("temp"),
        "primetime": game.get("is_primetime"),
        "surface_group": game.get("surface_group"),
        "stadium": game.get("stadium"),
    }


def decorate_market(row: dict, stats: dict[str, str]) -> dict:
    over_odds = row.get("over_odds")
    under_odds = row.get("under_odds")
    open_over = row.get("open_over_odds")
    open_under = row.get("open_under_odds")
    return {
        "id": row.get("id"),
        "player_id": row.get("player_id"),
        "game_id": row.get("game_id"),
        "book": row.get("book") or BOOK,
        "stat": row["stat"],
        "stat_label": stats.get(row["stat"], row["stat"]),
        "line": row["line"],
        "over_odds": over_odds,
        "under_odds": under_odds,
        "over_implied": american_implied(over_odds),
        "under_implied": american_implied(under_odds),
        "open_line": row.get("open_line"),
        "open_over_odds": open_over,
        "open_under_odds": open_under,
        "open_over_implied": american_implied(open_over),
        "open_under_implied": american_implied(open_under),
        "opened_at": row.get("opened_at"),
        "source": row.get("source") or "manual",
        "updated_at": row.get("updated_at"),
    }


def list_markets(player_id: str, game_id: str | None) -> list[dict]:
    conn = connect_accounts()
    try:
        found = conn.execute(
            f"""
            SELECT {PLAYER_MARKET_COLS}
            FROM player_markets
            WHERE player_id = ? AND COALESCE(game_id, '') = COALESCE(?, '')
            ORDER BY stat
            """,
            (player_id, game_id),
        ).fetchall()
        return [dict(row) for row in found]
    finally:
        conn.close()


def upsert_market(
    player_id: str,
    game_id: str | None,
    stat: str,
    line: float,
    over_odds: int | None = None,
    under_odds: int | None = None,
    source: str = "manual",
    book: str = BOOK,
) -> dict:
    conn = connect_accounts()
    try:
        game_key = game_id or ""
        existing = conn.execute(
            f"""
            SELECT {PLAYER_MARKET_COLS}
            FROM player_markets
            WHERE player_id = ? AND COALESCE(game_id, '') = ?
              AND book = ? AND stat = ?
            """,
            (player_id, game_key, book, stat),
        ).fetchone()
        now = now_iso()
        prior = dict(existing) if existing else None
        incoming = {"line": line, "over_odds": over_odds, "under_odds": under_odds}
        opened = first_open(prior, incoming, PLAYER_OPEN_PAIRS, now)
        market_id = existing["id"] if existing else uuid.uuid4().hex
        created = existing["created_at"] if existing else now
        conn.execute(
            """
            INSERT INTO player_markets (
              id, player_id, game_id, book, stat, line, over_odds, under_odds,
              open_line, open_over_odds, open_under_odds, opened_at, source,
              created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(player_id, game_id, book, stat) DO UPDATE SET
              line = excluded.line,
              over_odds = excluded.over_odds,
              under_odds = excluded.under_odds,
              open_line = COALESCE(player_markets.open_line, excluded.open_line),
              open_over_odds = COALESCE(player_markets.open_over_odds, excluded.open_over_odds),
              open_under_odds = COALESCE(player_markets.open_under_odds, excluded.open_under_odds),
              opened_at = COALESCE(player_markets.opened_at, excluded.opened_at),
              source = excluded.source,
              updated_at = excluded.updated_at
            """,
            (
                market_id,
                player_id,
                game_key,
                book,
                stat,
                line,
                over_odds,
                under_odds,
                opened.get("open_line"),
                opened.get("open_over_odds"),
                opened.get("open_under_odds"),
                opened.get("opened_at"),
                source,
                created,
                now,
            ),
        )
        conn.commit()
        row = conn.execute(
            f"SELECT {PLAYER_MARKET_COLS} FROM player_markets WHERE id = ?",
            (market_id,),
        ).fetchone()
        return dict(row)
    finally:
        conn.close()


def delete_market(market_id: str) -> bool:
    conn = connect_accounts()
    try:
        cur = conn.execute("DELETE FROM player_markets WHERE id = ?", (market_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def list_game_markets(game_id: str) -> list[dict]:
    conn = connect_accounts()
    try:
        found = conn.execute(
            f"""
            SELECT {PLAYER_MARKET_COLS}
            FROM player_markets
            WHERE game_id = ?
            ORDER BY stat
            """,
            (game_id,),
        ).fetchall()
        return [dict(row) for row in found]
    finally:
        conn.close()


def _game_import_fresh(game_id: str) -> bool:
    conn = connect_accounts()
    try:
        row = conn.execute(
            """
            SELECT COUNT(*) AS n
            FROM player_markets
            WHERE game_id = ? AND source = 'odds_api'
            """,
            (game_id,),
        ).fetchone()
        return bool(row and (row["n"] or 0) > 0)
    finally:
        conn.close()


def _game_lines_fresh(game_id: str) -> bool:
    conn = connect_accounts()
    try:
        row = conn.execute(
            """
            SELECT COUNT(*) AS n
            FROM game_markets
            WHERE game_id = ? AND source = 'odds_api'
            """,
            (game_id,),
        ).fetchone()
        return bool(row and (row["n"] or 0) > 0)
    finally:
        conn.close()


def list_game_lines(game_id: str) -> list[dict]:
    conn = connect_accounts()
    try:
        found = conn.execute(
            f"""
            SELECT {GAME_MARKET_COLS}
            FROM game_markets
            WHERE game_id = ?
            ORDER BY market
            """,
            (game_id,),
        ).fetchall()
        return [dict(row) for row in found]
    finally:
        conn.close()


def _upsert_game_lines(game_id: str, items: list[dict]) -> None:
    if not items:
        return
    conn = connect_accounts()
    try:
        now = now_iso()
        for item in items:
            existing = conn.execute(
                f"""
                SELECT {GAME_MARKET_COLS}
                FROM game_markets
                WHERE game_id = ? AND book = ? AND market = ?
                """,
                (game_id, item.get("book") or BOOK, item["market"]),
            ).fetchone()
            prior = dict(existing) if existing else None
            opened = first_open(prior, item, GAME_OPEN_PAIRS, now)
            conn.execute(
                """
                INSERT INTO game_markets (
                  id, game_id, book, market, home_line, away_line, home_odds, away_odds,
                  over_odds, under_odds, open_home_line, open_away_line, open_home_odds,
                  open_away_odds, open_over_odds, open_under_odds, opened_at, source,
                  created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(game_id, book, market) DO UPDATE SET
                  home_line = excluded.home_line,
                  away_line = excluded.away_line,
                  home_odds = excluded.home_odds,
                  away_odds = excluded.away_odds,
                  over_odds = excluded.over_odds,
                  under_odds = excluded.under_odds,
                  open_home_line = COALESCE(game_markets.open_home_line, excluded.open_home_line),
                  open_away_line = COALESCE(game_markets.open_away_line, excluded.open_away_line),
                  open_home_odds = COALESCE(game_markets.open_home_odds, excluded.open_home_odds),
                  open_away_odds = COALESCE(game_markets.open_away_odds, excluded.open_away_odds),
                  open_over_odds = COALESCE(game_markets.open_over_odds, excluded.open_over_odds),
                  open_under_odds = COALESCE(game_markets.open_under_odds, excluded.open_under_odds),
                  opened_at = COALESCE(game_markets.opened_at, excluded.opened_at),
                  source = excluded.source,
                  updated_at = excluded.updated_at
                """,
                (
                    existing["id"] if existing else uuid.uuid4().hex,
                    game_id,
                    item.get("book") or BOOK,
                    item["market"],
                    item.get("home_line"),
                    item.get("away_line"),
                    item.get("home_odds"),
                    item.get("away_odds"),
                    item.get("over_odds"),
                    item.get("under_odds"),
                    opened.get("open_home_line"),
                    opened.get("open_away_line"),
                    opened.get("open_home_odds"),
                    opened.get("open_away_odds"),
                    opened.get("open_over_odds"),
                    opened.get("open_under_odds"),
                    opened.get("opened_at"),
                    item.get("source") or "odds_api",
                    existing["created_at"] if existing else now,
                    now,
                ),
            )
        conn.commit()
    finally:
        conn.close()


def snapshot_meta() -> dict:
    conn = connect_accounts()
    try:
        row = conn.execute(
            """
            SELECT COUNT(*) AS n, COUNT(DISTINCT game_id) AS games, MAX(updated_at) AS updated_at
            FROM player_markets
            WHERE source = 'odds_api'
            """
        ).fetchone()
        return {
            "markets": int(row["n"] or 0) if row else 0,
            "games": int(row["games"] or 0) if row else 0,
            "updated_at": row["updated_at"] if row else None,
            "first_look": odds_first_look_enabled(),
        }
    finally:
        conn.close()


def _latest_updated(stored: list[dict]) -> str | None:
    stamps = [row.get("updated_at") for row in stored if row.get("updated_at")]
    return max(stamps) if stamps else None


def _upsert_many(items: list[dict]) -> None:
    if not items:
        return
    conn = connect_accounts()
    try:
        now = now_iso()
        for item in items:
            game_key = item.get("game_id") or ""
            existing = conn.execute(
                f"""
                SELECT {PLAYER_MARKET_COLS}
                FROM player_markets
                WHERE player_id = ? AND COALESCE(game_id, '') = ?
                  AND book = ? AND stat = ?
                """,
                (item["player_id"], game_key, item.get("book") or BOOK, item["stat"]),
            ).fetchone()
            prior = dict(existing) if existing else None
            opened = first_open(prior, item, PLAYER_OPEN_PAIRS, now)
            conn.execute(
                """
                INSERT INTO player_markets (
                  id, player_id, game_id, book, stat, line, over_odds, under_odds,
                  open_line, open_over_odds, open_under_odds, opened_at, source,
                  created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(player_id, game_id, book, stat) DO UPDATE SET
                  line = excluded.line,
                  over_odds = excluded.over_odds,
                  under_odds = excluded.under_odds,
                  open_line = COALESCE(player_markets.open_line, excluded.open_line),
                  open_over_odds = COALESCE(player_markets.open_over_odds, excluded.open_over_odds),
                  open_under_odds = COALESCE(player_markets.open_under_odds, excluded.open_under_odds),
                  opened_at = COALESCE(player_markets.opened_at, excluded.opened_at),
                  source = excluded.source,
                  updated_at = excluded.updated_at
                """,
                (
                    existing["id"] if existing else uuid.uuid4().hex,
                    item["player_id"],
                    game_key,
                    item.get("book") or BOOK,
                    item["stat"],
                    item["line"],
                    item.get("over_odds"),
                    item.get("under_odds"),
                    opened.get("open_line"),
                    opened.get("open_over_odds"),
                    opened.get("open_under_odds"),
                    opened.get("opened_at"),
                    item.get("source") or "odds_api",
                    existing["created_at"] if existing else now,
                    now,
                ),
            )
        conn.commit()
    finally:
        conn.close()


def _get_json(url: str) -> object:
    req = urllib.request.Request(url, headers={"User-Agent": "collegegridiron-desk"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            _last_quota["remaining"] = resp.headers.get("x-requests-remaining")
            _last_quota["used"] = resp.headers.get("x-requests-used")
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")[:240]
        _last_quota["remaining"] = exc.headers.get("x-requests-remaining") if exc.headers else None
        _last_quota["used"] = exc.headers.get("x-requests-used") if exc.headers else None
        raise RuntimeError(f"Odds API HTTP {exc.code}: {body}") from exc


def _odds_get(path: str, params: dict) -> object:
    if not ODDS_API_KEY:
        raise RuntimeError("ODDS_API_KEY is not set.")
    query = urllib.parse.urlencode({**params, "apiKey": ODDS_API_KEY})
    return _get_json(f"{ODDS_HOST}{path}?{query}")


def _odds_events() -> list[dict]:
    global _events_cache
    if not ODDS_API_KEY:
        return []
    if _events_cache and time.time() - _events_cache[0] < EVENTS_TTL:
        return _events_cache[1]
    try:
        payload = _odds_get(f"/v4/sports/{ODDS_SPORT}/events", {"dateFormat": "iso"})
    except (RuntimeError, TimeoutError, json.JSONDecodeError, ValueError):
        return _events_cache[1] if _events_cache else []
    events = payload if isinstance(payload, list) else []
    _events_cache = (time.time(), events)
    return events


def _norm_odds(value: str | None) -> str:
    return " ".join((value or "").lower().split())


def _team_from_odds_name(name: str | None) -> str | None:
    key = _norm_odds(name)
    if not key:
        return None
    exact: dict[str, str] = {}
    ambiguous: set[str] = set()

    def add(label: str | None, abbr: str) -> None:
        norm = _norm_odds(label)
        if not norm:
            return
        prev = exact.get(norm)
        if prev and prev != abbr:
            ambiguous.add(norm)
        else:
            exact[norm] = abbr

    for abbr, label in TEAM_NAMES.items():
        add(label, abbr)
    for abbr, school in TEAM_SCHOOLS.items():
        add(school, abbr)
    for norm in ambiguous:
        exact.pop(norm, None)
    return exact.get(key)


def _event_for_game(game: dict) -> dict | None:
    home = game.get("home_team")
    away = game.get("away_team")
    for event in _odds_events():
        if _team_from_odds_name(event.get("home_team")) == home and _team_from_odds_name(
            event.get("away_team")
        ) == away:
            return event
    return None


def _name_keys(value: str | None) -> list[str]:
    parts = [part for part in re.split(r"\s+", (value or "").strip()) if part]
    keys = []
    full = _norm_name(value)
    if full:
        keys.append(full)
    if len(parts) >= 2:
        first = _norm_name(parts[0])
        last = _norm_name(parts[-1])
        if first and last:
            keys.append(f"{first[:1]}{last}")
        if last:
            keys.append(last)
    return keys


def _roster_index(players: list[dict]) -> dict[str, list[dict]]:
    index: dict[str, list[dict]] = {}
    for player in players:
        for key in _name_keys(player.get("player_name")):
            index.setdefault(key, []).append(player)
    return index


def _match_player(name: str | None, index: dict[str, list[dict]]) -> dict | None:
    for key in _name_keys(name):
        hits = index.get(key) or []
        if len(hits) == 1:
            return hits[0]
        unique = {row["player_id"]: row for row in hits}
        if len(unique) == 1:
            return next(iter(unique.values()))
    return None


def _roster(conn, home: str, away: str) -> list[dict]:
    return rows(
        conn,
        """
        SELECT player_id, player_name, position, latest_team
        FROM players
        WHERE latest_team IN (?, ?)
        """,
        (home, away),
    )


def _fetch_event_odds(event_id: str) -> dict:
    merged: dict = {"bookmakers": []}
    fanduel = {"key": "fanduel", "markets": []}
    keys = list(ODDS_STAT)
    for i in range(0, len(keys), MARKET_CHUNK):
        chunk = keys[i : i + MARKET_CHUNK]
        payload = _odds_get(
            f"/v4/sports/{ODDS_SPORT}/events/{event_id}/odds",
            {
                "regions": "us",
                "oddsFormat": "american",
                "bookmakers": "fanduel",
                "markets": ",".join(chunk),
            },
        )
        if not isinstance(payload, dict):
            continue
        merged["id"] = payload.get("id") or event_id
        for book in payload.get("bookmakers") or []:
            if book.get("key") != "fanduel":
                continue
            fanduel["markets"].extend(book.get("markets") or [])
    if fanduel["markets"]:
        merged["bookmakers"] = [fanduel]
    return merged


def _fetch_featured_odds(event_id: str) -> dict:
    payload = _odds_get(
        f"/v4/sports/{ODDS_SPORT}/events/{event_id}/odds",
        {
            "regions": "us",
            "oddsFormat": "american",
            "bookmakers": "fanduel",
            "markets": "h2h,spreads,totals",
        },
    )
    return payload if isinstance(payload, dict) else {}


def _parse_game_lines(payload: dict, game: dict) -> list[dict]:
    home = game.get("home_team")
    away = game.get("away_team")
    collected: dict[str, dict] = {}
    for book in payload.get("bookmakers") or []:
        if book.get("key") != "fanduel":
            continue
        for market in book.get("markets") or []:
            key = market.get("key") or ""
            if key == "h2h":
                row = {
                    "market": "moneyline",
                    "book": BOOK,
                    "source": "odds_api",
                    "home_odds": None,
                    "away_odds": None,
                }
                for outcome in market.get("outcomes") or []:
                    team = _team_from_odds_name(outcome.get("name"))
                    price = outcome.get("price")
                    odds = int(price) if price is not None else None
                    if team == home:
                        row["home_odds"] = odds
                    elif team == away:
                        row["away_odds"] = odds
                if row["home_odds"] is not None or row["away_odds"] is not None:
                    collected["moneyline"] = row
            elif key == "spreads":
                row = {
                    "market": "spread",
                    "book": BOOK,
                    "source": "odds_api",
                    "home_line": None,
                    "away_line": None,
                    "home_odds": None,
                    "away_odds": None,
                }
                for outcome in market.get("outcomes") or []:
                    team = _team_from_odds_name(outcome.get("name"))
                    price = outcome.get("price")
                    odds = int(price) if price is not None else None
                    point = outcome.get("point")
                    line = float(point) if point is not None else None
                    if team == home:
                        row["home_odds"] = odds
                        row["home_line"] = line
                    elif team == away:
                        row["away_odds"] = odds
                        row["away_line"] = line
                if row["home_line"] is not None or row["away_line"] is not None:
                    collected["spread"] = row
            elif key == "totals":
                row = {
                    "market": "total",
                    "book": BOOK,
                    "source": "odds_api",
                    "home_line": None,
                    "over_odds": None,
                    "under_odds": None,
                }
                for outcome in market.get("outcomes") or []:
                    name = (outcome.get("name") or "").lower()
                    price = outcome.get("price")
                    odds = int(price) if price is not None else None
                    point = outcome.get("point")
                    if point is not None:
                        row["home_line"] = float(point)
                    if name == "over":
                        row["over_odds"] = odds
                    elif name == "under":
                        row["under_odds"] = odds
                if row["home_line"] is not None:
                    collected["total"] = row
    return list(collected.values())


def _import_status(
    *,
    ok: bool,
    feed: str,
    error: str | None = None,
    count: int = 0,
    fetched: bool = False,
) -> dict:
    return {
        "ok": ok,
        "feed": feed,
        "error": error,
        "count": count,
        "fetched": fetched,
        "quota_remaining": _last_quota.get("remaining"),
        "quota_used": _last_quota.get("used"),
    }


def import_game_markets(conn, game: dict, force: bool = False, first_look: bool = False) -> dict:
    game_id = game.get("game_id")
    if not fanduel_props_enabled():
        return _import_status(ok=False, feed="off")
    if not game_id:
        return _import_status(ok=False, feed="manual", error="No game on this slate.")
    if not ODDS_API_KEY:
        return _import_status(
            ok=False,
            feed="missing_key",
            error="Set ODDS_API_KEY in api/.env and restart the API to import FanDuel props.",
        )
    cached_props = _game_import_fresh(game_id)
    cached_lines = _game_lines_fresh(game_id)
    if cached_props and cached_lines and not force:
        return _import_status(
            ok=True,
            feed="odds_api",
            count=len(list_game_markets(game_id)),
        )
    if game.get("played"):
        return _import_status(ok=False, feed="snapshot")
    if not force and not (first_look and odds_first_look_enabled()):
        return _import_status(ok=False, feed="snapshot")
    event = _event_for_game(game)
    if not event:
        return _import_status(
            ok=False,
            feed="odds_api",
            error="No Odds API event matched this slate game yet.",
            fetched=False,
        )
    fetched = False
    error = None
    if force or not cached_lines:
        try:
            featured = _fetch_featured_odds(event["id"])
            fetched = True
            _upsert_game_lines(game_id, _parse_game_lines(featured, game))
        except (RuntimeError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
            error = str(exc)
            fetched = True
    if force or not cached_props:
        try:
            payload = _fetch_event_odds(event["id"])
            fetched = True
        except (RuntimeError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
            error = error or str(exc)
            payload = {}
            fetched = True
        index = _roster_index(_roster(conn, game["home_team"], game["away_team"]))
        collected: dict[tuple[str, str], dict] = {}
        for book in payload.get("bookmakers") or []:
            for market in book.get("markets") or []:
                stat = ODDS_STAT.get(market.get("key") or "")
                if not stat:
                    continue
                grouped: dict[str, dict] = {}
                for outcome in market.get("outcomes") or []:
                    player = _match_player(outcome.get("description"), index)
                    if not player or outcome.get("point") is None:
                        continue
                    row = grouped.setdefault(
                        player["player_id"],
                        {
                            "player_id": player["player_id"],
                            "game_id": game_id,
                            "stat": stat,
                            "line": float(outcome["point"]),
                            "over_odds": None,
                            "under_odds": None,
                            "source": "odds_api",
                            "book": BOOK,
                        },
                    )
                    name = (outcome.get("name") or "").lower()
                    price = outcome.get("price")
                    odds = int(price) if price is not None else None
                    if name == "over":
                        row["over_odds"] = odds
                        row["line"] = float(outcome["point"])
                    elif name == "under":
                        row["under_odds"] = odds
                        row["line"] = float(outcome["point"])
                for row in grouped.values():
                    collected[(row["player_id"], stat)] = row
        items = list(collected.values())
        _upsert_many(items)
        if not items and not _game_lines_fresh(game_id):
            return _import_status(
                ok=False,
                feed="odds_api",
                error=error or "FanDuel returned no matching player props for this game.",
                fetched=True,
            )
    count = len(list_game_markets(game_id))
    if count or _game_lines_fresh(game_id):
        return _import_status(ok=True, feed="odds_api", count=count, fetched=fetched)
    return _import_status(
        ok=False,
        feed="odds_api",
        error=error or "FanDuel returned no matching lines for this game.",
        fetched=fetched,
    )


def import_current_slate(conn, force: bool = False) -> dict:
    """Refresh FanDuel only for games someone already opened. Never buy the rest of the slate."""
    if not fanduel_props_enabled():
        return {"ok": False, "error": "FanDuel props are off.", **snapshot_meta()}
    if not ODDS_API_KEY:
        return {"ok": False, "error": "ODDS_API_KEY is not set.", **snapshot_meta()}
    slate = resolve_slate(conn)
    if not slate:
        return {"ok": False, "error": "No slate loaded yet.", **snapshot_meta()}
    games = [
        decorate_game(dict(game))
        for game in slate_games(conn, slate["season"], slate["week"], slate["season_type"] or "REG")
    ]
    results = []
    fetched = 0
    skipped = 0
    watched = [
        game
        for game in games
        if not game.get("played") and _game_import_fresh(game["game_id"])
    ]
    if watched:
        _odds_events()
    for game in games:
        label = f"{game.get('away_team')} @ {game.get('home_team')}"
        if game.get("played"):
            skipped += 1
            results.append({"game_id": game["game_id"], "label": label, "status": "played", "count": 0})
            continue
        if not _game_import_fresh(game["game_id"]):
            skipped += 1
            results.append(
                {
                    "game_id": game["game_id"],
                    "label": label,
                    "status": "unwatched",
                    "count": 0,
                }
            )
            continue
        imported = import_game_markets(conn, game, force=True)
        if imported.get("fetched"):
            fetched += 1
        results.append(
            {
                "game_id": game["game_id"],
                "label": label,
                "status": "ok" if imported.get("ok") else "error",
                "count": imported.get("count") or 0,
                "error": imported.get("error"),
            }
        )
    snap = snapshot_meta()
    return {
        "ok": True,
        "error": None if watched else "No opened games to refresh yet.",
        "force": force,
        "fetched": fetched,
        "skipped": skipped,
        "slate": {
            "season": slate["season"],
            "week": slate["week"],
            "season_type": slate.get("season_type"),
            "label": slate.get("label") or week_label(slate["season"], slate["week"], slate.get("season_type")),
        },
        "quota_remaining": _last_quota.get("remaining"),
        "quota_used": _last_quota.get("used"),
        "results": results,
        "snapshot_at": snap.get("updated_at"),
        "snapshot_games": snap.get("games"),
        "snapshot_markets": snap.get("markets"),
        "first_look": snap.get("first_look"),
    }


def _group_props(conn, game: dict, stats: dict[str, str], stored: list[dict]) -> list[dict]:
    ids = sorted({row["player_id"] for row in stored})
    by_id: dict[str, dict] = {}
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
            by_id[row["player_id"]] = row
    grouped: dict[str, dict] = {}
    for row in stored:
        player = by_id.get(row["player_id"]) or {
            "player_id": row["player_id"],
            "player_name": row["player_id"],
            "position": None,
            "latest_team": None,
        }
        bucket = grouped.setdefault(
            player["player_id"],
            {
                "player_id": player["player_id"],
                "player_name": player["player_name"],
                "position": player.get("position"),
                "latest_team": player.get("latest_team"),
                "markets": [],
            },
        )
        bucket["markets"].append(decorate_market(row, stats))
    ordered = list(grouped.values())
    home = game.get("home_team")
    ordered.sort(
        key=lambda item: (
            0 if item.get("latest_team") == game.get("away_team") else 1 if item.get("latest_team") == home else 2,
            POS_RANK.get(item.get("position") or "", 9),
            item.get("player_name") or "",
        )
    )
    return ordered


def game_prop_board(conn, game: dict, stats: dict[str, str], first_look: bool = False) -> dict:
    imported = import_game_markets(conn, game, first_look=first_look)
    stored = list_game_markets(game["game_id"])
    return {
        "book": BOOK,
        "feed": imported["feed"],
        "import_error": imported.get("error"),
        "has_odds_key": bool(ODDS_API_KEY),
        "quota_remaining": imported.get("quota_remaining"),
        "snapshot_at": _latest_updated(stored),
        "first_look": first_look and odds_first_look_enabled(),
        "players": _group_props(conn, game, stats, stored),
    }


def player_card(conn, player: dict, stats: dict[str, str], first_look: bool = False) -> dict:
    team = player.get("latest_team")
    slate, game = player_slate_game(conn, team)
    situation = situation_from_game(game, team) if game and team else None
    game_id = game.get("game_id") if game else None
    imported = {"feed": "manual", "error": None}
    if game:
        imported = import_game_markets(conn, game, first_look=first_look)
    stored = list_markets(player["player_id"], game_id)
    markets = [decorate_market(row, stats) for row in stored]
    position = player.get("position") or ""
    from collegegridiron.freshness import injury_freshness

    fresh = injury_freshness(conn, game) if game else None
    return {
        "player": player,
        "slate": (
            {
                "season": slate["season"],
                "week": slate["week"],
                "season_type": slate.get("season_type"),
                "label": slate.get("label") or week_label(slate["season"], slate["week"], slate.get("season_type")),
            }
            if slate
            else None
        ),
        "game": decorate_game(dict(game)) if game else None,
        "situation": situation,
        "markets": markets,
        "suggestions": list(SUGGESTED.get(position, SUGGESTED["WR"])),
        "feed": imported.get("feed") or "manual",
        "import_error": imported.get("error"),
        "has_odds_key": bool(ODDS_API_KEY),
        "quota_remaining": imported.get("quota_remaining"),
        "snapshot_at": _latest_updated(stored),
        "first_look": first_look and odds_first_look_enabled(),
        "injury_freshness": fresh,
    }
