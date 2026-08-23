import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("DATA_DIR", str(ROOT / "data")))
DB_PATH = DATA_DIR / "collegegridiron.db"

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
