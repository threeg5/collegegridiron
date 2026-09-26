from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from collegegridiron.config import DB_PATH, fanduel_props_enabled
from collegegridiron.db import connect
from collegegridiron.freshness import injury_freshness
from collegegridiron.live_pull import kick_live_pull, live_status
from collegegridiron.markets import (
    delete_market,
    game_prop_board,
    import_current_slate,
    player_card,
    snapshot_meta,
    upsert_market,
)
from collegegridiron.session import OptionalUser, User
from collegegridiron.slate import get_matchup, get_slate
from collegegridiron.tenpage import build_tenpage
from collegegridiron.tpe_board import build_tpe_board
from collegegridiron.venues import pacific_teams

router = APIRouter()

STATS = {
    "passing_yards": "Pass yds",
    "passing_tds": "Pass TD",
    "completions": "Completions",
    "attempts": "Attempts",
    "carries": "Carries",
    "rushing_yards": "Rush yds",
    "rushing_tds": "Rush TD",
    "targets": "Targets",
    "receptions": "Receptions",
    "receiving_yards": "Rec yds",
    "receiving_tds": "Rec TD",
    "rushing_receiving_yards": "Rush + rec yds",
    "interceptions": "INTs thrown",
    "fantasy_points": "Fantasy pts",
}

DEFAULT_LINES = {
    "QB": ("passing_yards", 250.5),
    "RB": ("rushing_yards", 80.5),
    "WR": ("receiving_yards", 69.5),
    "TE": ("receiving_yards", 44.5),
}


def rows(conn, sql: str, params: tuple = ()) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def one(conn, sql: str, params: tuple = ()) -> dict | None:
    found = conn.execute(sql, params).fetchone()
    return dict(found) if found else None


@router.get("/health")
def health():
    return {"ok": True, "db": DB_PATH.exists()}


@router.get("/api/meta")
def meta():
    if not DB_PATH.exists():
        return {
            "ingested": False,
            "stats": STATS,
            "fanduel": fanduel_props_enabled(),
            "fanduel_snapshot_at": None,
            "fanduel_snapshot_games": 0,
            "fanduel_snapshot_markets": 0,
            "injury_freshness": None,
            "live_pull": None,
            "owner_controls": True,
        }
    conn = connect()
    try:
        kv = {r["key"]: r["value"] for r in rows(conn, "SELECT key, value FROM meta")}
        counts = one(
            conn,
            """
            SELECT
              (SELECT COUNT(*) FROM games) AS games,
              (SELECT COUNT(*) FROM players) AS players,
              (SELECT COUNT(*) FROM player_weeks) AS player_weeks,
              (SELECT COUNT(*) FROM team_weeks) AS team_weeks,
              (SELECT COUNT(*) FROM missing_regulars) AS missing_regulars
            """,
        )
        snap = snapshot_meta()
        kick_live_pull(reason="meta")
        ingested = str(kv.get("ingest_complete") or "") == "1" or int((counts or {}).get("games") or 0) > 0
        return {
            "ingested": ingested,
            "stats": STATS,
            "fanduel": fanduel_props_enabled(),
            "fanduel_snapshot_at": snap.get("updated_at"),
            "fanduel_snapshot_games": snap.get("games"),
            "fanduel_snapshot_markets": snap.get("markets"),
            "injury_freshness": injury_freshness(conn),
            "live_pull": live_status(conn),
            "owner_controls": True,
            **kv,
            **(counts or {}),
        }
    finally:
        conn.close()


@router.get("/api/players/search")
def search_players(q: str = Query(..., min_length=2), limit: int = 15):
    conn = connect()
    try:
        return rows(
            conn,
            """
            SELECT player_id, player_name, position, latest_team
            FROM players
            WHERE player_name LIKE ?
            ORDER BY
              CASE WHEN player_name LIKE ? THEN 0 ELSE 1 END,
              player_name
            LIMIT ?
            """,
            (f"%{q}%", f"{q}%", limit),
        )
    finally:
        conn.close()


