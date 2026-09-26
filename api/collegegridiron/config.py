import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent
load_dotenv(ROOT / ".env")
load_dotenv(REPO_ROOT / ".env")

DATA_DIR = Path(os.environ.get("DATA_DIR", str(ROOT / "data")))
DB_PATH = DATA_DIR / "collegegridiron.db"
TPE_API_URL = os.environ.get(
    "TPE_API_URL",
    "https://wagechecker-api.onrender.com",
).strip().rstrip("/")
ODDS_API_KEY = (
    os.environ.get("ODDS_API_KEY", "").strip()
    or os.environ.get("THE_ODDS_API_KEY", "").strip()
)


def _env_bool(name: str) -> str:
    return os.environ.get(name, "").strip().lower()


def fanduel_props_enabled() -> bool:
    """Live kill switch. FANDUEL_PROPS=0 hides FanDuel; 1 forces it on."""
    raw = _env_bool("FANDUEL_PROPS")
    if raw in {"0", "false", "no", "off"}:
        return False
    if raw in {"1", "true", "yes", "on"}:
        return True
    return bool(ODDS_API_KEY)


def odds_first_look_enabled() -> bool:
    """First open of a game buys FanDuel. Later views read SQLite. Set 0 to freeze pulls."""
    return _env_bool("ODDS_FIRST_LOOK") not in {"0", "false", "no", "off"}


def live_pull_enabled() -> bool:
    """Auto-refresh ESPN scores. LIVE_PULL=0 freezes the clock."""
    return _env_bool("LIVE_PULL") not in {"0", "false", "no", "off"}


def live_odds_enabled() -> bool:
    """Auto-refresh already-opened FanDuel games. Never buys unopened games."""
    if not fanduel_props_enabled():
        return False
    return _env_bool("LIVE_ODDS") not in {"0", "false", "no", "off"}

SEASONS = list(range(2022, 2027))
REGULAR_TOUCHES = 6.0
REGULAR_PASS_ATT = 15.0
REGULAR_LOOKBACK_GAMES = 3
TEAM_LOOKBACK_GAMES = 12
TEAM_RECENT_GAMES = 4
HTTP_WORKERS = int(os.environ.get("HTTP_WORKERS", "4"))


def ingest_years() -> list[int]:
    raw = os.environ.get("INGEST_SEASONS", "")
    if raw.strip():
        return [int(part.strip()) for part in raw.split(",") if part.strip()]
    return SEASONS


HOSTGATOR_ORIGINS = (
    "https://theprofitengineer.com",
    "https://www.theprofitengineer.com",
)


def cors_origins() -> list[str]:
    raw = os.environ.get(
        "CORS_ORIGINS",
        "http://127.0.0.1:5176,http://localhost:5176",
    )
    origins = [origin.strip().rstrip("/") for origin in raw.split(",") if origin.strip()]
    for origin in HOSTGATOR_ORIGINS:
        if origin not in origins:
            origins.append(origin)
    return origins
