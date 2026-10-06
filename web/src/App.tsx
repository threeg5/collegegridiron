import { FormEvent, useEffect, useState } from "react";
import {
  claimHandedSession,
  claimOwner,
  fetchMe,
  fetchMeta,
  login,
  signup,
  tpeAccountUrl,
  type Meta,
  type PlayerHit,
  type TpeUser,
  type Tier,
} from "./api";
import AdminDesk from "./Admin";
import PlayerDesk from "./PlayerDesk";
import SlateDesk from "./SlateDesk";
import TenPage from "./TenPage";

type Desk = "players" | "slate" | "tenpage" | "admin";

const TIER_LABEL: Record<Tier, string> = {
  amateur: "Amateur",
  player: "Player",
  owner: "Owner",
};

function DeskSignIn({ onSignedIn }: { onSignedIn: (user: TpeUser) => void }) {
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [tier, setTier] = useState<Tier>("amateur");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onSignedIn(
        mode === "signup"
          ? await signup({ email, password, displayName, tier })
          : await login(
              email.includes("@") ? { email, password } : { username: email, password },
            ),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign in failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="desk-signin" onSubmit={onSubmit}>
      <div className="desk-auth-tabs">
        <button type="button" className={mode === "login" ? "active" : ""} onClick={() => setMode("login")}>
          Sign in
        </button>
        <button type="button" className={mode === "signup" ? "active" : ""} onClick={() => setMode("signup")}>
          Create
        </button>
      </div>
      {mode === "signup" && (
        <>
          <input
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            placeholder="Name"
            autoComplete="nickname"
            required
            maxLength={40}
          />
          <select value={tier} onChange={(e) => setTier(e.target.value as Tier)} aria-label="Account type">
            <option value="amateur">Amateur</option>
            <option value="player">Player</option>
            <option value="owner">Owner</option>
          </select>
        </>
      )}
      <input
        type={mode === "signup" ? "email" : "text"}
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        placeholder={mode === "signup" ? "Email" : "Email or username"}
        autoComplete={mode === "signup" ? "email" : "username"}
        required
      />
      <input
        type="password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        placeholder="Password"
        autoComplete={mode === "signup" ? "new-password" : "current-password"}
        required
        minLength={mode === "signup" ? 8 : undefined}
      />
      <button type="submit" disabled={busy}>
        {busy ? "…" : mode === "signup" ? `Create ${TIER_LABEL[tier]}` : "Sign in"}
      </button>
      {mode === "login" && (
        <span className="note">
          Same TPE login as Gridiron. Create an account here if you do not have one yet.
        </span>
      )}
      {error && <span className="error">{error}</span>}
    </form>
  );
}

export default function App() {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [desk, setDesk] = useState<Desk>("slate");
  const [account, setAccount] = useState<TpeUser | null>(null);
  const [focusPlayer, setFocusPlayer] = useState<PlayerHit | null>(null);
  const [claimError, setClaimError] = useState<string | null>(null);

  useEffect(() => {
    claimHandedSession();
    fetchMeta()
      .then(setMeta)
      .catch(() => setMeta({ ingested: false, stats: {} }));
    fetchMe().then(setAccount);
  }, []);

  async function onClaimOwner() {
    setClaimError(null);
    try {
      setAccount(await claimOwner());
      fetchMeta()
        .then(setMeta)
        .catch(() => undefined);
    } catch (err) {
      setClaimError(err instanceof Error ? err.message : "Could not become owner.");
    }
  }

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
              {desk === "slate"
                ? "Team research desk"
                : desk === "tenpage"
                  ? "TENPAGE"
                  : desk === "admin"
                    ? "Owner"
                    : "College football research desk"}
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
          <button
            type="button"
            className={desk === "tenpage" ? "active" : ""}
            onClick={() => setDesk("tenpage")}
          >
            TENPAGE
          </button>
          {account?.tier === "owner" && (
            <button
              type="button"
              className={desk === "admin" ? "active" : ""}
              onClick={() => setDesk("admin")}
            >
              Admin
            </button>
          )}
        </nav>
        <div className="meta">
          <p>
            {meta?.ingested
              ? `${meta.games?.toLocaleString() ?? "—"} games · ${meta.players?.toLocaleString()} players · seasons ${meta.seasons}`
              : "Database not loaded yet. Run python -m collegegridiron.ingest from api/"}
          </p>
          {account ? (
            <div className="account-chip">
              <a
                className="account-link"
                href={tpeAccountUrl(account.tier === "owner" ? "admin" : "account")}
              >
                {account.display_name} · {TIER_LABEL[account.tier]}
              </a>
              {account.tier !== "owner" && !meta?.owner_controls && (
                <button type="button" className="claim-owner" onClick={() => void onClaimOwner()}>
                  Become Owner
                </button>
              )}
              {claimError && <span className="error">{claimError}</span>}
            </div>
          ) : (
            <DeskSignIn onSignedIn={setAccount} />
          )}
        </div>
      </header>

      {desk === "slate" ? (
        <SlateDesk
          account={account}
          canPullResults={!meta?.owner_controls || account?.tier === "owner"}
          fanduel={Boolean(meta?.fanduel)}
          snapshotAt={meta?.fanduel_snapshot_at}
          injuryFreshness={meta?.injury_freshness}
          onSnapshot={() => {
            fetchMeta()
              .then(setMeta)
              .catch(() => undefined);
          }}
          onOpenPlayer={(hit) => {
            setFocusPlayer(hit);
            setDesk("players");
          }}
        />
      ) : desk === "tenpage" ? (
        <TenPage
          account={account}
          canPullResults={!meta?.owner_controls || account?.tier === "owner"}
        />
      ) : desk === "admin" ? (
        account ? (
          <AdminDesk
            viewer={account}
            onUser={(next) => {
              setAccount(next);
              if (next.tier !== "owner") setDesk("slate");
            }}
          />
        ) : (
          <p className="error">Sign in with an owner login to manage profiles.</p>
        )
      ) : (
        <PlayerDesk meta={meta} account={account} focusPlayer={focusPlayer} />
      )}
    </div>
  );
}
