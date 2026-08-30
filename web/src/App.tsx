import { FormEvent, useEffect, useState } from "react";
import {
  claimHandedSession,
  fetchMe,
  fetchMeta,
  login,
  tpeAccountUrl,
  type Meta,
  type TpeUser,
} from "./api";
import PlayerDesk from "./PlayerDesk";
import SlateDesk from "./SlateDesk";

type Desk = "players" | "slate";

function DeskSignIn({ onSignedIn }: { onSignedIn: (user: TpeUser) => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onSignedIn(await login({ email, password }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign in failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="desk-signin" onSubmit={onSubmit}>
      <input
        type="email"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        placeholder="Email"
        autoComplete="email"
        required
      />
      <input
        type="password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        placeholder="Password"
        autoComplete="current-password"
        required
      />
      <button type="submit" disabled={busy}>
        {busy ? "…" : "Sign in"}
      </button>
      {error && <span className="error">{error}</span>}
    </form>
  );
}

export default function App() {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [desk, setDesk] = useState<Desk>("slate");
  const [account, setAccount] = useState<TpeUser | null>(null);

  useEffect(() => {
    claimHandedSession();
    fetchMeta()
      .then(setMeta)
      .catch(() => setMeta({ ingested: false, stats: {} }));
    fetchMe().then(setAccount);
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
        <div className="meta">
          <p>
            {meta?.ingested
              ? `${meta.games?.toLocaleString() ?? "—"} games · ${meta.players?.toLocaleString()} players · seasons ${meta.seasons}`
              : "Database not loaded yet. Run python -m collegegridiron.ingest from api/"}
          </p>
          {account ? (
            <a className="account-link" href={tpeAccountUrl("book")}>
              {account.display_name} · book
            </a>
          ) : (
            <>
              <DeskSignIn onSignedIn={setAccount} />
              <a className="account-link" href={tpeAccountUrl("signin")}>
                or create a TPE account
              </a>
            </>
          )}
        </div>
      </header>

      {desk === "slate" ? (
        <SlateDesk account={account} />
      ) : (
        <PlayerDesk meta={meta} account={account} />
      )}
    </div>
  );
}
