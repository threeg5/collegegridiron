import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import {
  fetchPlayer,
  fetchPlayerCard,
  fetchProp,
  formatSnapshot,
  type InjuryFreshness,
  searchPlayers,
  type FanDuelMarket,
  type Meta,
  type MissingRegular,
  type PlayerCard,
  type PlayerHit,
  type PlayerSummary,
  type PropQuery,
  type PropResult,
  type Follow,
  type TpeUser,
  addFollow,
  addSpot,
  addWager,
  lookupFollow,
  patchMe,
  removeFollow,
  tpeAccountUrl,
} from "./api";

const EMPTY_QUERY: PropQuery = {
  stat: "rushing_yards",
  line: 70.5,
  home: "",
  minRest: "",
  maxWind: "",
  roof: "",
  mlStreak: "",
  atsStreak: "",
  travel: "",
  practice: "",
  divGame: "",
  primetime: "",
  shortWeek: "",
  offBye: "",
  surface: "",
  altitude: "",
  favored: "",
  westCoastEarly: "",
  consecRoad: "",
};

function streakLabel(value: number | null) {
  if (value == null || value === 0) return "—";
  const n = Math.abs(value);
  return value > 0 ? `${n}W` : `${n}L`;
}

function formatMissing(rows: MissingRegular[]) {
  if (!rows.length) return "—";
  return rows
    .slice(0, 4)
    .map((row) => {
      const pos = row.position ? `${row.position} ` : "";
      const injury = row.injury ? ` · ${row.injury}` : "";
      const when = row.date_modified ? ` · ${formatSnapshot(row.date_modified) ?? ""}` : "";
      return `${pos}${row.player_name} ${row.status ?? "Out"}${injury}${when}`;
    })
    .join(" · ");
}

function pct(value: number | null | undefined) {
  if (value == null) return "—";
  return `${Math.round(value * 100)}%`;
}

function formatOdds(odds: number | null | undefined) {
  if (odds == null) return "—";
  return odds > 0 ? `+${odds}` : String(odds);
}

function tpeRead(result: PropResult, market: FanDuelMarket | null) {
  if (!result.sample_size) {
    return "No matching games with the current filters. Loosen the spot or keep this as a sketch.";
  }
  const parts = [
    `In ${result.sample_size} matching games he cleared ${result.line} ${result.hits} times (${pct(result.hit_rate)}).`,
  ];
  if (result.mean != null) {
    parts.push(`Mean ${result.mean}, median ${result.median ?? "—"}.`);
  }
  const implied = market?.over_implied;
  if (implied == null) {
    parts.push("Add FanDuel odds on the card to compare this rate to the market price.");
  } else {
    const gap = (result.hit_rate ?? 0) - implied;
    parts.push(`FanDuel prices the over around ${pct(implied)} (juice still in).`);
    if (Math.abs(gap) < 0.03) {
      parts.push("History and the price are close — the spot still has to earn the bet.");
    } else if (gap > 0) {
      parts.push(
        `This sample has cleared more often than the price implies (${pct(gap)} gap). That is a question, not a lock.`,
      );
    } else {
      parts.push(`The price is hotter than this sample (${pct(-gap)} the other way).`);
    }
  }
  if (
    market?.open_line != null &&
    market.line != null &&
    market.open_line !== market.line
  ) {
    parts.push(`First snapshot was ${market.open_line}; now ${market.line}.`);
  }
  parts.push("TPE helps you read the spot. You still make the price decision.");
  return parts.join(" ");
}

function FreshNote({ fresh }: { fresh?: InjuryFreshness | null }) {
  if (!fresh) return null;
  return (
    <p className={`fresh-note fresh-${fresh.status}`}>
      {fresh.label}
      {fresh.note ? ` · ${fresh.note}` : ""}
    </p>
  );
}

