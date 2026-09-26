from contextlib import asynccontextmanager
from datetime import date
from threading import Thread
import os
import time
import traceback

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from collegegridiron.config import DATA_DIR, DB_PATH, cors_origins, ingest_years
from collegegridiron.db import connect
from collegegridiron.live_pull import kick_live_pull
from collegegridiron.routes import router

LOCK_PATH = DATA_DIR / "ingest.lock"


def _log(message: str) -> None:
    print(message, flush=True)


def _ingest_complete() -> bool:
    if not DB_PATH.exists():
        return False
    conn = connect()
    try:
        row = conn.execute("SELECT value FROM meta WHERE key='ingest_complete'").fetchone()
        return bool(row and str(row[0]) == "1")
    except Exception:
        return False
    finally:
        conn.close()


def _player_count() -> int:
    if not DB_PATH.exists():
        return 0
    conn = connect()
    try:
        return int(conn.execute("SELECT COUNT(*) FROM players").fetchone()[0])
    except Exception:
        return 0
    finally:
        conn.close()


def _clear_stale_lock() -> None:
    if LOCK_PATH.exists():
        _log(f"Removing stale ingest lock {LOCK_PATH}")
        LOCK_PATH.unlink(missing_ok=True)


def _ingest_if_empty() -> None:
    if _ingest_complete():
        _log("Skip ingest; ingest_complete=1")
        return
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
    except FileExistsError:
        _log(f"Skip ingest; lock already present at {LOCK_PATH}")
        return
    try:
        if _ingest_complete():
            _log("Skip ingest; ingest_complete=1")
            return
        from collegegridiron.ingest import run_ingest

        years = ingest_years()
        _log(f"Ingesting sportsdataverse CFB data for {years} (players={_player_count()})")
        run_ingest(years)
        _log("Ingest finished")
    except Exception:
        traceback.print_exc()
    finally:
        LOCK_PATH.unlink(missing_ok=True)


def _upcoming_games() -> int:
    if not DB_PATH.exists():
        return 0
    conn = connect()
    try:
        today = date.today().isoformat()
        return int(conn.execute("SELECT COUNT(*) FROM games WHERE gameday >= ?", (today,)).fetchone()[0])
    except Exception:
        return 0
    finally:
        conn.close()


def _refresh_schedule_if_needed() -> None:
    if not _ingest_complete():
        return
    upcoming = _upcoming_games()
    if upcoming > 0:
        _log(f"Skip schedule refresh; {upcoming} upcoming games")
        return
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
    except FileExistsError:
        _log(f"Skip schedule refresh; lock already present at {LOCK_PATH}")
        return
    try:
        from collegegridiron.ingest import refresh_upcoming_schedules

        year = date.today().year
        _log(f"Refreshing {year} FBS schedule from ESPN")
        result = refresh_upcoming_schedules([year])
        _log(f"Schedule refresh finished {result}")
    except Exception:
        traceback.print_exc()
    finally:
        LOCK_PATH.unlink(missing_ok=True)


def _boot_ingest() -> None:
    _log("Boot ingest thread sleeping 8s")
    time.sleep(8)
    _ingest_if_empty()
    _refresh_schedule_if_needed()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        _log(f"Could not create data dir {DATA_DIR}: {exc}")
    _clear_stale_lock()
    if _ingest_complete():
        _log(f"Boot thread will refresh schedule if needed (players={_player_count()})")
    else:
        _log(f"Starting ingest thread (db={DB_PATH.exists()} players={_player_count()})")
    Thread(target=_boot_ingest, daemon=True).start()
    if _ingest_complete():
        kick_live_pull(reason="boot")
    yield


app = FastAPI(title="Collegegridiron", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)


@app.get("/")
def root():
    return {
        "ok": True,
        "service": "collegegridiron-api",
        "health": "/health",
        "meta": "/api/meta",
    }
