from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from collegegridiron.config import DATA_DIR, DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT
);

CREATE TABLE IF NOT EXISTS team_venues (
  team TEXT PRIMARY KEY,
  team_id TEXT,
  school TEXT,
  mascot TEXT,
  conference TEXT,
  classification TEXT,
  lat REAL,
  lon REAL,
  tz_offset INTEGER,
  elevation REAL,
  venue_name TEXT,
  city TEXT,
  state TEXT,
  grass INTEGER,
  dome INTEGER
);

CREATE TABLE IF NOT EXISTS games (
  game_id TEXT PRIMARY KEY,
  season INTEGER NOT NULL,
  week INTEGER NOT NULL,
  season_type TEXT,
  gameday TEXT,
  weekday TEXT,
  home_team TEXT NOT NULL,
  away_team TEXT NOT NULL,
  home_score INTEGER,
  away_score INTEGER,
  result INTEGER,
  total INTEGER,
  roof TEXT,
  surface TEXT,
  temp REAL,
  wind REAL,
  home_rest INTEGER,
  away_rest INTEGER,
  spread_line REAL,
  total_line REAL,
  home_moneyline INTEGER,
  away_moneyline INTEGER,
  home_ml_streak INTEGER,
  away_ml_streak INTEGER,
  home_ats_streak INTEGER,
  away_ats_streak INTEGER,
  location TEXT,
  stadium TEXT,
  stadium_id TEXT,
  gametime TEXT,
  div_game INTEGER,
  is_overseas INTEGER,
  is_primetime INTEGER,
  is_early_window INTEGER,
  is_altitude INTEGER,
  surface_group TEXT,
  home_travel TEXT,
  away_travel TEXT,
  home_travel_miles REAL,
  away_travel_miles REAL,
  home_tz_change INTEGER,
  away_tz_change INTEGER,
  home_road_streak INTEGER,
  away_road_streak INTEGER,
  home_conference TEXT,
  away_conference TEXT
);

CREATE INDEX IF NOT EXISTS idx_games_season_week ON games(season, week);
CREATE INDEX IF NOT EXISTS idx_games_teams ON games(home_team, away_team);
CREATE INDEX IF NOT EXISTS idx_games_gameday ON games(gameday);

CREATE TABLE IF NOT EXISTS players (
  player_id TEXT PRIMARY KEY,
  player_name TEXT NOT NULL,
  position TEXT,
  latest_team TEXT
);

CREATE INDEX IF NOT EXISTS idx_players_name ON players(player_name);

CREATE TABLE IF NOT EXISTS player_weeks (
  player_id TEXT NOT NULL,
  player_name TEXT,
  position TEXT,
  team TEXT,
  opponent TEXT,
  season INTEGER NOT NULL,
  week INTEGER NOT NULL,
  season_type TEXT,
  game_id TEXT,
  is_home INTEGER,
  completions REAL,
  attempts REAL,
  passing_yards REAL,
  passing_tds REAL,
  interceptions REAL,
  sacks REAL,
  carries REAL,
  rushing_yards REAL,
  rushing_tds REAL,
  targets REAL,
  receptions REAL,
  receiving_yards REAL,
  receiving_tds REAL,
  rushing_receiving_yards REAL,
  fantasy_points REAL,
  practice_status TEXT,
  PRIMARY KEY (player_id, season, week, season_type)
);

CREATE INDEX IF NOT EXISTS idx_pw_game ON player_weeks(game_id);
CREATE INDEX IF NOT EXISTS idx_pw_name ON player_weeks(player_name);
CREATE INDEX IF NOT EXISTS idx_pw_team_week ON player_weeks(team, season, week);

CREATE TABLE IF NOT EXISTS injuries (
  season INTEGER,
  week INTEGER,
  team TEXT,
  player_id TEXT,
  player_name TEXT,
  position TEXT,
  report_status TEXT,
  report_injury TEXT,
  practice_status TEXT,
  date_modified TEXT
);

CREATE INDEX IF NOT EXISTS idx_inj_week_team ON injuries(season, week, team);

