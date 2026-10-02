# Structured Instruments

Monitoring app for autocallable structured notes (contingent income notes) — tracks
coupon barriers, autocall events, and position performance across a portfolio.

## Stack

- **Backend** — Python 3.13, FastAPI, SQLAlchemy, Typer CLI (`si`)
- **Frontend** — React + Vite + TypeScript + Tailwind + Recharts
- **Database** — SQLite at `data/structured_instruments.db`
- **Services** — pricing (yfinance), PDF term-sheet parsing (Claude API),
  coupon evaluation, autocall evaluation, performance

## Setup

```bash
python3.13 -m venv .venv
.venv/bin/pip install -e .
cp .env.example .env        # then fill in ANTHROPIC_API_KEY

cd frontend && npm install
```

## Running

```bash
# Backend — note: the frontend proxies /api to port 8002
.venv/bin/si serve --port 8002

# Frontend (separate shell)
cd frontend && npm run dev   # http://localhost:5173
```

`si serve` has no `--reload` flag, so restart the backend after Python changes.

## CLI

```bash
si add        # add an instrument
si prices     # fetch / backfill underlying prices
si evaluate   # evaluate coupon + autocall events
si status     # portfolio status
si serve      # start the API
```

## API notes

- Endpoints require an **`X-User-Id` header containing an integer** (e.g. `1`);
  requests without it return 400.
- Routes expect a **trailing slash** — `/api/instruments/`, not `/api/instruments`.

```bash
curl -H "X-User-Id: 1" http://localhost:8002/api/instruments/
```

## Data

`data/structured_instruments.db` is committed intentionally so the app has its
dataset on checkout. It contains real position data — keep this repository private.

`.env` is **not** committed; it holds the Anthropic API key.
