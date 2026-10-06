const API = (
  import.meta.env.DEV
    ? ""
    : (import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8002")
).replace(/\/$/, "");

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
  date_modified?: string | null;
};

export type InjuryFreshness = {
  ingested_at: string | null;
  newest_modified: string | null;
  hours_old: number | null;
  ingest_hours_old: number | null;
  status: "fresh" | "aging" | "stale" | "none";
  late_window: boolean;
  label: string;
  note: string | null;
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
  fanduel?: boolean;
  fanduel_snapshot_at?: string | null;
  fanduel_snapshot_games?: number;
  fanduel_snapshot_markets?: number;
  ingested_at?: string;
  seasons?: string;
  games?: number;
  players?: number;
  player_weeks?: number;
  team_weeks?: number;
  missing_regulars?: number;
  injury_freshness?: InjuryFreshness | null;
  live_pull?: {
    enabled?: boolean;
    odds_enabled?: boolean;
    late_window?: boolean;
    cooldown_minutes?: number;
    injury_pulled_at?: string | null;
    odds_pulled_at?: string | null;
    injury_due?: boolean;
    odds_due?: boolean;
    busy?: boolean;
  } | null;
  owner_controls?: boolean;
};

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API}${path}`);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || res.statusText);
  }
  return res.json();
}

async function deskJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const token = readSessionToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const res = await fetch(`${API}${path}`, { ...init, headers });
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

export type PlayerSituation = {
  is_home: number;
  opponent: string;
  opponent_name: string;
  rest_days: number | null;
  travel: string | null;
  travel_miles: number | null;
  roof: string | null;
  roof_group: "outdoors" | "indoor" | null;
  wind: number | null;
  temp: number | null;
  primetime: number | null;
  surface_group: string | null;
  stadium: string | null;
};

export type FanDuelMarket = {
  id: string | null;
  player_id: string;
  game_id: string | null;
  book: string;
  stat: string;
  stat_label: string;
  line: number;
  over_odds: number | null;
  under_odds: number | null;
  over_implied: number | null;
  under_implied: number | null;
  open_line?: number | null;
  open_over_odds?: number | null;
  open_under_odds?: number | null;
  open_over_implied?: number | null;
  open_under_implied?: number | null;
  opened_at?: string | null;
  source: "manual" | "odds_api" | string;
  updated_at?: string;
};

export type PlayerCard = {
  player: PlayerHit;
  slate: {
    season: number;
    week: number;
    season_type: string | null;
    label: string;
  } | null;
  game: SlateGame | null;
  situation: PlayerSituation | null;
  markets: FanDuelMarket[];
  suggestions: string[];
  feed: "manual" | "odds_api" | "missing_key" | string;
  import_error?: string | null;
  has_odds_key: boolean;
  quota_remaining?: string | number | null;
  snapshot_at?: string | null;
  first_look?: boolean;
  injury_freshness?: InjuryFreshness | null;
};

export type PropPlayer = PlayerHit & {
  markets: FanDuelMarket[];
};

export type TpeBoardRow = {
  id: string;
  market: string;
  side: string;
  book: string;
  odds: number | null;
  implied: number | null;
  tpe: string;
  tpe_pct: number | null;
  gap_pts: number | null;
  ev: number | null;
  lean: "value" | "juiced" | "close" | "book" | "none" | "tpe";
  sample: string;
  read: string;
  player_id?: string | null;
  stat?: string | null;
  player_name?: string;
  position?: string | null;
  latest_team?: string | null;
  line?: number;
  form_index?: number | null;
  last_year_mean?: number | null;
  expected?: number | null;
  opp_mult?: number | null;
  opp_team?: string | null;
  this_year_games?: number | null;
  hit_rate?: number | null;
  open_line?: number | null;
  open_odds?: number | null;
  opened_at?: string | null;
  line_move?: number | null;
  odds_move?: number | null;
  move_kind?: "number" | "juice" | "both" | "flat" | string | null;
  vs_tpe?: "toward" | "away" | "flat" | string | null;
  move_label?: string | null;
};

export type TpeBoard = {
  book: string;
  snapshot_at?: string | null;
  method: string;
  context_notes?: string[];
  fanduel_spread?: number | null;
  fanduel_total?: number | null;
  fanduel_spread_open?: number | null;
  fanduel_total_open?: number | null;
  injury_freshness?: InjuryFreshness | null;
  game_rows: TpeBoardRow[];
  prop_rows: TpeBoardRow[];
};

export type TenpageTicket = {
  id: string;
  market: string;
  board_side: string;
  pick: string;
  odds: number;
  odds_text: string;
  tpe: string | null;
  tpe_pct: number | null;
  implied: number | null;
  ev: number | null;
  stake: number;
  actual: string | null;
  result: "win" | "loss" | "push" | null;
  open_line?: number | null;
  open_odds?: number | null;
  move_kind?: string | null;
  vs_tpe?: string | null;
  move_label?: string | null;
  winner: "tpe" | "book" | "push" | null;
  profit: number | null;
  status: "tpe" | "book" | "push" | "pending";
};

export type TenpageGame = {
  game_id: string;
  label: string;
  kickoff: string | null;
  played: boolean;
  score: string | null;
  rows: TenpageTicket[];
};

export type TenpageResponse = {
  stake: number;
  slate: SlateWeek | null;
  weeks: SlateWeek[];
  games: TenpageGame[];
  tickets: number;
  pending: number;
  tpe_wins: number;
  book_wins: number;
  pushes: number;
  total: number;
  graded_total: number;
  method: string;
};

export type GameProps = {
  book: string;
  feed: string;
  import_error: string | null;
  has_odds_key: boolean;
  quota_remaining?: string | number | null;
  snapshot_at?: string | null;
  first_look?: boolean;
  players: PropPlayer[];
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
  context_notes?: string[];
  raw_home_points?: number;
  raw_away_points?: number;
  raw_total?: number;
  raw_margin?: number;
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
  props?: GameProps;
  board?: TpeBoard | null;
  injury_freshness?: InjuryFreshness | null;
};

export function fetchSlate(season?: number, week?: number, seasonType?: string) {
  const params = new URLSearchParams();
  if (season != null) params.set("season", String(season));
  if (week != null) params.set("week", String(week));
  if (seasonType) params.set("season_type", seasonType);
  const qs = params.toString();
  return getJson<SlateResponse>(`/api/slate${qs ? `?${qs}` : ""}`);
}

export function fetchTenpage(season?: number, week?: number, seasonType?: string) {
  const params = new URLSearchParams();
  if (season != null) params.set("season", String(season));
  if (week != null) params.set("week", String(week));
  if (seasonType) params.set("season_type", seasonType);
  const qs = params.toString();
  return getJson<TenpageResponse>(`/api/tenpage${qs ? `?${qs}` : ""}`);
}

export function fetchMatchup(gameId: string) {
  return deskJson<Matchup>(`/api/games/${encodeURIComponent(gameId)}/matchup`);
}

const TPE_API = (
  import.meta.env.DEV
    ? "/tpe-api"
    : (import.meta.env.VITE_TPE_API_URL ?? "https://wagechecker-api.onrender.com")
).replace(/\/$/, "");

export type Tier = "amateur" | "player" | "owner";

export type LastSearch = {
  desk?: string;
  player_id?: string;
  player_name?: string;
  position?: string | null;
  latest_team?: string | null;
  stat?: string;
  line?: number;
};

export type TpeUser = {
  id: string;
  email: string | null;
  username: string | null;
  display_name: string;
  tier: Tier;
  last_desk: string | null;
  last_search: LastSearch | null;
  created_at: string;
};

const SESSION_KEY = "tpe_session";
const SESSION_MAX_AGE = 30 * 24 * 60 * 60;
const TPE_HOME = import.meta.env.DEV
  ? "http://127.0.0.1:5175"
  : "https://theprofitengineer.com";

export type AdminUser = TpeUser & { updated_at?: string | null };

export type AdminRoster = {
  users: AdminUser[];
  counts: Record<string, number>;
  total: number;
};

export function tpeAccountUrl(hash: "signin" | "account" | "book" | "admin" = "account") {
  return `${TPE_HOME}/#${hash}`;
}