CREATE TABLE IF NOT EXISTS missing_regulars (
  season INTEGER,
  week INTEGER,
  team TEXT,
  player_id TEXT,
  player_name TEXT,
  position TEXT,
  side TEXT,
  snap_pct_recent REAL,
  status TEXT,
  injury TEXT,
  date_modified TEXT,
  PRIMARY KEY (season, week, team, player_id)
);

CREATE INDEX IF NOT EXISTS idx_miss_week_team ON missing_regulars(season, week, team);

CREATE TABLE IF NOT EXISTS team_weeks (
  season INTEGER NOT NULL,
  week INTEGER NOT NULL,
  season_type TEXT,
  game_id TEXT,
  team TEXT NOT NULL,
  opponent TEXT,
  is_home INTEGER,
  completions REAL,
  attempts REAL,
  passing_yards REAL,
  passing_tds REAL,
  interceptions REAL,
  sacks_suffered REAL,
  passing_epa REAL,
  carries REAL,
  rushing_yards REAL,
  rushing_tds REAL,
  rushing_epa REAL,
  rushing_fumbles_lost REAL,
  sack_fumbles_lost REAL,
  def_sacks REAL,
  def_interceptions REAL,
  PRIMARY KEY (season, week, season_type, team)
);

CREATE INDEX IF NOT EXISTS idx_tw_game ON team_weeks(game_id);
CREATE INDEX IF NOT EXISTS idx_tw_team ON team_weeks(team, season, week);

CREATE TABLE IF NOT EXISTS player_markets (
  id TEXT PRIMARY KEY,
  player_id TEXT NOT NULL,
  game_id TEXT,
  book TEXT NOT NULL DEFAULT 'FanDuel',
  stat TEXT NOT NULL,
  line REAL NOT NULL,
  over_odds INTEGER,
  under_odds INTEGER,
  open_line REAL,
  open_over_odds INTEGER,
  open_under_odds INTEGER,
  opened_at TEXT,
  source TEXT NOT NULL DEFAULT 'manual',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE (player_id, game_id, book, stat)
);

CREATE INDEX IF NOT EXISTS idx_player_markets_player ON player_markets(player_id, game_id);

CREATE TABLE IF NOT EXISTS game_markets (
  id TEXT PRIMARY KEY,
  game_id TEXT NOT NULL,
  book TEXT NOT NULL DEFAULT 'FanDuel',
  market TEXT NOT NULL,
  home_line REAL,
  away_line REAL,
  home_odds INTEGER,
  away_odds INTEGER,
  over_odds INTEGER,
  under_odds INTEGER,
  open_home_line REAL,
  open_away_line REAL,
  open_home_odds INTEGER,
  open_away_odds INTEGER,
  open_over_odds INTEGER,
  open_under_odds INTEGER,
  opened_at TEXT,
  source TEXT NOT NULL DEFAULT 'odds_api',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE (game_id, book, market)
);

CREATE INDEX IF NOT EXISTS idx_game_markets_game ON game_markets(game_id);
"""


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def connect(path: Path | None = None) -> sqlite3.Connection:
    ensure_dirs()
    conn = sqlite3.connect(path or DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    init_db(conn)
    from collegegridiron.venues import load_homes_from_db

    load_homes_from_db(conn)
    return conn


def reset_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        DROP TABLE IF EXISTS missing_regulars;
        DROP TABLE IF EXISTS injuries;
        DROP TABLE IF EXISTS player_weeks;
        DROP TABLE IF EXISTS players;
        DROP TABLE IF EXISTS team_weeks;
        DROP TABLE IF EXISTS games;
        DROP TABLE IF EXISTS team_venues;
        DROP TABLE IF EXISTS meta;
        """
    )
    init_db(conn)


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _migrate(conn: sqlite3.Connection) -> None:
    if "date_modified" not in _table_columns(conn, "missing_regulars"):
        conn.execute("ALTER TABLE missing_regulars ADD COLUMN date_modified TEXT")


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    _migrate(conn)
    conn.commit()


@contextmanager
def get_db():
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()
