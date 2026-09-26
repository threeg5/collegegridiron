"""Game-script Monte Carlo on top of TPE expected scores and player means."""

from __future__ import annotations

import numpy as np

SIMS = 5000
TEAM_SD = 9.8
CORR = 0.22


def _seed(game_id: str | None) -> int:
    text = game_id or "tpe"
    value = 0
    for char in text:
        value = (value * 131 + ord(char)) & 0xFFFFFFFF
    return value or 1


def score_draws(
    home_mu: float,
    away_mu: float,
    *,
    game_id: str | None = None,
    n: int = SIMS,
    sd: float = TEAM_SD,
) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(_seed(game_id))
    u = rng.normal(0.0, 1.0, n)
    v = rng.normal(0.0, 1.0, n)
    root = float(np.sqrt(max(0.0, 1.0 - CORR * CORR)))
    homes = np.clip(np.rint(home_mu + sd * u), 0, None).astype(int)
    aways = np.clip(np.rint(away_mu + sd * (CORR * u + root * v)), 0, None).astype(int)
    return homes, aways


def _share(mask: np.ndarray) -> float:
    if mask.size == 0:
        return 0.0
    return round(float(mask.mean()), 3)


def game_probs(
    homes: np.ndarray,
    aways: np.ndarray,
    *,
    home_spread: float | None = None,
    total_line: float | None = None,
) -> dict:
    n = int(min(len(homes), len(aways)))
    homes = homes[:n]
    aways = aways[:n]
    return {
        "n": n,
        "home_cover": _share(homes + float(home_spread) > aways) if home_spread is not None else None,
        "over": _share(homes + aways > float(total_line)) if total_line is not None else None,
        "home_ml": _share(homes > aways),
    }


def script_mult(stat: str, team_pts: np.ndarray, opp_pts: np.ndarray) -> np.ndarray:
    margin = team_pts.astype(float) - opp_pts.astype(float)
    if stat in {"passing_yards", "passing_tds", "receptions", "receiving_yards", "receiving_tds"}:
        return np.clip(1.0 - 0.012 * margin, 0.88, 1.12)
    if stat in {"carries", "rushing_yards", "rushing_tds"}:
        return np.clip(1.0 + 0.010 * margin, 0.90, 1.10)
    return np.ones(len(team_pts))


def prop_over_prob(
    homes: np.ndarray,
    aways: np.ndarray,
    *,
    expected: float,
    line: float,
    sd: float,
    stat: str,
    is_home: bool,
    poisson: bool,
    game_id: str | None = None,
) -> float:
    rng = np.random.default_rng(_seed(f"{game_id}:{stat}:{round(expected, 2)}:{round(line, 1)}"))
    n = int(min(len(homes), len(aways)))
    team_pts = homes[:n] if is_home else aways[:n]
    opp_pts = aways[:n] if is_home else homes[:n]
    mean = np.maximum(0.05, float(expected) * script_mult(stat, team_pts, opp_pts))
    if poisson:
        values = rng.poisson(mean)
    else:
        values = rng.normal(mean, max(0.4, float(sd)))
    return _share(values > line)