export function fetchPlayerCard(id: string) {
  return deskJson<PlayerCard>(`/api/players/${encodeURIComponent(id)}/card`);
}

export function savePlayerMarket(
  playerId: string,
  input: {
    stat: string;
    line: number;
    overOdds?: number | null;
    underOdds?: number | null;
    gameId?: string | null;
  },
) {
  return deskJson<FanDuelMarket>(`/api/players/${encodeURIComponent(playerId)}/markets`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export type OddsRefresh = {
  ok: boolean;
  error?: string | null;
  fetched?: number;
  skipped?: number;
  quota_remaining?: string | number | null;
  snapshot_at?: string | null;
  snapshot_games?: number;
  snapshot_markets?: number;
};

export function formatSnapshot(iso?: string | null) {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, { dateStyle: "short", timeStyle: "short" });
}

export function moveShort(row: {
  move_kind?: string | null;
  vs_tpe?: string | null;
  line_move?: number | null;
}) {
  if (!row.move_kind || row.move_kind === "flat") return "—";
  const vs = row.vs_tpe === "toward" ? " toward" : row.vs_tpe === "away" ? " away" : "";
  if (row.move_kind === "juice") return `Juice${vs}`;
  const pts =
    row.line_move != null && Math.abs(row.line_move) >= 0.01
      ? `${row.line_move > 0 ? "+" : ""}${Number(row.line_move)}`
      : "";
  const kind = row.move_kind === "both" ? "n+j" : "";
  return [pts, kind, vs.trim()].filter(Boolean).join(" ") || row.move_kind;
}

export function refreshOddsSnapshot() {
  return deskJson<OddsRefresh>("/api/odds/refresh", { method: "POST" });
}

export type IngestRefresh = {
  ok?: boolean;
  seasons?: number[];
  games?: number;
  played?: number;
  team_weeks?: number;
  player_weeks?: number;
  ingested_at?: string;
};

export function refreshResults(season?: number) {
  const params = new URLSearchParams();
  if (season != null) params.set("season", String(season));
  const qs = params.toString();
  return deskJson<IngestRefresh>(`/api/ingest${qs ? `?${qs}` : ""}`, { method: "POST" });
}

export async function fetchAdminUsers() {
  return authJson<AdminRoster>("/api/admin/users");
}

export async function patchAdminUser(userId: string, input: { displayName?: string; tier?: Tier }) {
  return authJson<AdminUser>(`/api/admin/users/${encodeURIComponent(userId)}`, {
    method: "PATCH",
    body: JSON.stringify(input),
  });
}

export async function createAdminUser(input: {
  username: string;
  password: string;
  displayName?: string;
  tier?: Tier;
}) {
  return authJson<AdminUser>("/api/admin/users", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

function readCookie(name: string) {
  const prefix = `${name}=`;
  for (const part of document.cookie.split("; ")) {
    if (part.startsWith(prefix)) return decodeURIComponent(part.slice(prefix.length));
  }
  return null;
}

export function readSessionToken() {
  return localStorage.getItem(SESSION_KEY) || readCookie(SESSION_KEY);
}

export function writeSessionToken(token: string | null) {
  if (token) {
    localStorage.setItem(SESSION_KEY, token);
    document.cookie = `${SESSION_KEY}=${encodeURIComponent(token)}; Path=/; Max-Age=${SESSION_MAX_AGE}; SameSite=Lax`;
  } else {
    localStorage.removeItem(SESSION_KEY);
    document.cookie = `${SESSION_KEY}=; Path=/; Max-Age=0; SameSite=Lax`;
  }
}

async function authError(res: Response) {
  const text = await res.text();
  try {
    const data = JSON.parse(text) as { detail?: unknown };
    if (typeof data.detail === "string") return data.detail;
  } catch {
    /* use raw text */
  }
  return text || res.statusText;
}

async function authJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const token = readSessionToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const res = await fetch(`${TPE_API}${path}`, { ...init, headers });
  if (!res.ok) {
    if (res.status === 401) writeSessionToken(null);
    throw new Error(await authError(res));
  }
  return res.json() as Promise<T>;
}

export function claimHandedSession() {
  const params = new URLSearchParams(window.location.search);
  const handed = params.get("tpe");
  if (!handed) return;
  writeSessionToken(handed);
  params.delete("tpe");
  const search = params.toString();
  history.replaceState(null, "", `${window.location.pathname}${search ? `?${search}` : ""}${window.location.hash}`);
}

export async function login(input: { email?: string; username?: string; password: string }) {
  const data = await authJson<{ token: string; user: TpeUser }>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify(input),
  });
  writeSessionToken(data.token);
  return data.user;
}

