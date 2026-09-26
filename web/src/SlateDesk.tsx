import { useEffect, useState } from "react";
import {
  fetchMatchup,
  fetchSlate,
  formatSnapshot,
  moveShort,
  refreshResults,
  refreshOddsSnapshot,
  type InjuryFreshness,
  type Matchup,
  type MissingRegular,
  type PlayerHit,
  type SlateGame,
  type SlateResponse,
  type SlateWeek,
  type TeamCard,
  type TeamProfile,
  type TpeBoard,
  type TpeBoardRow,
  type TpeUser,
  addFollow,
  addWager,
  lookupFollow,
  removeFollow,
  tpeAccountUrl,
} from "./api";

function num(value: number | null | undefined, digits = 1) {
  if (value == null) return "—";
  return value.toFixed(digits);
}

function signed(value: number | null | undefined, digits = 1) {
  if (value == null) return "—";
  const formatted = value.toFixed(digits);
  return value > 0 ? `+${formatted}` : formatted;
}

function kickoff(game: SlateGame) {
  const day = game.weekday || game.gameday || "";
  const time = game.gametime ? String(game.gametime).slice(0, 5) : "";
  return [day, time].filter(Boolean).join(" · ") || "TBD";
}

function roofLabel(game: SlateGame) {
  const roof = (game.roof || "").toLowerCase();
  if (roof.includes("dome") || roof === "closed") return "Dome";
  if (roof === "retractable") return "Retractable";
  if (roof === "outdoors" || roof === "open") return "Outdoors";
  return game.roof || "—";
}

function formatMissing(rows: MissingRegular[]) {
  if (!rows.length) return "None listed";
  return rows
    .slice(0, 5)
    .map((row) => {
      const pos = row.position ? `${row.position} ` : "";
      const injury = row.injury ? ` · ${row.injury}` : "";
      const when = row.date_modified ? ` · ${formatSnapshot(row.date_modified) ?? ""}` : "";
      return `${pos}${row.player_name} ${row.status ?? "Out"}${injury}${when}`;
    })
    .join(" · ");
}

function sampleRange(profile: TeamProfile | null) {
  if (!profile) return "No completed games yet";
  return `${profile.games} REG games · ${profile.from_season} W${profile.from_week}–${profile.to_season} W${profile.to_week}`;
}

function expectedLabel(matchup: Matchup) {
  const expected = matchup.expected;
  if (!expected) return "Need more completed games to build an expected score.";
  if (expected.margin > 0.4) {
    return `${matchup.home.team} by ${num(expected.margin)}`;
  }
  if (expected.margin < -0.4) {
    return `${matchup.away.team} by ${num(Math.abs(expected.margin))}`;
  }
  return "Pick 'em";
}

/** Books only hang totals and spreads on 0 or .5. */
function toBookHalf(value: number) {
  return Math.round(value * 2) / 2;
}

function halfLabel(value: number) {
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}

function spreadLabel(value: number) {
  if (value === 0) return "PK";
  return `${value > 0 ? "+" : "-"}${halfLabel(Math.abs(value))}`;
}

function bookTickets(expected: { total: number; margin: number }) {
  const total = toBookHalf(expected.total);
  const homeSpread = -toBookHalf(expected.margin);
  return {
    total,
    homeSpread,
    awaySpread: -homeSpread,
    totalLabel: halfLabel(total),
  };
}

function pct(value: number | null | undefined) {
  if (value == null) return "—";
  return `${Math.round(value * 100)}%`;
}

function valueLabel(row: TpeBoardRow) {
  if (row.lean === "juiced") return "Juiced";
  if (row.ev == null) return "—";
  if (row.lean === "close" && Math.abs(row.ev) < 0.03) return "Close";
  const formatted = row.ev.toFixed(2);
  return row.ev > 0 ? `+${formatted}` : formatted;
}

