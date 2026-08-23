import { useEffect, useState } from "react";
import {
  fetchMatchup,
  fetchSlate,
  type Matchup,
  type MissingRegular,
  type SlateGame,
  type SlateResponse,
  type SlateWeek,
  type TeamCard,
  type TeamProfile,
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
      return `${pos}${row.player_name} ${row.status ?? "Out"}${injury}`;
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

function StatRow({
  label,
  left,
  right,
  signedValue = false,
  digits = 1,
}: {
  label: string;
  left: number | null | undefined;
  right: number | null | undefined;
  signedValue?: boolean;
  digits?: number;
}) {
  const fmt = signedValue ? signed : num;
  return (
    <div className="stat-row">
      <b>{fmt(left, digits)}</b>
      <span>{label}</span>
      <b>{fmt(right, digits)}</b>
    </div>
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
          <dt>Points for</dt>
          <dd>{num(overall?.ppg)}</dd>
        </div>
        <div>
          <dt>Points against</dt>
          <dd>{num(overall?.papg)}</dd>
        </div>
        <div>
          <dt>Margin</dt>
          <dd>{signed(overall?.margin)}</dd>
        </div>
        <div>
          <dt>Yards</dt>
          <dd>{num(overall?.yards, 0)}</dd>
        </div>
        <div>
          <dt>Yards allowed</dt>
          <dd>{num(overall?.yards_allowed, 0)}</dd>
        </div>
        <div>
          <dt>Pass / rush yds</dt>
          <dd>
            {num(overall?.pass_yards, 0)} / {num(overall?.rush_yards, 0)}
          </dd>
        </div>
        <div>
          <dt>Pass EPA</dt>
          <dd>{signed(overall?.pass_epa, 2)}</dd>
        </div>
        <div>
          <dt>Rush EPA</dt>
          <dd>{signed(overall?.rush_epa, 2)}</dd>
        </div>
        <div>
          <dt>Plays</dt>
          <dd>{num(overall?.plays, 0)}</dd>
        </div>
        <div>
          <dt>Sacks taken / made</dt>
          <dd>
            {num(overall?.sacks_suffered, 1)} / {num(overall?.def_sacks, 1)}
          </dd>
        </div>
        <div>
          <dt>Turnovers</dt>
          <dd>{num(overall?.turnovers, 1)}</dd>
        </div>
        <div>
          <dt>Last 4</dt>
          <dd>
            {num(recent?.ppg)} / {num(recent?.papg)} ({signed(recent?.margin)})
          </dd>
        </div>
        <div>
          <dt>{roleLabel} split</dt>
          <dd>
            {role
              ? `${num(role.ppg)} / ${num(role.papg)} in ${role.games}`
              : "—"}
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

export default function SlateDesk() {
  const [data, setData] = useState<SlateResponse | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [matchup, setMatchup] = useState<Matchup | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

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
    fetchMatchup(selected)
      .then(setMatchup)
      .catch((err) => setError(err instanceof Error ? err.message : "Matchup failed"));
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

  if (loading && !data) {
    return <p className="note">Loading this week’s slate…</p>;
  }

  if (matchup) {
    const { game, expected, away, home } = matchup;
    return (
      <div className="matchup-desk">
        <button type="button" className="back" onClick={() => setSelected(null)}>
          ← Back to slate
        </button>
        <header className="matchup-head">
          <p className="kicker">
            {kickoff(game)} · {roofLabel(game)}
            {game.stadium ? ` · ${game.stadium}` : ""}
          </p>
          <h2>
            {game.away_team} @ {game.home_team}
          </h2>
          <p className="sub">
            Rest {game.away_rest ?? "—"}d / {game.home_rest ?? "—"}d
            {game.div_game ? " · Conference" : ""}
            {game.is_primetime ? " · Primetime" : ""}
            {game.away_travel && game.away_travel !== "none"
              ? ` · Away travel ${game.away_travel}`
              : ""}
          </p>
        </header>

        <section className="expected-board">
          <p className="kicker">Expected from team numbers</p>
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
              </div>
              <p className="sub">
                Last {matchup.lookback_games} regular-season games before this
                kickoff. Blend of each team’s scoring and the other side’s points
                allowed, minus FBS league PPG
                {expected.hfa
                  ? `, plus ${num(expected.hfa, 1)} home field from the same window`
                  : ", no home-field (neutral/overseas)"}
                . Not a betting line.
              </p>
              {expected.recent && (
                <p className="note">
                  Last {matchup.recent_games}: {game.away_team} {num(expected.recent.away_points)}{" "}
                  – {game.home_team} {num(expected.recent.home_points)} (total{" "}
                  {num(expected.recent.total)})
                </p>
              )}
              {game.played && (
                <p className="played">
                  Final {game.away_score}–{game.home_score}
                </p>
              )}
            </>
          ) : (
            <p className="sub">Not enough completed games to build an expected score.</p>
          )}
        </section>

        <div className="compare">
          <StatRow label="PPG" left={away.overall?.ppg} right={home.overall?.ppg} />
          <StatRow label="PAPG" left={away.overall?.papg} right={home.overall?.papg} />
          <StatRow
            label="Margin"
            left={away.overall?.margin}
            right={home.overall?.margin}
            signedValue
          />
          <StatRow
            label="Yards"
            left={away.overall?.yards}
            right={home.overall?.yards}
            digits={0}
          />
          <StatRow
            label="Yds allowed"
            left={away.overall?.yards_allowed}
            right={home.overall?.yards_allowed}
            digits={0}
          />
          <StatRow
            label="Pass EPA"
            left={away.overall?.pass_epa}
            right={home.overall?.pass_epa}
            signedValue
            digits={2}
          />
          <StatRow
            label="Plays"
            left={away.overall?.plays}
            right={home.overall?.plays}
            digits={0}
          />
        </div>

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
            Team identity only — no spreads, totals, or moneylines. Click a game
            for each side’s numbers and an expected score from those numbers.
            FBS only.
          </p>
        </div>
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
