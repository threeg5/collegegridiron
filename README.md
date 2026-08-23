# Collegegridiron

FBS research desk: searchable player stats with the week’s environment attached — home/away, rest, travel, conference games, win/ATS streaks, and who usually plays but didn’t.

## What this first cut does

Search a player, pick a stat and a line, then see how often they cleared it in comparable games. Each game row shows rest, travel, streaks, and missing regulars on both sidelines.

The slate shows this week’s FBS games with each team’s numbers (no betting lines) and an expected score from those numbers.

## Run

**API** (from `api/`):

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m collegegridiron.ingest
uvicorn main:app --reload --port 8002
```

**Web** (from `web/`):

```
npm install
npm run dev
```

Then open http://127.0.0.1:5176

First ingest pulls 2022–2026 (FBS only) from sportsdataverse parquet on GitHub. Takes several minutes.

## Data

Schedules, rosters, team/player box scores, and advanced EPA come from [sportsdataverse](https://github.com/sportsdataverse/cfbfastR). Not an official NCAA product. There is no league injury report, so missing regulars are inferred from recent usage plus a missing box-score line.

This is decision support from historical data, not a prediction of future results.

## Online (Render + HostGator)

`render.yaml` creates **collegegridiron-api** (Python + SQLite disk). Public site is HostGator at **https://theprofitengineer.com/collegegridiron**.

After the API is up:

```
cd web
npm run build:hostgator
npm run deploy:hostgator
```

That uploads `web/dist` into HostGator `public_html/collegegridiron/`. CORS on the API allows `https://theprofitengineer.com`.
