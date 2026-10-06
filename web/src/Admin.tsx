import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  createAdminUser,
  fetchAdminUsers,
  patchAdminUser,
  type AdminUser,
  type Tier,
  type TpeUser,
} from "./api";

const TIER_LABEL: Record<Tier, string> = {
  amateur: "Amateur",
  player: "Player",
  owner: "Owner",
};

const TIERS: Tier[] = ["owner", "player", "amateur"];

const DESK_LABEL: Record<string, string> = {
  nfl: "Gridiron",
  cfb: "College Gridiron",
  mlb: "Diamond",
};

function deskLabel(id: string | null) {
  if (!id) return "—";
  return DESK_LABEL[id] ?? id.toUpperCase();
}

function loginHandle(person: Pick<AdminUser, "email" | "username">) {
  return person.username || person.email || "—";
}

function createdLabel(iso: string) {
  return iso.slice(0, 10);
}

export default function AdminDesk({
  viewer,
  onUser,
}: {
  viewer: TpeUser;
  onUser?: (user: TpeUser) => void;
}) {
  const [people, setPeople] = useState<AdminUser[]>([]);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [total, setTotal] = useState(0);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<Tier | "all">("all");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [names, setNames] = useState<Record<string, string>>({});
  const [loaded, setLoaded] = useState(false);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [agentName, setAgentName] = useState("");
  const [agentTier, setAgentTier] = useState<Tier>("amateur");
  const [creating, setCreating] = useState(false);

  async function load() {
    const roster = await fetchAdminUsers();
    setPeople(roster.users);
    setCounts(roster.counts);
    setTotal(roster.total);
    setNames(Object.fromEntries(roster.users.map((person) => [person.id, person.display_name])));
  }

  useEffect(() => {
    let cancelled = false;
    fetchAdminUsers()
      .then((roster) => {
        if (cancelled) return;
        setPeople(roster.users);
        setCounts(roster.counts);
        setTotal(roster.total);
        setNames(Object.fromEntries(roster.users.map((person) => [person.id, person.display_name])));
        setError(null);
        setLoaded(true);
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Could not load accounts.");
          setLoaded(true);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const shown = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return people.filter((person) => {
      if (filter !== "all" && person.tier !== filter) return false;
      if (!needle) return true;
      return (
        person.display_name.toLowerCase().includes(needle) ||
        (person.email ?? "").toLowerCase().includes(needle) ||
        (person.username ?? "").toLowerCase().includes(needle)
      );
    });
  }, [people, query, filter]);

  async function save(person: AdminUser, input: { displayName?: string; tier?: Tier }) {
    setBusyId(person.id);
    setError(null);
    setNotice(null);
    try {
      const next = await patchAdminUser(person.id, input);
      setPeople((current) => current.map((row) => (row.id === next.id ? next : row)));
      setNames((current) => ({ ...current, [next.id]: next.display_name }));
      const roster = await fetchAdminUsers();
      setCounts(roster.counts);
      setTotal(roster.total);
      if (next.id === viewer.id) onUser?.(next);
      setNotice(
        input.tier
          ? `${next.display_name} is now ${TIER_LABEL[next.tier]}.`
          : `Saved ${next.display_name}.`,
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save.");
      await load().catch(() => undefined);
    } finally {
      setBusyId(null);
    }
  }

  async function onName(event: FormEvent, person: AdminUser) {
    event.preventDefault();
    const displayName = (names[person.id] ?? person.display_name).trim();
    if (!displayName || displayName === person.display_name) return;
    await save(person, { displayName });
  }

  async function onCreate(event: FormEvent) {
    event.preventDefault();
    setCreating(true);
    setError(null);
    setNotice(null);
    try {
      const next = await createAdminUser({
        username,
        password,
        displayName: agentName.trim() || undefined,
        tier: agentTier,
      });
      setUsername("");
      setPassword("");
      setAgentName("");
      setAgentTier("amateur");
      await load();
      setNotice(`${next.display_name} can sign in as ${next.username}.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create login.");
    } finally {
      setCreating(false);
    }
  }

  if (viewer.tier !== "owner") {
    return (
      <section className="admin-desk">
        <p className="kicker">Owner</p>
        <h2>Accounts</h2>
        <p className="error">Owner only. Sign in with an owner login to manage profiles.</p>
      </section>
    );
  }

  return (
    <section className="admin-desk">
      <div className="admin-head">
        <div>
          <p className="kicker">Owner</p>
          <h2>Accounts</h2>
          <p className="lede">
            Every TPE login. Change the name or the Amateur / Player / Owner type. Keep at least one owner.
            Agent logins are username and password only — no email.
          </p>
        </div>
      </div>
      <div className="admin-toolbar">
        <p className="admin-counts">
          <button type="button" className={filter === "all" ? "active" : ""} onClick={() => setFilter("all")}>
            {total} accounts
          </button>
          {TIERS.map((tier) => (
            <button
              key={tier}
              type="button"
              className={filter === tier ? "active" : ""}
              onClick={() => setFilter(tier)}
            >
              {counts[tier] ?? 0} {TIER_LABEL[tier]}
            </button>
          ))}
        </p>
        <label className="admin-search">
          Search
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Name, email, or username"
          />
        </label>
      </div>
      {error && <p className="error">{error}</p>}
      {notice && <p className="ok">{notice}</p>}
      <form className="admin-create" onSubmit={(event) => void onCreate(event)}>
        <p className="admin-create-label">Agent login</p>
        <input
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          placeholder="Username"
          autoComplete="off"
          required
          minLength={3}
          maxLength={32}
          aria-label="Username"
        />
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="Password"
          autoComplete="new-password"
          required
          minLength={8}
          aria-label="Password"
        />
        <input
          value={agentName}
          onChange={(e) => setAgentName(e.target.value)}
          placeholder="Name (optional)"
          maxLength={40}
          aria-label="Display name"
        />
        <select
          value={agentTier}
          onChange={(e) => setAgentTier(e.target.value as Tier)}
          aria-label="Account type"
        >
          {TIERS.filter((tier) => tier !== "owner").map((tier) => (
            <option key={tier} value={tier}>
              {TIER_LABEL[tier]}
            </option>
          ))}
        </select>
        <button type="submit" disabled={creating}>
          {creating ? "Creating…" : "Create login"}
        </button>
      </form>
      <div className="admin-table-wrap">
        <table className="admin-table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Login</th>
              <th>Account</th>
              <th>Last desk</th>
              <th>Created</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((person) => (
              <tr key={person.id} className={person.id === viewer.id ? "you" : undefined}>
                <td>
                  <form className="admin-name" onSubmit={(event) => void onName(event, person)}>
                    <input
                      value={names[person.id] ?? person.display_name}
                      onChange={(e) => setNames((current) => ({ ...current, [person.id]: e.target.value }))}
                      maxLength={40}
                      aria-label={`Name for ${loginHandle(person)}`}
                      disabled={busyId === person.id}
                    />
                    <button
                      type="submit"
                      disabled={
                        busyId === person.id ||
                        (names[person.id] ?? person.display_name).trim() === person.display_name
                      }
                    >
                      Save
                    </button>
                    {person.id === viewer.id && <span className="admin-you">You</span>}
                  </form>
                </td>
                <td>{loginHandle(person)}</td>
                <td>
                  <select
                    value={person.tier}
                    aria-label={`Account type for ${person.display_name}`}
                    disabled={busyId === person.id}
                    onChange={(e) => void save(person, { tier: e.target.value as Tier })}
                  >
                    {TIERS.map((tier) => (
                      <option key={tier} value={tier}>
                        {TIER_LABEL[tier]}
                      </option>
                    ))}
                  </select>
                </td>
                <td>{deskLabel(person.last_desk)}</td>
                <td>{createdLabel(person.created_at)}</td>
              </tr>
            ))}
            {!shown.length && (
              <tr>
                <td colSpan={5}>{!loaded ? "Loading accounts…" : people.length ? "No accounts match that search." : "No accounts yet."}</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
