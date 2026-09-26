import { useEffect, useState } from "react";
import {
  fetchTenpage,
  refreshResults,
  type SlateWeek,
  type TenpageResponse,
  type TenpageTicket,
  type TpeUser,
  moveShort,
} from "./api";

function weekKey(week: SlateWeek) {
  return `${week.season}-${week.season_type}-${week.week}`;
}

function money(value: number | null | undefined) {
  if (value == null) return "—";
  const formatted = Math.abs(value).toFixed(2);
  if (value > 0) return `+$${formatted}`;
  if (value < 0) return `-$${formatted}`;
  return "$0.00";
}

function winnerLabel(row: TenpageTicket) {
  if (row.status === "tpe") return "TPE";
  if (row.status === "book") return "Book";
  if (row.status === "push") return "Push";
  return "Pending";
}

export default function TenPage({
  canPullResults = false,
}: {
  account?: TpeUser | null;
  canPullResults?: boolean;
}) {
  const [data, setData] = useState<TenpageResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [ingestBusy, setIngestBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    fetchTenpage()
      .then(setData)
      .catch((err) => setError(err instanceof Error ? err.message : "TENPAGE failed"))
      .finally(() => setLoading(false));
  }, []);

  function loadWeek(season?: number, week?: number, seasonType?: string) {
    setLoading(true);
    setError(null);
    fetchTenpage(season, week, seasonType)
      .then(setData)
      .catch((err) => setError(err instanceof Error ? err.message : "TENPAGE failed"))
      .finally(() => setLoading(false));
  }

  function onWeekChange(value: string) {
    const week = data?.weeks.find((item) => weekKey(item) === value);
    if (!week) return;
    loadWeek(week.season, week.week, week.season_type || "REG");
  }

  function pullResults() {
    setIngestBusy(true);
    setNote(null);
    const week = data?.slate;
    refreshResults(week?.season)
      .then((result) => {
        setNote(
          `Pulled FBS results: ${result.played ?? 0} games with scores, ${result.player_weeks ?? 0} player weeks.`,
        );
        loadWeek(week?.season, week?.week, week?.season_type || "REG");
      })
      .catch((err) => setNote(err instanceof Error ? err.message : "Ingest failed"))
      .finally(() => setIngestBusy(false));
  }

  if (loading && !data) {
    return <p className="note">Loading TENPAGE…</p>;
  }

  const weeks = (data?.weeks ?? []).slice(0, 40);
  const current = data?.slate;
  if (current && !weeks.some((week) => weekKey(week) === weekKey(current))) {
    weeks.unshift(current);
  }

  return (
    <div className="tenpage">
      <div className="slate-bar">
        <div>
          <p className="kicker">TENPAGE</p>
          <h2>{data?.slate?.label ?? "No week loaded"}</h2>
          <p className="sub">
            ${data?.stake ?? 10} on TPE’s side of every stored FanDuel line this week. Graded after
            the game. Not a backtest.
          </p>
        </div>
        <div className="slate-tools">
          {canPullResults && (
            <button type="button" className="text-btn" disabled={ingestBusy} onClick={() => pullResults()}>
              {ingestBusy ? "Pulling results…" : "Pull results"}
            </button>
          )}
          {weeks.length > 0 && (
            <label>
              Week
              <select
                value={data?.slate ? weekKey(data.slate) : ""}
                onChange={(e) => onWeekChange(e.target.value)}
              >
                {weeks.map((week) => (
                  <option key={weekKey(week)} value={weekKey(week)}>
                    {week.label}
                  </option>
                ))}
              </select>
            </label>
          )}
        </div>
      </div>

      {note && <p className="note">{note}</p>}
      {error && <p className="error">{error}</p>}

      {data && (
        <div className="tenpage-totals">
          <div>
            <span>TPE total</span>
            <b className={(data.graded_total || 0) >= 0 ? "up" : "down"}>{money(data.graded_total)}</b>
          </div>
          <div>
            <span>TPE</span>
            <b>{data.tpe_wins}</b>
          </div>
          <div>
            <span>Book</span>
            <b>{data.book_wins}</b>
          </div>
          <div>
            <span>Push</span>
            <b>{data.pushes}</b>
          </div>
          <div>
            <span>Pending</span>
            <b>{data.pending}</b>
          </div>
          <div>
            <span>Lines</span>
            <b>{data.tickets}</b>
          </div>
        </div>
      )}

      {loading && data && <p className="note">Updating week…</p>}

      {data?.games.length ? (
        data.games.map((game) => (
          <section key={game.game_id} className="tenpage-game">
            <p className="kicker">
              {game.label}
              {game.score ? ` · ${game.score}` : game.played ? "" : " · pending"}
            </p>
            <div className="tpe-table-wrap">
              <table className="tpe-board-table">
                <thead>
                  <tr>
                    <th>Market</th>
                    <th>TPE $10</th>
                    <th>Odds</th>
                    <th>Move</th>
                    <th>Actual</th>
                    <th>Winner</th>
                    <th>$10</th>
                  </tr>
                </thead>
                <tbody>
                  {game.rows.map((row) => (
                    <tr key={row.id} className={`ten-${row.status}`}>
                      <td>{row.market}</td>
                      <td>{row.pick}</td>
                      <td>{row.odds_text}</td>
                      <td title={row.move_label ?? undefined}>{moveShort(row)}</td>
                      <td>{row.actual ?? "—"}</td>
                      <td>{winnerLabel(row)}</td>
                      <td>{money(row.profit)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        ))
      ) : (
        <section className="empty">
          <h2>No stored lines</h2>
          <p>
            TENPAGE only uses FanDuel lines already sitting in the snapshot. Open games on the slate
            to store them, then come back after the games are ingested.
          </p>
        </section>
      )}

      {data?.method && <p className="note">{data.method}</p>}
    </div>
  );
}
