const API = (import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8002").replace(
  /\/$/,
  "",
);

export type PlayerHit = {
  player_id: string;
  player_name: string;
  position: string | null;
  latest_team: string | null;
};

export type PlayerSummary = PlayerHit & {
  default_stat: string;
  default_line: number;
  stats: Record<string, string>;
};

export type MissingRegular = {
  player_name: string;
  position: string | null;
  side: string | null;
  snap_pct_recent: number | null;
  status: string | null;
  injury: string | null;
};

export type PropGame = {
  season: number;
  week: number;
  gameday: string | null;
  team: string;
  opponent: string;
  is_home: number | null;
  stat_value: number | null;
  hit: boolean;
  roof: string | null;
  temp: number | null;
  wind: number | null;
  rest_days: number | null;
  ml_streak: number | null;
  ats_streak: number | null;
  travel: string | null;
  travel_miles: number | null;
  tz_change: number | null;
  road_streak: number | null;
  practice_status: string | null;
  div_game: number | null;
  is_primetime: number | null;
  is_altitude: number | null;
  is_overseas: number | null;
  surface_group: string | null;
  stadium: string | null;
  favored: number | null;
  spread_line: number | null;
  home_score: number | null;
  away_score: number | null;
  missing_teammates: MissingRegular[];
  missing_opponents: MissingRegular[];
};

export type PropResult = {
  player: PlayerHit;
  stat: string;
  stat_label: string;
  line: number;
  sample_size: number;
  hits: number;
  hit_rate: number | null;
  mean: number | null;
  median: number | null;
  games: PropGame[];
};

export type Meta = {
  ingested: boolean;
  stats: Record<string, string>;
  ingested_at?: string;
  seasons?: string;
  games?: number;
  players?: number;
  player_weeks?: number;
  team_weeks?: number;
  missing_regulars?: number;
};

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API}${path}`);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || res.statusText);
  }
  return res.json();
}

export function fetchMeta() {
  return getJson<Meta>("/api/meta");
}

export function searchPlayers(q: string) {
  return getJson<PlayerHit[]>(`/api/players/search?q=${encodeURIComponent(q)}`);
}

export function fetchPlayer(id: string) {
  return getJson<PlayerSummary>(`/api/players/${encodeURIComponent(id)}`);
}

export type PropQuery = {
  stat: string;
  line: number;
  home: "" | "1" | "0";
  minRest: string;
  maxWind: string;
  roof: "" | "outdoors" | "indoor";
  mlStreak: "" | "win" | "loss";
  atsStreak: "" | "win" | "loss";
  travel: "" | "none" | "short" | "long" | "overseas";
  practice: "" | "dnp" | "limited" | "full" | "listed";
  divGame: "" | "1" | "0";
  primetime: "" | "1" | "0";
  shortWeek: "" | "1";
  offBye: "" | "1";
  surface: "" | "grass" | "turf";
  altitude: "" | "1";
  favored: "" | "1" | "0";
  westCoastEarly: "" | "1";
  consecRoad: "" | "1";
};

export function fetchProp(playerId: string, q: PropQuery) {
  const params = new URLSearchParams({
    stat: q.stat,
    line: String(q.line),
  });
  if (q.home) params.set("home", q.home);
  if (q.minRest) params.set("min_rest", q.minRest);
  if (q.maxWind) params.set("max_wind", q.maxWind);
  if (q.roof) params.set("roof", q.roof);
  if (q.mlStreak) params.set("ml_streak", q.mlStreak);
  if (q.atsStreak) params.set("ats_streak", q.atsStreak);
  if (q.travel) params.set("travel", q.travel);
  if (q.practice) params.set("practice", q.practice);
  if (q.divGame) params.set("div_game", q.divGame);
  if (q.primetime) params.set("primetime", q.primetime);
  if (q.shortWeek) params.set("short_week", q.shortWeek);
  if (q.offBye) params.set("off_bye", q.offBye);
  if (q.surface) params.set("surface", q.surface);
  if (q.altitude) params.set("altitude", q.altitude);
  if (q.favored) params.set("favored", q.favored);
  if (q.westCoastEarly) params.set("west_coast_early", q.westCoastEarly);
  if (q.consecRoad) params.set("consec_road", q.consecRoad);
  return getJson<PropResult>(
    `/api/players/${encodeURIComponent(playerId)}/prop?${params}`,
  );
}

export type SlateWeek = {
  season: number;
  week: number;
  season_type: string | null;
  games: number;
  first_gameday: string | null;
  last_gameday: string | null;
  unplayed: number | null;
  label: string;
};

export type SlateGame = {
  game_id: string;
  season: number;
  week: number;
  season_type: string | null;
  gameday: string | null;
  weekday: string | null;
  gametime: string | null;
  home_team: string;
  away_team: string;
  home_name: string;
  away_name: string;
  home_score: number | null;
  away_score: number | null;
  played: boolean;
  roof: string | null;
  surface_group: string | null;
  temp: number | null;
  wind: number | null;
  stadium: string | null;
  location: string | null;
  home_rest: number | null;
  away_rest: number | null;
  div_game: number | null;
  is_primetime: number | null;
  is_altitude: number | null;
  is_overseas: number | null;
  home_travel: string | null;
  away_travel: string | null;
  home_travel_miles: number | null;
  away_travel_miles: number | null;
  home_tz_change: number | null;
  away_tz_change: number | null;
  home_conference: string | null;
  away_conference: string | null;
  neutral: boolean;
};

export type SlateResponse = {
  slate: SlateWeek | null;
  weeks: SlateWeek[];
  games: SlateGame[];
};

export type TeamProfile = {
  games: number;
  from_gameday: string | null;
  to_gameday: string | null;
  from_season: number | null;
  from_week: number | null;
  to_season: number | null;
  to_week: number | null;
  ppg: number | null;
  papg: number | null;
  margin: number | null;
  pass_yards: number | null;
  rush_yards: number | null;
  yards: number | null;
  yards_allowed: number | null;
  pass_epa: number | null;
  rush_epa: number | null;
  turnovers: number | null;
  sacks_suffered: number | null;
  def_sacks: number | null;
  plays: number | null;
};

export type TeamCard = {
  team: string;
  name: string;
  is_home: number;
  overall: TeamProfile | null;
  recent: TeamProfile | null;
  role: TeamProfile | null;
  missing: MissingRegular[];
};

export type ExpectedScore = {
  away_points: number;
  home_points: number;
  total: number;
  margin: number;
  hfa: number | null;
  league_ppg: number | null;
  method: string;
  recent: {
    away_points: number;
    home_points: number;
    total: number;
    margin: number;
  } | null;
};

export type Matchup = {
  game: SlateGame;
  away: TeamCard;
  home: TeamCard;
  environment: {
    league_ppg: number | null;
    hfa: number | null;
    games: number;
  };
  expected: ExpectedScore | null;
  lookback_games: number;
  recent_games: number;
};

export function fetchSlate(season?: number, week?: number, seasonType?: string) {
  const params = new URLSearchParams();
  if (season != null) params.set("season", String(season));
  if (week != null) params.set("week", String(week));
  if (seasonType) params.set("season_type", seasonType);
  const qs = params.toString();
  return getJson<SlateResponse>(`/api/slate${qs ? `?${qs}` : ""}`);
}

export function fetchMatchup(gameId: string) {
  return getJson<Matchup>(`/api/games/${encodeURIComponent(gameId)}/matchup`);
}
