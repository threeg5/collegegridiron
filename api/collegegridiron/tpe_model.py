"""Player-prop baseline: last-year picture, recent form, this week's defense, value vs price."""

from __future__ import annotations

import math
from collections import defaultdict

from collegegridiron.markets import american_implied
from collegegridiron.slate import rows

# Last-year weight after 4 weeks is about 27% — this year starts to lead around week 4–5.
FORM_ALPHA = 0.28
WEEK_INDEX_CAP = 3.0
OPP_MULT_MIN = 0.72
OPP_MULT_MAX = 1.32
EV_VALUE = 0.04
EV_CLOSE = 0.03
LIKELY = 0.55
GAP_CLOSE = 0.03
JUICE_ODDS = -180

STAT_ALLOWED = {
    "passing_yards": "passing_yards",
    "passing_tds": "passing_tds",
    "carries": "carries",
    "rushing_yards": "rushing_yards",
    "rushing_tds": "rushing_tds",
    "receptions": "receptions",
    "receiving_yards": "receiving_yards",
    "receiving_tds": "receiving_tds",
}

POISSON_STATS = {
    "passing_tds",
    "rushing_tds",
    "receiving_tds",
    "receptions",
    "carries",
}

SD_FLOOR = {
    "passing_yards": 45.0,
    "rushing_yards": 22.0,
    "receiving_yards": 18.0,
    "receptions": 1.4,
    "carries": 2.5,
    "passing_tds": 0.7,
    "rushing_tds": 0.45,
    "receiving_tds": 0.4,
}

ALLOWED_COLS = (
    "passing_yards",
    "passing_tds",
    "rushing_yards",
    "rushing_tds",
    "carries",
    "receptions",
    "receiving_yards",
    "receiving_tds",
)