export async function signup(input: {
  email: string;
  password: string;
  displayName: string;
  tier?: Tier;
}) {
  const data = await authJson<{ token: string; user: TpeUser }>("/api/auth/signup", {
    method: "POST",
    body: JSON.stringify(input),
  });
  writeSessionToken(data.token);
  return data.user;
}

export async function fetchMe() {
  if (!readSessionToken()) return null;
  try {
    return await authJson<TpeUser>("/api/auth/me");
  } catch {
    return null;
  }
}

export async function claimOwner() {
  return authJson<TpeUser>("/api/auth/claim-owner", { method: "POST" });
}

export async function patchMe(input: {
  displayName?: string;
  lastDesk?: string;
  lastSearch?: LastSearch | null;
}) {
  return authJson<TpeUser>("/api/auth/me", {
    method: "PATCH",
    body: JSON.stringify(input),
  });
}

export type Follow = {
  id: string;
  kind: "athlete" | "team";
  desk: string;
  subject_id: string;
  subject_name: string;
};

export async function lookupFollow(kind: "athlete" | "team", desk: string, subjectId: string) {
  if (!readSessionToken()) return null;
  try {
    const found = await authJson<Follow | Record<string, never>>(
      `/api/book/follows/lookup?kind=${kind}&desk=${desk}&subject_id=${encodeURIComponent(subjectId)}`,
    );
    return found.id ? (found as Follow) : null;
  } catch {
    return null;
  }
}

export function addFollow(input: {
  kind: "athlete" | "team";
  desk: string;
  subjectId: string;
  subjectName: string;
}) {
  return authJson<Follow>("/api/book/follows", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function removeFollow(id: string) {
  return authJson(`/api/book/follows/${id}`, { method: "DELETE" });
}

export function addSpot(input: {
  desk: string;
  label: string;
  payload?: LastSearch & Record<string, unknown>;
}) {
  return authJson("/api/book/spots", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function addWager(input: {
  desk: string;
  gameLabel: string;
  market: string;
  side: string;
  line?: number | null;
  book?: string | null;
  odds?: number | null;
  placedAt?: string;
  note?: string;
}) {
  return authJson("/api/book/wagers", {
    method: "POST",
    body: JSON.stringify({
      ...input,
      placedAt: input.placedAt ?? new Date().toISOString().slice(0, 10),
    }),
  });
}
