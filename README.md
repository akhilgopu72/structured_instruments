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

## Modeling tab (candidate notes)

Offered notes (preliminary pricing supplements) are scored before purchase on
the **Modeling** tab: Monte Carlo + historical replay, fit against the selected
accounts' existing book, and per-ticker 52-week / MACD / support diagnostics.

Candidates get in three ways:

- **Add page** — drop a preliminary supplement PDF; it's parsed with the same
  parser as final prospectuses and, since it has no initial prices yet, lands
  on Modeling instead of in the portfolio.
- **Gmail** — the API server polls every 30 min (`SI_GMAIL_POLL_MINUTES`, 0 to
  disable) for `label:Rahul subject:"STRUCTURED NOTE"` emails (`SI_GMAIL_QUERY`)
  and parses new PDF attachments. One-time setup, in the Google account that
  receives the emails:
  1. Google Cloud Console → enable the Gmail API → create an OAuth client of
     type *Desktop app* → download its JSON to `data/gmail/credentials.json`.
  2. `.venv/bin/si gmail auth` (opens a browser; grants read-only access).
  3. Restart `si serve`. `si gmail sync` runs a sync by hand.
  `data/gmail/` (secret, token, downloaded PDFs) is git-ignored. Each
  attachment is parsed at most once (`gmail_processed_attachment`).
- **JSON** — `si candidates import data/candidates/2026-10.json`.

CLI equivalents: `si candidates list --month 2026-10`,
`si screen --month 2026-10 --account-id 1`.

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
