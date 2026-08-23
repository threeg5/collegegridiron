# Collegegridiron — FBS situational research desk

Personal research tool for player-game stats plus the context box scores miss: home/away, rest, weather (when known), moneyline/ATS streaks, travel, and regulars who did not appear. The Slate desk shows this week’s FBS games with each team’s numbers (no betting lines) and an expected score from those numbers.

Data comes from [sportsdataverse / cfbfastR](https://github.com/sportsdataverse/cfbfastR) parquet releases (schedules, team/player box scores, advanced EPA, rosters). Not an official NCAA feed and not a betting “lock” engine. College football has no NFL-style injury report, so “regulars out” means recent high-usage players who did not show up in that week’s box score.

## Structure

- `api/` — FastAPI + SQLite. Entry: `main.py`. Ingest: `python -m collegegridiron.ingest`
- `web/` — Vite + React desk UI

## Run locally

```
cd api
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m collegegridiron.ingest
uvicorn main:app --reload --port 8002

cd web
npm install
npm run dev
```

Open `http://127.0.0.1:5176`. API defaults to `http://127.0.0.1:8002`.

First ingest pulls 2022–2026 FBS seasons from GitHub. Takes several minutes.

## Deploy (Render + HostGator)

API on Render (Python + SQLite disk). Public site is a HostGator folder, not a custom DNS record.

1. Push this repo to GitHub (private).
2. [render.com](https://render.com) → New → **Blueprint** → this repo.
3. First API boot starts ingest in the background if the disk is empty (several minutes).
4. Put the API hostname in `web/.env.hostgator` as `VITE_API_URL`.
5. From `web/`: `npm run build:hostgator` then `npm run deploy:hostgator`.
6. Keep `CORS_ORIGINS` on **collegegridiron-api** as `https://theprofitengineer.com,https://www.theprofitengineer.com`.

Public URL: `https://theprofitengineer.com/collegegridiron`. The site is public until auth is added. Render free API will sleep when idle.