function leanLabel(lean: TpeBoardRow["lean"]) {
  if (lean === "value" || lean === "tpe") return "Value";
  if (lean === "juiced") return "Juiced";
  if (lean === "book") return "Price hotter";
  if (lean === "close") return "Close";
  return "No TPE yet";
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

function TpeLineBoard({
  board,
  expected,
  game,
  importError,
  firstLook,
  onOpenPlayer,
}: {
  board: TpeBoard;
  expected: Matchup["expected"];
  game: SlateGame;
  importError?: string | null;
  firstLook?: boolean;
  onOpenPlayer?: (hit: PlayerHit) => void;
}) {
  const firstId = board.game_rows[0]?.id ?? board.prop_rows[0]?.id ?? null;
  const [selectedId, setSelectedId] = useState<string | null>(firstId);
  const selected =
    board.game_rows.find((row) => row.id === selectedId) ??
    board.prop_rows.find((row) => row.id === selectedId) ??
    null;

  const tpeMargin =
    expected == null
      ? "—"
      : expected.margin > 0.4
        ? `${game.home_team} by ${num(expected.margin)}`
        : expected.margin < -0.4
          ? `${game.away_team} by ${num(Math.abs(expected.margin))}`
          : "Pick 'em";
  const fdHang =
    board.fanduel_spread != null || board.fanduel_total != null
      ? [
          board.fanduel_spread != null
            ? `${game.home_team} ${board.fanduel_spread > 0 ? "+" : ""}${board.fanduel_spread}`
            : null,
          board.fanduel_total != null ? String(board.fanduel_total) : null,
        ]
          .filter(Boolean)
          .join(" · ")
      : "No snapshot";
  const totalVs =
    expected != null && board.fanduel_total != null
      ? `${num(expected.total)} vs ${board.fanduel_total}`
      : "—";

  function renderTable(rows: TpeBoardRow[]) {
    return (
      <table className="tpe-board-table">
        <thead>
          <tr>
            <th>Market</th>
            <th>Line</th>
            <th>FD</th>
            <th>Imp</th>
            <th>TPE</th>
            <th>Val</th>
            <th>Move</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const active = row.id === selected?.id;
            return (
              <tr
                key={row.id}
                className={active ? `lean-${row.lean} active` : `lean-${row.lean}`}
                onClick={() => setSelectedId(row.id)}
              >
                <td>{row.market}</td>
                <td>{row.side}</td>
                <td>{row.book}</td>
                <td>{pct(row.implied)}</td>
                <td>{row.tpe}</td>
                <td>{valueLabel(row)}</td>
                <td>{moveShort(row)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    );
  }

  return (
    <section className="tpe-board">
      <div className="tpe-board-head">
        <div>
          <p className="kicker">FanDuel vs TPE</p>
          <p className="sub">
            {importError
              ? importError
              : board.game_rows.length || board.prop_rows.length
                ? `Click a row for the read.${
                    formatSnapshot(board.snapshot_at) ? ` FD ${formatSnapshot(board.snapshot_at)}.` : ""
                  } Rest, weather, and outs are in the number. % is 5,000 sims. Open is the first snapshot on this desk.`
                : firstLook
                  ? "No FanDuel lines for this game yet."
                  : "Sign in, then open this game to load FanDuel."}
          </p>
        </div>
        <p className="tpe-strip">
          <span>
            TPE {game.away_team} {expected ? num(expected.away_points) : "—"}–{game.home_team}{" "}
            {expected ? num(expected.home_points) : "—"}
          </span>
          <span>{tpeMargin}</span>
          <span>FD {fdHang}</span>
          <span>Tot {totalVs}</span>
          {board.fanduel_spread_open != null && board.fanduel_spread != null && board.fanduel_spread_open !== board.fanduel_spread && (
            <span>
              Open {game.home_team} {board.fanduel_spread_open > 0 ? "+" : ""}
              {board.fanduel_spread_open}
            </span>
          )}
          {board.fanduel_total_open != null && board.fanduel_total != null && board.fanduel_total_open !== board.fanduel_total && (
            <span>Open tot {board.fanduel_total_open}</span>
          )}
        </p>
      </div>
      <FreshNote fresh={board.injury_freshness} />
      <div className="tpe-board-split">
        <div className="tpe-table-wrap">
          {board.game_rows.length > 0 && (
            <>
              <p className="board-kicker">Game</p>
              {renderTable(board.game_rows)}
            </>
          )}
          {board.prop_rows.length > 0 && (
            <>
              <p className="board-kicker">Props</p>
              {renderTable(board.prop_rows)}
            </>
          )}
        </div>
        <aside className="tpe-read-pane">
          {selected ? (
            <>
              <p className="kicker">
                {selected.side}
                <span className={`lean-pill lean-${selected.lean}`}>{leanLabel(selected.lean)}</span>
              </p>
              <p className="tpe-read-meta">
                <span>Book <b>{pct(selected.implied)}</b></span>
                <span>TPE <b>{selected.tpe}</b></span>
                <span>Val <b>{valueLabel(selected)}</b></span>
              </p>
              {selected.move_label && selected.move_kind !== "flat" && (
                <p className="sub">{selected.move_label}</p>
              )}
              <p className="sub">{selected.sample}</p>
              <p className="tpe-copy">{selected.read}</p>
              {selected.player_id && onOpenPlayer && (
                <button
                  type="button"
                  className="text-btn"
                  onClick={() =>
                    onOpenPlayer({
                      player_id: selected.player_id as string,
                      player_name: selected.player_name || selected.side,
                      position: selected.position ?? null,
                      latest_team: selected.latest_team ?? null,
                    })
                  }
                >
                  Player desk
                </button>
              )}
            </>
          ) : (
            <p className="sub">Click a row to read the spot.</p>
          )}
        </aside>
      </div>
    </section>
  );
}

function TeamFacts({
  card,
  roleLabel,
}: {
  card: TeamCard;
  roleLabel: string;
}) {
  const overall = card.overall;
  const recent = card.recent;
  const role = card.role;
  return (
    <section className="team-card">
      <p className="kicker">{roleLabel}</p>
      <h2>{card.team}</h2>
      <p className="team-name">{card.name}</p>
      <p className="sub">{sampleRange(overall)}</p>
      <dl className="team-stats">
        <div>
          <dt>PF / PA</dt>
          <dd>
            {num(overall?.ppg)} / {num(overall?.papg)}
          </dd>
        </div>
        <div>
          <dt>Margin</dt>
          <dd>{signed(overall?.margin)}</dd>
        </div>
        <div>
          <dt>Yds / allwd</dt>
          <dd>
            {num(overall?.yards, 0)} / {num(overall?.yards_allowed, 0)}
          </dd>
        </div>
        <div>
          <dt>Pass / rush</dt>
          <dd>
            {num(overall?.pass_yards, 0)} / {num(overall?.rush_yards, 0)}
          </dd>
        </div>
        <div>
          <dt>Pass EPA</dt>
          <dd>{signed(overall?.pass_epa, 2)}</dd>
        </div>
        <div>
          <dt>Last 4</dt>
          <dd>
            {num(recent?.ppg)} / {num(recent?.papg)}
          </dd>
        </div>
        <div>
          <dt>{roleLabel}</dt>
          <dd>{role ? `${num(role.ppg)} / ${num(role.papg)}` : "—"}</dd>
        </div>
        <div>
          <dt>TO / sacks</dt>
          <dd>
            {num(overall?.turnovers, 1)} / {num(overall?.def_sacks, 1)}
          </dd>
        </div>
      </dl>
      <p className="missing-block">
        <span className="kicker">Regulars out this week</span>
        {formatMissing(card.missing)}
      </p>
    </section>
  );
}

function GameCard({
  game,
  onOpen,
}: {
  game: SlateGame;
  onOpen: (id: string) => void;
}) {
  const tags = [];
  if (game.div_game) tags.push("Conf");
  if (game.is_primetime) tags.push("Prime");
  if (game.is_altitude) tags.push("Alt");
  if (game.neutral) tags.push("Neutral");
  if (game.surface_group) tags.push(game.surface_group);
  return (
    <button type="button" className="game-card" onClick={() => onOpen(game.game_id)}>
      <p className="kicker">{kickoff(game)}</p>
      <p className="matchup-line">
        <span>{game.away_team}</span>
        <small>@</small>
        <span>{game.home_team}</span>
      </p>
      <p className="sub">
        {game.away_conference || game.away_name} at {game.home_conference || game.home_name}
      </p>
      <p className="spot-line">
        {roofLabel(game)}
        {game.stadium ? ` · ${game.stadium}` : ""}
      </p>
      <p className="spot-line">
        Rest {game.away_rest ?? "—"}d / {game.home_rest ?? "—"}d
        {game.away_travel && game.away_travel !== "none"
          ? ` · ${game.away_travel} road`
          : ""}
      </p>
      {game.played && (
        <p className="played">
          Played {game.away_score}–{game.home_score}
        </p>
      )}
      <div className="card-tags">
        {tags.map((tag) => (
          <span className="chip" key={tag}>
            {tag}
          </span>
        ))}
      </div>
    </button>
  );
}

function weekKey(week: SlateWeek) {
  return `${week.season}-${week.season_type}-${week.week}`;
}

function TeamFollow({
  account,
  team,
  name,
}: {
  account: TpeUser | null;
  team: string;
  name: string;
}) {
  const [followId, setFollowId] = useState<string | null>(null);

  useEffect(() => {
    if (!account) {
      setFollowId(null);
      return;
    }
    lookupFollow("team", "cfb", team).then((found) => setFollowId(found?.id ?? null));
  }, [account, team]);

  if (!account) {
    return (
      <a className="book-mini" href={tpeAccountUrl("signin")}>
        Sign in to follow {team}
      </a>
    );
  }

  return (
    <button
      type="button"
      className="book-mini"
      onClick={() => {
        if (followId) {
          void removeFollow(followId).then(() => setFollowId(null));
          return;
        }
        void addFollow({
          kind: "team",
          desk: "cfb",
          subjectId: team,
          subjectName: name || team,
        }).then((row) => setFollowId(row.id));
      }}
    >
      {followId ? `Following ${team}` : `Follow ${team}`}
    </button>
  );
}

export default function SlateDesk({
  account,
  canPullResults = false,
  onOpenPlayer,
  fanduel = false,
  snapshotAt = null,
  injuryFreshness = null,
  onSnapshot,
}: {
  account: TpeUser | null;
  canPullResults?: boolean;
  onOpenPlayer?: (hit: PlayerHit) => void;
  fanduel?: boolean;
  snapshotAt?: string | null;
  injuryFreshness?: InjuryFreshness | null;
  onSnapshot?: () => void;
}) {
  const [data, setData] = useState<SlateResponse | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [matchup, setMatchup] = useState<Matchup | null>(null);
  const [loading, setLoading] = useState(true);
  const [matchupLoading, setMatchupLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [bookNote, setBookNote] = useState<string | null>(null);
  const [snapshotBusy, setSnapshotBusy] = useState(false);
  const [snapshotNote, setSnapshotNote] = useState<string | null>(null);
  const [ingestBusy, setIngestBusy] = useState(false);

  useEffect(() => {
    fetchSlate()
      .then(setData)
      .catch((err) => setError(err instanceof Error ? err.message : "Slate failed"))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!selected) {
      setMatchup(null);
      return;
    }
    setError(null);
    setMatchupLoading(true);
    fetchMatchup(selected)
      .then(setMatchup)
      .catch((err) => setError(err instanceof Error ? err.message : "Matchup failed"))
      .finally(() => setMatchupLoading(false));
  }, [selected]);

  function onWeekChange(value: string) {
    const week = data?.weeks.find((item) => weekKey(item) === value);
    if (!week) return;
    setSelected(null);
    setLoading(true);
    fetchSlate(week.season, week.week, week.season_type || "REG")
      .then(setData)
      .catch((err) => setError(err instanceof Error ? err.message : "Slate failed"))
      .finally(() => setLoading(false));
  }

  function pullResults() {
    setIngestBusy(true);
    setSnapshotNote(null);
    refreshResults(data?.slate?.season)
      .then((result) => {
        setSnapshotNote(
          `Pulled FBS results: ${result.played ?? 0} games with scores, ${result.player_weeks ?? 0} player weeks.`,
        );
        onSnapshot?.();
        const week = data?.slate;
        return fetchSlate(week?.season, week?.week, week?.season_type || "REG").then(setData);
      })
      .catch((err) => setSnapshotNote(err instanceof Error ? err.message : "Ingest failed"))
      .finally(() => setIngestBusy(false));
  }

  function pullSnapshot() {
    setSnapshotBusy(true);
    setSnapshotNote(null);
    refreshOddsSnapshot()
      .then((result) => {
        const when = formatSnapshot(result.snapshot_at);
        setSnapshotNote(
          result.error
            ? result.error
            : `Updated ${result.fetched ?? 0} opened game${result.fetched === 1 ? "" : "s"}${
                when ? ` as of ${when}` : ""
              }.${result.quota_remaining != null ? ` Odds credits left: ${result.quota_remaining}.` : ""}`,
        );
        onSnapshot?.();
        if (selected) {
          return fetchMatchup(selected).then(setMatchup);
        }
      })
      .catch((err) => setSnapshotNote(err instanceof Error ? err.message : "Snapshot failed"))
      .finally(() => setSnapshotBusy(false));
  }

  if (loading && !data) {
    return <p className="note">Loading this week’s slate…</p>;
  }

  if (selected && matchupLoading) {
    return <p className="note">Loading matchup…</p>;
  }

  if (matchup) {
    const { game, expected, away, home } = matchup;
    const tickets = expected ? bookTickets(expected) : null;
    const gameLabel = `${game.away_team} @ ${game.home_team}`;
    return (
      <div className="matchup-desk">
        <header className="matchup-head">
          <button type="button" className="back" onClick={() => setSelected(null)}>
            ← Slate
          </button>
          <div>
            <h2>
              {game.away_team} @ {game.home_team}
            </h2>
            <p className="sub">
              {kickoff(game)} · {roofLabel(game)}
              {game.stadium ? ` · ${game.stadium}` : ""}
              · Rest {game.away_rest ?? "—"}/{game.home_rest ?? "—"}d
              {game.div_game ? " · Conference" : ""}
              {game.is_primetime ? " · Prime" : ""}
              {game.away_travel && game.away_travel !== "none" ? ` · ${game.away_travel} road` : ""}
            </p>
          </div>
          <div className="book-bar">
            <TeamFollow account={account} team={game.away_team} name={game.away_name} />
            <TeamFollow account={account} team={game.home_team} name={game.home_name} />
            {account && <a href={tpeAccountUrl("book")}>Book</a>}
          </div>
        </header>

        <section className="expected-board">
          {expected ? (
            <>
              <div className="expected-scores">
                <div>
                  <span>{game.away_team}</span>
                  <b>{num(expected.away_points)}</b>
                </div>
                <div className="expected-mid">
                  <small>Total {num(expected.total)}</small>
                  <strong>{expectedLabel(matchup)}</strong>
                </div>
                <div>
                  <span>{game.home_team}</span>
                  <b>{num(expected.home_points)}</b>
                </div>
                <div className="expected-extra">
                  {matchup.board && (matchup.board.fanduel_spread != null || matchup.board.fanduel_total != null) && (
                    <p>
                      FD
                      {matchup.board.fanduel_spread != null
                        ? ` ${game.home_team} ${matchup.board.fanduel_spread > 0 ? "+" : ""}${matchup.board.fanduel_spread}`
                        : ""}
                      {matchup.board.fanduel_total != null ? ` · ${matchup.board.fanduel_total}` : ""}
                    </p>
                  )}
                  {expected.recent && (
                    <p>
                      L4 {game.away_team} {num(expected.recent.away_points)}–{game.home_team}{" "}
                      {num(expected.recent.home_points)}
                    </p>
                  )}
                  {expected.context_notes && expected.context_notes.length > 0 && (
                    <p>In TPE: {expected.context_notes.slice(0, 6).join(" · ")}</p>
                  )}
                  {matchup.injury_freshness && <FreshNote fresh={matchup.injury_freshness} />}
                  {game.played && (
                    <p className="played">
                      Final {game.away_score}–{game.home_score}
                    </p>
                  )}
                </div>
              </div>
              <div className="book-bar log-row">
                {account && tickets ? (
                  <>
                    <div className="log-group">
                      <span>Moneyline</span>
                      <button
                        type="button"
                        onClick={() => {
                          void addWager({
                            desk: "cfb",
                            gameLabel,
                            market: "moneyline",
                            side: game.away_team,
                            line: null,
                          }).then(() => setBookNote(`Logged ${game.away_team} ML.`));
                        }}
                      >
                        Log {game.away_team}
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          void addWager({
                            desk: "cfb",
                            gameLabel,
                            market: "moneyline",
                            side: game.home_team,
                            line: null,
                          }).then(() => setBookNote(`Logged ${game.home_team} ML.`));
                        }}
                      >
                        Log {game.home_team}
                      </button>
                    </div>
                    <div className="log-group">
                      <span>Spread</span>
                      <button
                        type="button"
                        onClick={() => {
                          void addWager({
                            desk: "cfb",
                            gameLabel,
                            market: "spread",
                            side: `${game.away_team} ${spreadLabel(tickets.awaySpread)}`,
                            line: tickets.awaySpread,
                          }).then(() =>
                            setBookNote(`Logged ${game.away_team} ${spreadLabel(tickets.awaySpread)}.`),
                          );
                        }}
                      >
                        Log {game.away_team} {spreadLabel(tickets.awaySpread)}
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          void addWager({
                            desk: "cfb",
                            gameLabel,
                            market: "spread",
                            side: `${game.home_team} ${spreadLabel(tickets.homeSpread)}`,
                            line: tickets.homeSpread,
                          }).then(() =>
                            setBookNote(`Logged ${game.home_team} ${spreadLabel(tickets.homeSpread)}.`),
                          );
                        }}
                      >
                        Log {game.home_team} {spreadLabel(tickets.homeSpread)}
                      </button>
                    </div>
                    <div className="log-group">
                      <span>Total</span>
                      <button
                        type="button"
                        onClick={() => {
                          void addWager({
                            desk: "cfb",
                            gameLabel,
                            market: "total",
                            side: `Over ${tickets.totalLabel}`,
                            line: tickets.total,
                          }).then(() => setBookNote(`Logged over ${tickets.totalLabel}.`));
                        }}
                      >
                        Log over {tickets.totalLabel}
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          void addWager({
                            desk: "cfb",
                            gameLabel,
                            market: "total",
                            side: `Under ${tickets.totalLabel}`,
                            line: tickets.total,
                          }).then(() => setBookNote(`Logged under ${tickets.totalLabel}.`));
                        }}
                      >
                        Log under {tickets.totalLabel}
                      </button>
                    </div>
                    {bookNote && <span className="note">{bookNote}</span>}
                  </>
                ) : (
                  <a href={tpeAccountUrl("signin")}>
                    Sign in to log a moneyline, spread, or total
                  </a>
                )}
              </div>
            </>
          ) : (
            <p className="sub">Not enough completed games to build an expected score.</p>
          )}
        </section>

        {fanduel && matchup.board && (
          <TpeLineBoard
            key={game.game_id}
            board={matchup.board}
            expected={expected}
            game={game}
            importError={matchup.props?.import_error}
            firstLook={matchup.props?.first_look}
            onOpenPlayer={onOpenPlayer}
          />
        )}

        <div className="matchup-grid">
          <TeamFacts card={away} roleLabel="Away" />
          <TeamFacts card={home} roleLabel="Home" />
        </div>
      </div>
    );
  }

  const weeks = data?.weeks ?? [];
  const shownWeeks = weeks.slice(0, 40);
  const currentWeek = data?.slate;
  if (currentWeek && !shownWeeks.some((week) => weekKey(week) === weekKey(currentWeek))) {
    shownWeeks.unshift(currentWeek);
  }

  return (
    <>
      <div className="slate-bar">
        <div>
          <p className="kicker">This week’s slate</p>
          <h2>{data?.slate?.label ?? "No games loaded"}</h2>
          <p className="sub">
            Click a game for the expected score and TPE board. Scores refresh
            from ESPN; opened FanDuel games refresh on the same clock.
            {fanduel
              ? formatSnapshot(snapshotAt)
                ? ` FanDuel as of ${formatSnapshot(snapshotAt)}.`
                : " FanDuel loads the first time a game is opened."
              : ""}
          </p>
          <FreshNote fresh={injuryFreshness} />
          {snapshotNote && <p className="note">{snapshotNote}</p>}
        </div>
        <div className="slate-tools">
          {(canPullResults || account?.tier === "owner") && (
            <div className="snapshot-actions">
              {canPullResults && (
                <button type="button" className="text-btn" disabled={ingestBusy} onClick={() => pullResults()}>
                  {ingestBusy ? "Pulling results…" : "Pull results"}
                </button>
              )}
              {account?.tier === "owner" && fanduel && (
                <button type="button" className="text-btn" disabled={snapshotBusy} onClick={() => pullSnapshot()}>
                  {snapshotBusy ? "Refreshing FanDuel…" : "Refresh opened games"}
                </button>
              )}
            </div>
          )}
          {shownWeeks.length > 0 && (
            <label>
              Week
              <select
                value={data?.slate ? weekKey(data.slate) : ""}
                onChange={(e) => onWeekChange(e.target.value)}
              >
                {shownWeeks.map((week) => (
                  <option key={weekKey(week)} value={weekKey(week)}>
                    {week.label}
                  </option>
                ))}
              </select>
            </label>
          )}
        </div>
      </div>

      {error && <p className="error">{error}</p>}

      {data?.games?.length ? (
        <div className="slate-grid">
          {data.games.map((game) => (
            <GameCard key={game.game_id} game={game} onOpen={setSelected} />
          ))}
        </div>
      ) : (
        <section className="empty">
          <h2>No slate yet</h2>
          <p>
            Run ingest so schedules are in the database, then this desk will show
            the current or next FBS week.
          </p>
        </section>
      )}
    </>
  );
}