def _phi(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def p_greater_normal(mean: float, threshold: float, sd: float) -> float:
    if sd <= 0:
        return 1.0 if mean > threshold else 0.0
    return 1.0 - _phi((threshold - mean) / sd)


def p_greater_poisson(mean: float, threshold: float) -> float:
    lam = max(0.05, mean)
    need = math.floor(threshold) + 1
    term = math.exp(-lam)
    cdf = term
    for i in range(1, need):
        term *= lam / i
        cdf += term
    return max(0.0, min(1.0, 1.0 - cdf))


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def stdev(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    avg = sum(values) / len(values)
    var = sum((item - avg) ** 2 for item in values) / (len(values) - 1)
    return math.sqrt(var)


def before_week(season: int, week: int, game_season: int, game_week: int) -> bool:
    return season < game_season or (season == game_season and week < game_week)


def ewma_index(ratios: list[float], alpha: float = FORM_ALPHA) -> float:
    index = 1.0
    for ratio in ratios:
        week = clamp(ratio, 0.0, WEEK_INDEX_CAP)
        index = (1.0 - alpha) * index + alpha * week
    return index


def american_ev(p: float, odds: int) -> float:
    price = int(odds)
    profit = price / 100.0 if price > 0 else 100.0 / abs(price)
    return p * profit - (1.0 - p)


def value_lean(p: float | None, implied: float | None, ev: float | None, odds: int | None) -> str:
    if p is None or implied is None:
        return "none"
    if ev is not None and ev >= EV_VALUE:
        return "value"
    juiced_price = odds is not None and int(odds) <= JUICE_ODDS
    if ev is not None and ev < 0 and (p >= LIKELY or juiced_price):
        return "juiced"
    if ev is not None and abs(ev) < EV_CLOSE:
        return "close"
    if abs(p - implied) < GAP_CLOSE:
        return "close"
    return "book" if p < implied else "close"


def _round_p(value: float | None) -> float | None:
    if value is None:
        return None
    return round(max(0.0, min(1.0, value)), 3)


def _round(value: float | None, digits: int = 2) -> float | None:
    if value is None:
        return None
    return round(value, digits)


class DefenseBook:
    def __init__(self, league_ly: dict[str, float], by_team: dict[str, dict[str, object]]):
        self.league_ly = league_ly
        self.by_team = by_team

    def multiplier(self, team: str | None, allowed: str, season: int, week: int) -> float | None:
        if not team:
            return None
        pack = self.by_team.get(team)
        if not pack:
            return None
        ly = pack["ly"].get(allowed)
        league = self.league_ly.get(allowed)
        if not ly or not league:
            return None
        weeks = [
            float(value)
            for w_season, w_week, value in pack["weeks"].get(allowed) or []
            if before_week(w_season, w_week, season, week) and value is not None
        ]
        ratios = [value / ly for value in weeks]
        current = ly * ewma_index(ratios)
        return clamp(current / league, OPP_MULT_MIN, OPP_MULT_MAX)


def load_defense_book(conn, last_year: int, this_year: int) -> DefenseBook:
    sums = ", ".join(f"SUM({col}) AS {col}" for col in ALLOWED_COLS)
    found = rows(
        conn,
        f"""
        SELECT season, week, opponent AS team, game_id, {sums}
        FROM player_weeks
        WHERE COALESCE(season_type, 'REG') = 'REG'
          AND season IN (?, ?)
          AND opponent IS NOT NULL
        GROUP BY season, week, opponent, game_id
        """,
        (last_year, this_year),
    )
    league_sums: dict[str, list[float]] = defaultdict(list)
    ly: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    weeks: dict[str, dict[str, list[tuple[int, int, float]]]] = defaultdict(lambda: defaultdict(list))
    for row in found:
        team = row.get("team")
        if not team:
            continue
        for col in ALLOWED_COLS:
            raw = row.get(col)
            if raw is None:
                continue
            value = float(raw)
            if row["season"] == last_year:
                ly[team][col].append(value)
                league_sums[col].append(value)
            if row["season"] == this_year:
                weeks[team][col].append((int(row["season"]), int(row["week"]), value))
    by_team: dict[str, dict[str, object]] = {}
    for team in set(ly) | set(weeks):
        by_team[team] = {
            "ly": {col: mean(values) for col, values in ly.get(team, {}).items() if mean(values)},
            "weeks": {
                col: sorted(items, key=lambda item: (item[0], item[1]))
                for col, items in weeks.get(team, {}).items()
            },
        }
    league_ly = {col: avg for col, values in league_sums.items() if (avg := mean(values))}
    return DefenseBook(league_ly, by_team)


def load_position_priors(conn, last_year: int, stats: list[str]) -> dict[tuple[str, str], float]:
    if not stats:
        return {}
    cols = ", ".join(f"AVG({stat}) AS {stat}" for stat in stats)
    found = rows(
        conn,
        f"""
        SELECT position, {cols}
        FROM player_weeks
        WHERE COALESCE(season_type, 'REG') = 'REG'
          AND season = ?
          AND position IS NOT NULL
        GROUP BY position
        """,
        (last_year,),
    )
    priors: dict[tuple[str, str], float] = {}
    for row in found:
        position = row.get("position")
        if not position:
            continue
        for stat in stats:
            value = row.get(stat)
            if value is not None:
                priors[(position, stat)] = float(value)
    return priors


def load_player_weeks(conn, player_ids: list[str], stats: list[str], last_year: int, this_year: int) -> dict[str, list[dict]]:
    if not player_ids or not stats:
        return {}
    placeholders = ",".join("?" for _ in player_ids)
    cols = ", ".join(stats)
    found = rows(
        conn,
        f"""
        SELECT player_id, position, team, opponent, season, week, {cols}
        FROM player_weeks
        WHERE player_id IN ({placeholders})
          AND COALESCE(season_type, 'REG') = 'REG'
          AND season IN (?, ?)
        ORDER BY season, week
        """,
        (*player_ids, last_year, this_year),
    )
    by_player: dict[str, list[dict]] = defaultdict(list)
    for row in found:
        by_player[row["player_id"]].append(row)
    return by_player


def _prior_mean(
    last_year_values: list[float],
    position: str | None,
    stat: str,
    priors: dict[tuple[str, str], float],
) -> tuple[float | None, str]:
    ly = mean(last_year_values)
    if ly and ly > 0:
        return ly, "last_year"
    if position and (position, stat) in priors and priors[(position, stat)] > 0:
        return priors[(position, stat)], "position"
    return None, "none"


def player_prop_model(
    *,
    weeks: list[dict],
    stat: str,
    line: float,
    season: int,
    week: int,
    opponent: str | None,
    defense: DefenseBook,
    priors: dict[tuple[str, str], float],
    odds: int | None,
    under_odds: int | None = None,
    situation_mult: float = 1.0,
    usage_mult: float = 1.0,
    context_notes: list[str] | None = None,
    is_home: bool | None = None,
    homes=None,
    aways=None,
    game_id: str | None = None,
) -> dict:
    allowed = STAT_ALLOWED.get(stat)
    last_year_values = [
        float(row[stat])
        for row in weeks
        if row.get("season") == season - 1 and row.get(stat) is not None
    ]
    this_year = [
        row
        for row in weeks
        if row.get("season") == season
        and before_week(int(row["season"]), int(row["week"]), season, week)
        and row.get(stat) is not None
    ]
    position = next((row.get("position") for row in weeks if row.get("position")), None)
    prior, prior_source = _prior_mean(last_year_values, position, stat, priors)
    hit_values = last_year_values + [float(row[stat]) for row in this_year]
    hits = sum(1 for value in hit_values if value > line)
    sample_size = len(hit_values)
    hit_rate = round(hits / sample_size, 3) if sample_size else None

    if prior is None:
        return {
            "tpe_pct": None,
            "expected": None,
            "form_index": 1.0,
            "form_mean": None,
            "last_year_mean": None,
            "prior_source": prior_source,
            "opp_mult": None,
            "this_year_games": len(this_year),
            "hit_rate": hit_rate,
            "hits": hits,
            "sample_size": sample_size,
            "ev": None,
            "implied": american_implied(odds),
            "overround": _overround(odds, under_odds),
        }

    ratios: list[float] = []
    for row in this_year:
        opp_mult = (
            defense.multiplier(row.get("opponent"), allowed, int(row["season"]), int(row["week"]))
            if allowed
            else None
        )
        expected_then = prior * (opp_mult if opp_mult else 1.0)
        if expected_then <= 0:
            continue
        ratios.append(float(row[stat]) / expected_then)
    index = ewma_index(ratios)
    form_mean = prior * index
    opp_mult = defense.multiplier(opponent, allowed, season, week) if allowed else None
    base = form_mean * (opp_mult if opp_mult else 1.0)
    expected = base * float(situation_mult or 1.0) * float(usage_mult or 1.0)
    sd = max(stdev(last_year_values) or 0.0, SD_FLOOR.get(stat, 1.0))
    if homes is not None and aways is not None and is_home is not None:
        from collegegridiron.tpe_sim import prop_over_prob

        tpe_pct = prop_over_prob(
            homes,
            aways,
            expected=expected,
            line=line,
            sd=sd,
            stat=stat,
            is_home=bool(is_home),
            poisson=stat in POISSON_STATS,
            game_id=game_id,
        )
    elif stat in POISSON_STATS:
        tpe_pct = _round_p(p_greater_poisson(expected, line))
    else:
        tpe_pct = _round_p(p_greater_normal(expected, line, sd))
    implied = american_implied(odds)
    ev = _round(american_ev(tpe_pct, odds), 3) if tpe_pct is not None and odds is not None else None
    return {
        "tpe_pct": tpe_pct,
        "expected": _round(expected, 1),
        "form_index": _round(index, 3),
        "form_mean": _round(form_mean, 1),
        "last_year_mean": _round(prior, 1),
        "prior_source": prior_source,
        "opp_mult": _round(opp_mult, 3) if opp_mult is not None else None,
        "situation_mult": _round(float(situation_mult), 3),
        "usage_mult": _round(float(usage_mult), 3),
        "context_notes": context_notes or [],
        "sims": len(homes) if homes is not None else 0,
        "this_year_games": len(this_year),
        "hit_rate": hit_rate,
        "hits": hits,
        "sample_size": sample_size,
        "ev": ev,
        "implied": implied,
        "overround": _overround(odds, under_odds),
        "sd": _round(sd, 1),
    }


def _overround(over_odds: int | None, under_odds: int | None) -> float | None:
    over_imp = american_implied(over_odds)
    under_imp = american_implied(under_odds)
    if over_imp is None or under_imp is None:
        return None
    return round(over_imp + under_imp - 1.0, 3)


def ev_for_price(p: float | None, odds: int | None) -> float | None:
    if p is None or odds is None:
        return None
    return _round(american_ev(p, odds), 3)