@router.get("/api/players/{player_id}")
def player_summary(player_id: str):
    conn = connect()
    try:
        player = one(
            conn,
            "SELECT player_id, player_name, position, latest_team FROM players WHERE player_id = ?",
            (player_id,),
        )
        if not player:
            raise HTTPException(404, "Player not found")
        pos = (player["position"] or "").upper()
        default_stat, default_line = DEFAULT_LINES.get(pos, ("receiving_yards", 49.5))
        if pos.startswith("QB"):
            default_stat, default_line = DEFAULT_LINES["QB"]
        elif pos.startswith("RB") or pos in {"FB"}:
            default_stat, default_line = DEFAULT_LINES["RB"]
        elif pos.startswith("TE"):
            default_stat, default_line = DEFAULT_LINES["TE"]
        elif pos.startswith("WR"):
            default_stat, default_line = DEFAULT_LINES["WR"]
        return {**player, "default_stat": default_stat, "default_line": default_line, "stats": STATS}
    finally:
        conn.close()


class MarketBody(BaseModel):
    stat: str
    line: float
    over_odds: int | None = Field(default=None, alias="overOdds")
    under_odds: int | None = Field(default=None, alias="underOdds")
    game_id: str | None = Field(default=None, alias="gameId")

    model_config = {"populate_by_name": True}


@router.get("/api/players/{player_id}/card")
def player_profile_card(player_id: str, user: OptionalUser):
    conn = connect()
    try:
        player = one(
            conn,
            "SELECT player_id, player_name, position, latest_team FROM players WHERE player_id = ?",
            (player_id,),
        )
        if not player:
            raise HTTPException(404, "Player not found")
        return player_card(conn, player, STATS, first_look=bool(user))
    finally:
        conn.close()


@router.post("/api/players/{player_id}/markets")
def save_player_market(player_id: str, body: MarketBody, user: User):
    if body.stat not in STATS:
        raise HTTPException(400, f"Unknown stat. Choose from: {', '.join(STATS)}")
    conn = connect()
    try:
        player = one(conn, "SELECT player_id FROM players WHERE player_id = ?", (player_id,))
        if not player:
            raise HTTPException(404, "Player not found")
    finally:
        conn.close()
    return upsert_market(
        player_id,
        body.game_id,
        body.stat,
        body.line,
        over_odds=body.over_odds,
        under_odds=body.under_odds,
        source="manual",
    )


@router.delete("/api/markets/{market_id}")
def remove_player_market(market_id: str, user: User):
    if not delete_market(market_id):
        raise HTTPException(404, "Market not found.")
    return {"ok": True}


@router.post("/api/odds/refresh")
def refresh_odds(user: User):
    if user.get("tier") != "owner":
        raise HTTPException(403, "Owner only.")
    conn = connect()
    try:
        return import_current_slate(conn)
    finally:
        conn.close()


@router.post("/api/ingest")
def ingest_results(user: User, season: int | None = None):
    if user.get("tier") != "owner":
        raise HTTPException(403, "Owner only.")
    years = [season] if season else None
    try:
        from collegegridiron.ingest import refresh_results

        return refresh_results(years)
    except Exception as exc:
        raise HTTPException(500, f"Ingest failed: {exc}") from exc


def _streak_clause(column: str, direction: str | None, params: list) -> str:
    if direction == "win":
        params.append(2)
        return f"AND {column} >= ?"
    if direction == "loss":
        params.append(-2)
        return f"AND {column} <= ?"
    return ""