function pickImportedMarket(profile: PlayerCard | null, restore?: { stat?: string }) {
  if (!profile?.markets.length) return null;
  const order = [
    ...(restore?.stat ? [restore.stat] : []),
    ...profile.suggestions,
    ...profile.markets.map((market) => market.stat),
  ];
  for (const stat of order) {
    const found = profile.markets.find((market) => market.stat === stat);
    if (found) return found;
  }
  return profile.markets[0];
}

function travelLabel(game: {
  travel: string | null;
  travel_miles: number | null;
  tz_change: number | null;
}) {
  if (!game.travel) return "—";
  const bits = [game.travel];
  if (game.travel !== "none" && game.travel_miles != null) {
    bits.push(`${Math.round(game.travel_miles)}mi`);
  }
  if (game.tz_change) bits.push(`${game.tz_change}tz`);
  return bits.join(" · ");
}

function practiceLabel(status: string | null) {
  if (status === "dnp") return "DNP";
  if (status === "limited") return "Limited";
  if (status === "full") return "Full";
  return "—";
}

function practiceClass(status: string | null) {
  if (status === "dnp" || status === "limited" || status === "full") return `chip ${status}`;
  return "chip";
}

function spotTags(game: PropResult["games"][number]) {
  const tags = [];
  if (game.div_game) tags.push("Conf");
  if (game.is_primetime) tags.push("Prime");
  if (game.is_altitude) tags.push("Alt");
  if (game.surface_group) tags.push(game.surface_group);
  if (game.favored === 1) tags.push("Fav");
  if (game.favored === 0) tags.push("Dog");
  if (!tags.length) return "—";
  return tags.map((tag) => (
    <span className="chip" key={tag}>
      {tag}
    </span>
  ));
}

