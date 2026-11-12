"""Run the candidate screener and serialize results for the API / Modeling tab."""
from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from structured_instruments.database import get_session
from structured_instruments.models.candidate import ScreenRun
from structured_instruments.services.candidates import list_candidates, to_screen_note
from structured_instruments.services.market_signals import compute_signals
from structured_instruments.services.note_screener import (
    TaxAssumptions,
    load_held_notes,
    screen_candidates,
)

# Flag a note when real history was much harsher than the simulation.
REPLAY_RETURN_GAP = 0.03
REPLAY_LOSS_GAP = 0.10

_run_lock = threading.Lock()


@dataclass
class ScreenParams:
    stake: float = 10_000
    coupon_tax: float = 0.408
    state_tax: float = 0.0
    loss_tax: float = 0.238
    erp: float = 0.05
    reversal: float = 0.0
    reversal_signal: str = "3m"
    paths: int = 30_000


def run_screen(session: Session, month: str, account_ids: list[int], params: ScreenParams) -> dict:
    """Screen the month's (non-dismissed) candidates against *account_ids*."""
    offerings = list_candidates(session, month)
    if not offerings:
        raise ValueError(f"No candidates for {month}")
    notes = [to_screen_note(c) for c in offerings]
    held = load_held_notes(session, account_ids) if account_ids else []
    tax = TaxAssumptions(coupon_rate=params.coupon_tax, capital_loss_rate=params.loss_tax, state_rate=params.state_tax)

    risk_free, market, book, results = screen_candidates(
        notes, tax, held=held, stake=params.stake, equity_risk_premium=params.erp,
        reversal=params.reversal, reversal_signal=params.reversal_signal, n_paths=params.paths,
    )

    tickers = list(dict.fromkeys(t for n in notes for t in n.tickers))
    signals = compute_signals(tickers)
    barriers: dict[str, float] = {}
    for n in notes:
        for t in n.tickers:
            barriers[t] = min(barriers.get(t, 1.0), n.downside_barrier_pct)

    rows = []
    for r in results:
        rp = r.replay
        rows.append({
            "cusip": r.note.cusip,
            "issuer": r.note.issuer,
            "tickers": r.note.tickers,
            "coupon_rate_annual": r.note.coupon_rate_annual,
            "downside_barrier_pct": r.note.downside_barrier_pct,
            "sigma": r.sigma,
            "fair_value": r.fair_value,
            "prob_autocall": r.prob_autocall,
            "expected_life_years": r.expected_life_years,
            "prob_principal_loss": r.prob_principal_loss,
            "expected_loss_given_breach": r.expected_loss_given_breach,
            "pretax_return_per_year": r.pretax_return_per_year,
            "aftertax_return_per_year": r.aftertax_return_per_year,
            "cvar_5_aftertax": r.cvar_5_aftertax,
            "replay": None if rp is None else {
                "windows": rp.windows,
                "first_start": rp.first_start.isoformat(),
                "last_start": rp.last_start.isoformat(),
                "prob_principal_loss": rp.prob_principal_loss,
                "prob_autocall": rp.prob_autocall,
                "aftertax_return_per_year": rp.aftertax_return_per_year,
                "worst_aftertax_pnl": rp.worst_aftertax_pnl,
            },
            "replay_flag": rp is not None and (
                rp.aftertax_return_per_year < r.aftertax_return_per_year - REPLAY_RETURN_GAP
                or rp.prob_principal_loss > r.prob_principal_loss + REPLAY_LOSS_GAP
            ),
            "corr_with_book": r.corr_with_book,
            "prob_breach_in_book_tail": r.prob_breach_in_book_tail,
            "tail_add": r.delta_book_cvar,
            "max_concentration": list(r.max_concentration) if r.max_concentration else None,
            "overlap_tickers": r.overlap_tickers,
        })

    return {
        "risk_free": risk_free,
        "aftertax_hurdle": risk_free * (1 - params.coupon_tax - params.state_tax),
        "params": asdict(params),
        "book": None if book is None else {
            "principal": book.principal,
            "expected_aftertax_pnl": book.expected_aftertax_pnl,
            "cvar_5_aftertax": book.cvar_5_aftertax,
            "prob_any_breach": book.prob_any_breach,
            "concentration": sorted(book.concentration.items(), key=lambda kv: -kv[1]),
            "notes": [
                {
                    "cusip": h.cusip,
                    "principal": h.principal,
                    "levels": [{"ticker": t, "pct": p} for t, p in zip(h.tickers, h.current_pct)],
                    "coupon_barrier_pct": h.coupon_barrier_pct,
                    "downside_barrier_pct": h.downside_barrier_pct,
                }
                for h in book.notes
            ],
        },
        "results": rows,
        "signals": [
            {**asdict(signals[t]), "barrier_pct": barriers[t]}
            for t in tickers
        ],
    }


def start_screen_run(month: str, account_ids: list[int], params: ScreenParams) -> int:
    """Record a run and execute it on a background thread (takes ~1-2 min).
    Only one run executes at a time; later ones wait their turn."""
    session = get_session()
    try:
        run = ScreenRun(
            offering_month=month,
            account_ids=",".join(str(a) for a in account_ids),
            params_json=json.dumps(asdict(params)),
        )
        session.add(run)
        session.commit()
        run_id = run.id
    finally:
        session.close()

    def work() -> None:
        with _run_lock:
            s = get_session()
            try:
                result = run_screen(s, month, account_ids, params)
                r = s.get(ScreenRun, run_id)
                r.result_json = json.dumps(result, default=str)
                r.status = "done"
                r.finished_at = datetime.now()
                s.commit()
            except Exception as exc:
                s.rollback()
                r = s.get(ScreenRun, run_id)
                r.status = "error"
                r.error = str(exc)
                r.finished_at = datetime.now()
                s.commit()
            finally:
                s.close()

    threading.Thread(target=work, daemon=True).start()
    return run_id


def latest_run(session: Session, month: str) -> ScreenRun | None:
    return session.execute(
        select(ScreenRun)
        .where(ScreenRun.offering_month == month)
        .order_by(ScreenRun.id.desc())
        .limit(1)
    ).scalar_one_or_none()
