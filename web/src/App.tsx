import { useEffect, useState } from "react";
import { fetchMeta, type Meta } from "./api";
import PlayerDesk from "./PlayerDesk";
import SlateDesk from "./SlateDesk";

type Desk = "players" | "slate";

export default function App() {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [desk, setDesk] = useState<Desk>("slate");

  useEffect(() => {
    fetchMeta()
      .then(setMeta)
      .catch(() => setMeta({ ingested: false, stats: {} }));
  }, []);

  return (
    <div className="shell">
      <header className="masthead">
        <div className="brand">
          <img
            src={`${import.meta.env.BASE_URL}collegegridiron-mark.png`}
            alt="Collegegridiron logo"
            width={72}
            height={72}
          />
          <div>
            <p className="kicker">
              {desk === "slate" ? "Team research desk" : "College football research desk"}
            </p>
            <h1>Collegegridiron</h1>
          </div>
        </div>
        <nav className="desks" aria-label="Desks">
          <button
            type="button"
            className={desk === "slate" ? "active" : ""}
            onClick={() => setDesk("slate")}
          >
            This Weeks Games
          </button>
          <button
            type="button"
            className={desk === "players" ? "active" : ""}
            onClick={() => setDesk("players")}
          >
            Player Stats
          </button>
        </nav>
        <p className="meta">
          {meta?.ingested
            ? `${meta.games?.toLocaleString() ?? "—"} games · ${meta.players?.toLocaleString()} players · seasons ${meta.seasons}`
            : "Database not loaded yet. Run python -m collegegridiron.ingest from api/"}
        </p>
      </header>

      {desk === "slate" ? <SlateDesk /> : <PlayerDesk meta={meta} />}
    </div>
  );
}