export default function PlayerDesk({
  meta,
  account,
  focusPlayer,
}: {
  meta: Meta | null;
  account: TpeUser | null;
  focusPlayer?: PlayerHit | null;
}) {
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<PlayerHit[]>([]);
  const [player, setPlayer] = useState<PlayerSummary | null>(null);
  const [filters, setFilters] = useState<PropQuery>(EMPTY_QUERY);
  const [result, setResult] = useState<PropResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const boxRef = useRef<HTMLDivElement>(null);
  const restored = useRef(false);
  const [follow, setFollow] = useState<Follow | null>(null);
  const [bookNote, setBookNote] = useState<string | null>(null);
  const [card, setCard] = useState<PlayerCard | null>(null);
  const [selectedMarket, setSelectedMarket] = useState<FanDuelMarket | null>(null);

  useEffect(() => {
    if (query.trim().length < 2) {
      setHits([]);
      return;
    }
    const handle = window.setTimeout(() => {
      searchPlayers(query.trim())
        .then(setHits)
        .catch(() => setHits([]));
    }, 180);
    return () => window.clearTimeout(handle);
  }, [query]);

  useEffect(() => {
    function onClick(event: MouseEvent) {
      if (boxRef.current && !boxRef.current.contains(event.target as Node)) {
        setHits([]);
      }
    }
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, []);

  function rememberSearch(summary: PlayerSummary, query: PropQuery) {
    if (!account) return;
    void patchMe({
      lastDesk: "cfb",
      lastSearch: {
        desk: "cfb",
        player_id: summary.player_id,
        player_name: summary.player_name,
        position: summary.position,
        latest_team: summary.latest_team,
        stat: query.stat,
        line: Number(query.line),
      },
    }).catch(() => undefined);
  }

  async function selectPlayer(hit: PlayerHit, restore?: { stat?: string; line?: number }) {
    setQuery(hit.player_name);
    setHits([]);
    setError(null);
    setSelectedMarket(null);
    const [summary, profile] = await Promise.all([
      fetchPlayer(hit.player_id),
      meta?.fanduel ? fetchPlayerCard(hit.player_id).catch(() => null) : Promise.resolve(null),
    ]);
    setPlayer(summary);
    setCard(profile);
    const imported = pickImportedMarket(profile, restore);
    const next = {
      ...EMPTY_QUERY,
      stat: imported?.stat || restore?.stat || summary.default_stat,
      line: imported?.line ?? restore?.line ?? summary.default_line,
    };
    if (profile?.situation) {
      next.home = profile.situation.is_home ? "1" : "0";
    }
    setSelectedMarket(imported);
    setFilters(next);
    setLoading(true);
    try {
      setResult(await fetchProp(summary.player_id, next));
      rememberSearch(summary, next);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Lookup failed");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (!focusPlayer?.player_id) return;
    restored.current = true;
    void selectPlayer(focusPlayer);
  }, [focusPlayer?.player_id]);

  useEffect(() => {
    const saved = account?.last_search;
    if (restored.current || !saved?.player_id || !saved.player_name) return;
    if (saved.desk && saved.desk !== "cfb") return;
    restored.current = true;
    void selectPlayer(
      {
        player_id: saved.player_id,
        player_name: saved.player_name,
        position: saved.position ?? null,
        latest_team: saved.latest_team ?? null,
      },
      { stat: saved.stat, line: saved.line },
    );
  }, [account]);

  useEffect(() => {
    if (!account || !player) {
      setFollow(null);
      return;
    }
    lookupFollow("athlete", "cfb", player.player_id).then(setFollow);
  }, [account, player?.player_id]);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!player) return;
    if (selectedMarket && selectedMarket.stat === filters.stat && selectedMarket.line !== filters.line) {
      setSelectedMarket({ ...selectedMarket, line: filters.line });
    } else if (selectedMarket && selectedMarket.stat !== filters.stat) {
      setSelectedMarket(importedMarkets.find((market) => market.stat === filters.stat) ?? null);
    }
    await runLookup(player, filters);
  }

  const stats = player?.stats ?? meta?.stats ?? {};
  const importedMarkets = useMemo(() => {
    const preferred = card?.suggestions ?? [];
    const rest = (card?.markets ?? []).filter((market) => !preferred.includes(market.stat));
    const ordered: FanDuelMarket[] = [];
    for (const stat of preferred) {
      const found = card?.markets.find((market) => market.stat === stat);
      if (found) ordered.push(found);
    }
    return [...ordered, ...rest];
  }, [card]);

  async function runLookup(summary: PlayerSummary, query: PropQuery) {
    setLoading(true);
    setError(null);
    try {
      setResult(await fetchProp(summary.player_id, query));
      rememberSearch(summary, query);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Lookup failed");
    } finally {
      setLoading(false);
    }
  }

  async function useMarket(market: FanDuelMarket) {
    if (!player) return;
    const next: PropQuery = {
      ...filters,
      stat: market.stat,
      line: market.line,
      home: card?.situation ? (card.situation.is_home ? "1" : "0") : filters.home,
    };
    setSelectedMarket(market);
    setFilters(next);
    await runLookup(player, next);
  }

  function applyWeekSpot() {
    if (!player || !card?.situation) return;
    const next: PropQuery = {
      ...filters,
      home: card.situation.is_home ? "1" : "0",
      roof: card.situation.roof_group ?? "",
      primetime: card.situation.primetime ? "1" : "0",
    };
    setFilters(next);
    void runLookup(player, next);
  }

  const sampleNote = useMemo(() => {
    if (!result) return null;
    if (result.sample_size < 8) return "Small sample — treat as a sketch, not a rate.";
    if (result.sample_size < 16) return "Modest sample — splits can swing a lot.";
    return "Sample is large enough to browse; still not a future guarantee.";
  }, [result]);

  return (
    <>
      <div className="search" ref={boxRef}>
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search a player — CMC, Mahomes, Lamb…"
          autoFocus
        />
        {hits.length > 0 && (
          <ul className="suggest">
            {hits.map((hit) => (
              <li key={hit.player_id}>
                <button type="button" onClick={() => selectPlayer(hit)}>
                  <strong>{hit.player_name}</strong>
                  <span>
                    {hit.position} · {hit.latest_team}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {player && (
        <div className="book-bar">
          {account ? (
            <>
              <button
                type="button"
                onClick={() => {
                  if (follow) {
                    void removeFollow(follow.id).then(() => setFollow(null));
                    return;
                  }
                  void addFollow({
                    kind: "athlete",
                    desk: "cfb",
                    subjectId: player.player_id,
                    subjectName: player.player_name,
                  }).then(setFollow);
                }}
              >
                {follow ? "Following" : "Follow"}
              </button>
              {result && (
                <>
                  <button
                    type="button"
                    onClick={() => {
                      const label = `${player.player_name} ${stats[filters.stat] ?? filters.stat} ${filters.line}`;
                      void addSpot({
                        desk: "cfb",
                        label,
                        payload: {
                          desk: "cfb",
                          player_id: player.player_id,
                          player_name: player.player_name,
                          stat: filters.stat,
                          line: Number(filters.line),
                        },
                      }).then(() => setBookNote("Spot saved to your book."));
                    }}
                  >
                    Save this spot
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      const stat = stats[filters.stat] ?? filters.stat;
                      void addWager({
                        desk: "cfb",
                        gameLabel: `${player.player_name} · ${stat}`,
                        market: "prop",
                        side: `${player.player_name} over ${filters.line}`,
                        line: Number(filters.line),
                        book: selectedMarket?.book ?? "FanDuel",
                        odds: selectedMarket?.over_odds ?? null,
                      }).then(() => setBookNote(`Logged over ${filters.line}.`));
                    }}
                  >
                    Log over {filters.line}
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      const stat = stats[filters.stat] ?? filters.stat;
                      void addWager({
                        desk: "cfb",
                        gameLabel: `${player.player_name} · ${stat}`,
                        market: "prop",
                        side: `${player.player_name} under ${filters.line}`,
                        line: Number(filters.line),
                        book: selectedMarket?.book ?? "FanDuel",
                        odds: selectedMarket?.under_odds ?? null,
                      }).then(() => setBookNote(`Logged under ${filters.line}.`));
                    }}
                  >
                    Log under {filters.line}
                  </button>
                </>
              )}
              <a href={tpeAccountUrl("book")}>My book</a>
              {bookNote && <span className="note">{bookNote}</span>}
            </>
          ) : (
            <a href={tpeAccountUrl("signin")}>Sign in to follow and save spots</a>
          )}
        </div>
      )}

      {player && card && meta?.fanduel && (
        <section className="profile-card">
          <div className="week-strip">
            <p className="kicker">{card.slate?.label ?? "This week"}</p>
            {card.game && card.situation ? (
              <>
                <h2>
                  {player.latest_team} {card.situation.is_home ? "vs" : "@"} {card.situation.opponent}
                </h2>
                <p className="week-meta">
                  {card.game.weekday ?? ""} {card.game.gameday ?? ""}
                  {card.game.gametime ? ` · ${card.game.gametime}` : ""}
                  {card.situation.stadium ? ` · ${card.situation.stadium}` : ""}
                </p>
                <div className="stat-pills">
                  <span className="pill">
                    Spot <b>{card.situation.is_home ? "Home" : "Away"}</b>
                  </span>
                  <span className="pill">
                    Rest <b>{card.situation.rest_days ?? "—"}d</b>
                  </span>
                  <span className="pill">
                    Roof <b>{card.situation.roof ?? "—"}</b>
                  </span>
                  {card.situation.wind != null && (
                    <span className="pill">
                      Wind <b>{card.situation.wind} mph</b>
                    </span>
                  )}
                  {card.situation.primetime ? (
                    <span className="pill">
                      Window <b>Prime</b>
                    </span>
                  ) : null}
                </div>
                <button type="button" className="text-btn" onClick={applyWeekSpot}>
                  Match this week’s spot
                </button>
              </>
            ) : (
              <p className="sub">
                {player.latest_team
                  ? `${player.latest_team} is on a bye or not on this slate. Historical TPE still runs.`
                  : "No team listed for this player on the current slate."}
              </p>
            )}
          </div>

          <div className="fd-card">
            <p className="kicker">FanDuel props</p>
            <p className="sub">
              {card.import_error
                ? card.import_error
                : importedMarkets.length
                  ? `FanDuel for this game. Click a prop to load the TPE read.${
                      formatSnapshot(card.snapshot_at) ? ` As of ${formatSnapshot(card.snapshot_at)}.` : ""
                    }`
                  : card.first_look
                    ? "No FanDuel player props for this game yet."
                    : "Sign in, then open this game to load FanDuel."}
            </p>
            <FreshNote fresh={card.injury_freshness} />
            <div className="fd-grid">
              {importedMarkets.map((market) => {
                const active = selectedMarket?.stat === market.stat;
                return (
                  <button
                    key={market.stat}
                    type="button"
                    className={active ? "fd-pick active" : "fd-pick"}
                    onClick={() => void useMarket(market)}
                  >
                    <strong>{market.stat_label}</strong>
                    <span className="fd-line">
                      {market.line}
                      {market.open_line != null && market.open_line !== market.line && (
                        <small className="fd-open">open {market.open_line}</small>
                      )}
                    </span>
                    <span className="fd-odds">
                      {formatOdds(market.over_odds)} / {formatOdds(market.under_odds)}
                      {market.open_over_odds != null &&
                        market.open_over_odds !== market.over_odds && (
                          <small className="fd-open">
                            {" "}
                            was {formatOdds(market.open_over_odds)}
                          </small>
                        )}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
        </section>
      )}

      {player && (
        <form className="filters" onSubmit={onSubmit}>
          <label>
            Stat
            <select
              value={filters.stat}
              onChange={(e) => setFilters({ ...filters, stat: e.target.value })}
            >
              {Object.entries(stats).map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <label>
            Line
            <input
              type="number"
              step="0.5"
              value={filters.line}
              onChange={(e) =>
                setFilters({ ...filters, line: Number(e.target.value) })
              }
            />
          </label>
          <label>
            Home / away
            <select
              value={filters.home}
              onChange={(e) =>
                setFilters({ ...filters, home: e.target.value as PropQuery["home"] })
              }
            >
              <option value="">All</option>
              <option value="1">Home</option>
              <option value="0">Away</option>
            </select>
          </label>
          <label>
            Min rest
            <select
              value={filters.minRest}
              onChange={(e) => setFilters({ ...filters, minRest: e.target.value })}
            >
              <option value="">Any</option>
              <option value="6">6+ days</option>
              <option value="10">Bye / 10+</option>
            </select>
          </label>
          <label>
            Roof
            <select
              value={filters.roof}
              onChange={(e) =>
                setFilters({ ...filters, roof: e.target.value as PropQuery["roof"] })
              }
            >
              <option value="">Any</option>
              <option value="outdoors">Outdoors</option>
              <option value="indoor">Dome / closed</option>
            </select>
          </label>
          <label>
            Max wind
            <select
              value={filters.maxWind}
              onChange={(e) => setFilters({ ...filters, maxWind: e.target.value })}
            >
              <option value="">Any</option>
              <option value="10">≤ 10 mph</option>
              <option value="15">≤ 15 mph</option>
            </select>
          </label>
          <label>
            ML streak in
            <select
              value={filters.mlStreak}
              onChange={(e) =>
                setFilters({
                  ...filters,
                  mlStreak: e.target.value as PropQuery["mlStreak"],
                })
              }
            >
              <option value="">Any</option>
              <option value="win">2+ wins</option>
              <option value="loss">2+ losses</option>
            </select>
          </label>
          <label>
            ATS streak in
            <select
              value={filters.atsStreak}
              onChange={(e) =>
                setFilters({
                  ...filters,
                  atsStreak: e.target.value as PropQuery["atsStreak"],
                })
              }
            >
              <option value="">Any</option>
              <option value="win">2+ covers</option>
              <option value="loss">2+ ATS losses</option>
            </select>
          </label>
          <label>
            Travel
            <select
              value={filters.travel}
              onChange={(e) =>
                setFilters({ ...filters, travel: e.target.value as PropQuery["travel"] })
              }
            >
              <option value="">Any</option>
              <option value="none">None (true home)</option>
              <option value="short">Short (&lt;700 mi)</option>
              <option value="long">Long</option>
              <option value="overseas">Overseas</option>
            </select>
          </label>
          <label>
            Practice report
            <select
              value={filters.practice}
              onChange={(e) =>
                setFilters({
                  ...filters,
                  practice: e.target.value as PropQuery["practice"],
                })
              }
            >
              <option value="">Any</option>
              <option value="full">Full / not listed</option>
              <option value="limited">Limited</option>
              <option value="dnp">DNP</option>
              <option value="listed">Limited or DNP</option>
            </select>
          </label>
          <label>
            Conference
            <select
              value={filters.divGame}
              onChange={(e) =>
                setFilters({ ...filters, divGame: e.target.value as PropQuery["divGame"] })
              }
            >
              <option value="">Any</option>
              <option value="1">Conference</option>
              <option value="0">Non-conference</option>
            </select>
          </label>
          <label>
            Window
            <select
              value={filters.primetime}
              onChange={(e) =>
                setFilters({
                  ...filters,
                  primetime: e.target.value as PropQuery["primetime"],
                })
              }
            >
              <option value="">Any</option>
              <option value="1">Primetime</option>
              <option value="0">Day game</option>
            </select>
          </label>
          <label>
            Week type
            <select
              value={filters.shortWeek ? "short" : filters.offBye ? "bye" : ""}
              onChange={(e) => {
                const value = e.target.value;
                setFilters({
                  ...filters,
                  shortWeek: value === "short" ? "1" : "",
                  offBye: value === "bye" ? "1" : "",
                });
              }}
            >
              <option value="">Any rest</option>
              <option value="short">Short week (≤5 days)</option>
              <option value="bye">Off a bye (10+)</option>
            </select>
          </label>
          <label>
            Surface
            <select
              value={filters.surface}
              onChange={(e) =>
                setFilters({ ...filters, surface: e.target.value as PropQuery["surface"] })
              }
            >
              <option value="">Any</option>
              <option value="grass">Grass</option>
              <option value="turf">Turf</option>
            </select>
          </label>
          <label>
            Altitude
            <select
              value={filters.altitude}
              onChange={(e) =>
                setFilters({
                  ...filters,
                  altitude: e.target.value as PropQuery["altitude"],
                })
              }
            >
              <option value="">Any</option>
              <option value="1">Denver / altitude</option>
            </select>
          </label>
          <label>
            Spread side
            <select
              value={filters.favored}
              onChange={(e) =>
                setFilters({ ...filters, favored: e.target.value as PropQuery["favored"] })
              }
            >
              <option value="">Any</option>
              <option value="1">Favored</option>
              <option value="0">Underdog</option>
            </select>
          </label>
          <label>
            Extra
            <select
              value={filters.westCoastEarly ? "early" : filters.consecRoad ? "road" : ""}
              onChange={(e) => {
                const value = e.target.value;
                setFilters({
                  ...filters,
                  westCoastEarly: value === "early" ? "1" : "",
                  consecRoad: value === "road" ? "1" : "",
                });
              }}
            >
              <option value="">None</option>
              <option value="early">West Coast 1pm ET</option>
              <option value="road">2nd+ straight road</option>
            </select>
          </label>
          <button type="submit" disabled={loading}>
            {loading ? "Crunching…" : "Run"}
          </button>
        </form>
      )}

      {error && <p className="error">{error}</p>}

      {result && (
        <>
          <div className="player-result">
          <section className="hero">
            <div className="scoreboard">
              <p className="kicker">
                {result.player.player_name} · {result.stat_label} over {result.line}
              </p>
              <p className="rate">{pct(result.hit_rate)}</p>
              <p className="sub">historical hit rate in matching games</p>
              {sampleNote && <p className="note">{sampleNote}</p>}
            </div>
            <div className="hero-side">
              <p className="kicker">Box</p>
              <div className="stat-pills">
                <span className="pill">
                  Hits <b>{result.hits}</b>
                </span>
                <span className="pill">
                  Games <b>{result.sample_size}</b>
                </span>
                <span className="pill">
                  Mean <b>{result.mean ?? "—"}</b>
                </span>
                <span className="pill">
                  Median <b>{result.median ?? "—"}</b>
                </span>
              </div>
            </div>
          </section>

          <section className="tpe-banner">
            <p className="kicker">TPE read</p>
            {selectedMarket ? (
              <p className="tpe-market">
                {selectedMarket.book} · {selectedMarket.stat_label} {selectedMarket.line}
                {selectedMarket.open_line != null && selectedMarket.open_line !== selectedMarket.line
                  ? ` (open ${selectedMarket.open_line})`
                  : ""}{" "}
                · over {formatOdds(selectedMarket.over_odds)} ({pct(selectedMarket.over_implied)}) · under{" "}
                {formatOdds(selectedMarket.under_odds)} ({pct(selectedMarket.under_implied)})
              </p>
            ) : (
              <p className="tpe-market">
                Historical {result.stat_label} over {result.line}
                {meta?.fanduel ? ". Select a FanDuel prop on the card to price it." : "."}
              </p>
            )}
            <p className="tpe-copy">{tpeRead(result, selectedMarket)}</p>
          </section>
          </div>

          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>When</th>
                  <th>Spot</th>
                  <th>Travel</th>
                  <th>Practice</th>
                  <th>Rest</th>
                  <th>Wx</th>
                  <th>Context</th>
                  <th>ML</th>
                  <th>ATS</th>
                  <th>{result.stat_label}</th>
                  <th>Teammates out</th>
                  <th>Opponents out</th>
                </tr>
              </thead>
              <tbody>
                {result.games.map((game) => (
                  <tr key={`${game.season}-${game.week}-${game.opponent}`} className={game.hit ? "hit" : "miss"}>
                    <td>
                      {game.gameday ?? `${game.season} W${game.week}`}
                      <small>
                        W{game.week} {game.season}
                      </small>
                    </td>
                    <td>
                      {game.is_home === 1 ? "vs" : "@"} {game.opponent}
                    </td>
                    <td>{travelLabel(game)}</td>
                    <td>
                      <span className={practiceClass(game.practice_status)}>
                        {practiceLabel(game.practice_status)}
                      </span>
                    </td>
                    <td>{game.rest_days ?? "—"}d</td>
                    <td>
                      {game.roof ?? "—"}
                      {game.wind != null ? ` · ${game.wind}mph` : ""}
                      {game.temp != null ? ` · ${game.temp}°` : ""}
                    </td>
                    <td className="missing">{spotTags(game)}</td>
                    <td>{streakLabel(game.ml_streak)}</td>
                    <td>{streakLabel(game.ats_streak)}</td>
                    <td className="stat">
                      {game.stat_value ?? "—"}
                      <span className={game.hit ? "chip hit" : "chip miss"}>
                        {game.hit ? "over" : "under"}
                      </span>
                    </td>
                    <td className="missing">{formatMissing(game.missing_teammates)}</td>
                    <td className="missing">{formatMissing(game.missing_opponents)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {!player && (
        <section className="empty">
          <h2>Call a player</h2>
          <p>
            {meta?.fanduel
              ? "Search a name or open a player from this week’s game. FanDuel props import with the selection, then TPE compares that line to similar spots. This desk does not pick the bet."
              : "Search a name, set a line, then see how often it hit in comparable games. Travel, rest, weather, and missing regulars sit on each row. This desk does not pick the bet."}
          </p>
        </section>
      )}
    </>
  );
}