@router.get("/api/players/{player_id}/prop")
def player_prop(
    player_id: str,
    stat: str = "rushing_yards",
    line: float = 70.5,
    home: int | None = None,
    min_rest: int | None = None,
    max_rest: int | None = None,
    max_wind: float | None = None,
    roof: str | None = None,
    ml_streak: str | None = None,
    ats_streak: str | None = None,
    travel: str | None = None,
    practice: str | None = None,
    div_game: int | None = None,
    primetime: int | None = None,
    short_week: int | None = None,
    off_bye: int | None = None,
    surface: str | None = None,
    altitude: int | None = None,
    favored: int | None = None,
    west_coast_early: int | None = None,
    consec_road: int | None = None,
    season_from: int | None = None,
    season_to: int | None = None,
    season_type: str = "REG",
):
    if stat not in STATS:
        raise HTTPException(400, f"Unknown stat. Choose from: {', '.join(STATS)}")

    conn = connect()
    try:
        player = one(
            conn,
            "SELECT player_id, player_name, position, latest_team FROM players WHERE player_id = ?",
            (player_id,),
        )
        if not player:
            raise HTTPException(404, "Player not found")

        params: list = [player_id]
        where = ["pw.player_id = ?", f"pw.{stat} IS NOT NULL"]

        if season_type:
            where.append("pw.season_type = ?")
            params.append(season_type)
        if home is not None:
            where.append("pw.is_home = ?")
            params.append(home)
        if season_from is not None:
            where.append("pw.season >= ?")
            params.append(season_from)
        if season_to is not None:
            where.append("pw.season <= ?")
            params.append(season_to)
        if min_rest is not None:
            where.append(
                "((pw.is_home = 1 AND g.home_rest >= ?) OR (pw.is_home = 0 AND g.away_rest >= ?))"
            )
            params.extend([min_rest, min_rest])
        if max_rest is not None:
            where.append(
                "((pw.is_home = 1 AND g.home_rest <= ?) OR (pw.is_home = 0 AND g.away_rest <= ?))"
            )
            params.extend([max_rest, max_rest])
        if max_wind is not None:
            where.append("(g.wind IS NULL OR g.wind <= ?)")
            params.append(max_wind)
        if roof == "outdoors":
            where.append("g.roof IN ('outdoors', 'open')")
        elif roof == "indoor":
            where.append("g.roof IN ('dome', 'closed', 'retractable')")
        elif roof:
            where.append("g.roof = ?")
            params.append(roof)

        ml_col = "CASE WHEN pw.is_home = 1 THEN g.home_ml_streak ELSE g.away_ml_streak END"
        ats_col = "CASE WHEN pw.is_home = 1 THEN g.home_ats_streak ELSE g.away_ats_streak END"
        travel_col = "CASE WHEN pw.is_home = 1 THEN g.home_travel ELSE g.away_travel END"
        miles_col = "CASE WHEN pw.is_home = 1 THEN g.home_travel_miles ELSE g.away_travel_miles END"
        tz_col = "CASE WHEN pw.is_home = 1 THEN g.home_tz_change ELSE g.away_tz_change END"
        road_col = "CASE WHEN pw.is_home = 1 THEN g.home_road_streak ELSE g.away_road_streak END"
        rest_col = "CASE WHEN pw.is_home = 1 THEN g.home_rest ELSE g.away_rest END"
        favored_col = """
            CASE
              WHEN pw.is_home = 1 AND g.spread_line < 0 THEN 1
              WHEN pw.is_home = 0 AND g.spread_line > 0 THEN 1
              WHEN g.spread_line IS NULL THEN NULL
              ELSE 0
            END
        """
        where.append(_streak_clause(ml_col, ml_streak, params).lstrip("AND ").strip() or "1=1")
        where.append(_streak_clause(ats_col, ats_streak, params).lstrip("AND ").strip() or "1=1")

        if travel:
            where.append(f"{travel_col} = ?")
            params.append(travel)
        if practice == "dnp":
            where.append("pw.practice_status = 'dnp'")
        elif practice == "limited":
            where.append("pw.practice_status = 'limited'")
        elif practice == "full":
            where.append("pw.practice_status IN ('full', 'none')")
        elif practice == "listed":
            where.append("pw.practice_status IN ('dnp', 'limited')")
        if div_game is not None:
            where.append("g.div_game = ?")
            params.append(div_game)
        if primetime is not None:
            where.append("g.is_primetime = ?")
            params.append(primetime)
        if short_week:
            where.append(f"{rest_col} <= 5")
        if off_bye:
            where.append(f"{rest_col} >= 10")
        if surface:
            where.append("g.surface_group = ?")
            params.append(surface)
        if altitude is not None:
            where.append("g.is_altitude = ?")
            params.append(altitude)
        if favored is not None:
            where.append(f"{favored_col} = ?")
            params.append(favored)
        if west_coast_early:
            west = sorted(pacific_teams()) or ["—"]
            placeholders = ",".join("?" for _ in west)
            where.append(f"g.is_early_window = 1 AND pw.team IN ({placeholders})")
            params.extend(west)
        if consec_road:
            where.append(f"{road_col} >= ?")
            params.append(consec_road)

        where = [clause for clause in where if clause != "1=1"]

        sql = f"""
            SELECT
              pw.season, pw.week, pw.season_type,
              pw.game_id, pw.team, pw.opponent, pw.is_home, pw.position,
              pw.{stat} AS stat_value,
              pw.practice_status,
              g.gameday, g.weekday, g.gametime, g.roof, g.temp, g.wind,
              g.surface, g.surface_group, g.stadium, g.div_game,
              g.is_overseas, g.is_primetime, g.is_early_window, g.is_altitude,
              {rest_col} AS rest_days,
              {ml_col} AS ml_streak,
              {ats_col} AS ats_streak,
              {travel_col} AS travel,
              {miles_col} AS travel_miles,
              {tz_col} AS tz_change,
              {road_col} AS road_streak,
              {favored_col} AS favored,
              g.spread_line, g.total_line, g.home_score, g.away_score,
              g.home_team, g.away_team
            FROM player_weeks pw
            LEFT JOIN games g ON g.game_id = pw.game_id
            WHERE {' AND '.join(where)}
            ORDER BY pw.season DESC, pw.week DESC
        """

        games = rows(conn, sql, tuple(params))
        for game in games:
            value = game.get("stat_value")
            game["hit"] = value is not None and float(value) > line

        missing_map: dict[tuple, list[dict]] = {}
        if games:
            keys = {(g["season"], g["week"], g["team"]) for g in games} | {
                (g["season"], g["week"], g["opponent"]) for g in games
            }
            placeholders = ",".join("(?,?,?)" for _ in keys)
            flat: list = []
            for season, week, team in keys:
                flat.extend([season, week, team])
            missing_rows = rows(
                conn,
                f"""
                SELECT season, week, team, player_name, position, side,
                       snap_pct_recent, status, injury
                FROM missing_regulars
                WHERE (season, week, team) IN ({placeholders})
                ORDER BY snap_pct_recent DESC
                """,
                tuple(flat),
            )
            for row in missing_rows:
                missing_map.setdefault((row["season"], row["week"], row["team"]), []).append(row)

        for game in games:
            game["missing_teammates"] = missing_map.get(
                (game["season"], game["week"], game["team"]), []
            )
            game["missing_opponents"] = missing_map.get(
                (game["season"], game["week"], game["opponent"]), []
            )

        hits = sum(1 for g in games if g["hit"])
        values = [float(g["stat_value"]) for g in games if g["stat_value"] is not None]
        values_sorted = sorted(values)
        median = values_sorted[len(values_sorted) // 2] if values_sorted else None
        return {
            "player": player,
            "stat": stat,
            "stat_label": STATS[stat],
            "line": line,
            "sample_size": len(games),
            "hits": hits,
            "hit_rate": round(hits / len(games), 3) if games else None,
            "mean": round(sum(values) / len(values), 2) if values else None,
            "median": median,
            "games": games,
        }
    finally:
        conn.close()


@router.get("/api/slate")
def slate(
    season: int | None = None,
    week: int | None = None,
    season_type: str | None = None,
):
    if not DB_PATH.exists():
        return {"slate": None, "weeks": [], "games": []}
    conn = connect()
    try:
        kick_live_pull(reason="slate")
        return get_slate(conn, season, week, season_type)
    finally:
        conn.close()


@router.get("/api/tenpage")
def tenpage(
    season: int | None = None,
    week: int | None = None,
    season_type: str | None = None,
):
    if not DB_PATH.exists():
        return {
            "stake": 10,
            "slate": None,
            "weeks": [],
            "games": [],
            "tickets": 0,
            "pending": 0,
            "tpe_wins": 0,
            "book_wins": 0,
            "pushes": 0,
            "total": 0,
            "graded_total": 0,
            "method": "",
        }
    conn = connect()
    try:
        return build_tenpage(conn, STATS, season, week, season_type)
    finally:
        conn.close()


@router.get("/api/games/{game_id}/matchup")
def matchup(game_id: str, user: OptionalUser):
    conn = connect()
    try:
        found = get_matchup(conn, game_id)
        if not found:
            raise HTTPException(404, "Game not found")
        found["props"] = game_prop_board(conn, found["game"], STATS, first_look=bool(user))
        found["board"] = (
            build_tpe_board(conn, found["game"], found.get("expected"), STATS)
            if fanduel_props_enabled()
            else None
        )
        return found
    finally:
        conn.close()
