"""Stock-split adjustment service.

Detects stock splits via yfinance and adjusts stored initial/barrier prices
in instrument_underlying so they match yfinance's split-adjusted price world.
"""
from __future__ import annotations

from datetime import date

import yfinance as yf
from sqlalchemy import select
from sqlalchemy.orm import Session

from structured_instruments.models.instrument import InstrumentUnderlying
from structured_instruments.models.underlying import Underlying


def get_splits_after(ticker: str, after_date: date) -> float:
    """Return the cumulative split factor for *ticker* for splits after *after_date*.

    For example, a 10:1 split returns 10.0.  If no splits occurred, returns 1.0.
    """
    t = yf.Ticker(ticker)
    splits = t.splits

    if splits.empty:
        return 1.0

    factor = 1.0
    for ts, ratio in splits.items():
        split_date = ts.date() if hasattr(ts, "date") else ts
        if split_date > after_date:
            factor *= float(ratio)

    return factor


def adjust_splits(
    session: Session,
    dry_run: bool = False,
) -> list[dict]:
    """Detect and apply split adjustments for all instrument_underlying rows.

    For each row, computes the cumulative split factor since the instrument's
    pricing_date.  If the factor differs from what's already stored, the
    initial_price, coupon_barrier_price, and downside_barrier_price are divided
    by the split factor.

    Idempotent: on first run, saves original prospectus prices to original_*
    columns; subsequent runs recompute from those originals.

    Returns a list of dicts describing what was (or would be) adjusted.
    """
    stmt = (
        select(InstrumentUnderlying)
        .join(Underlying, InstrumentUnderlying.underlying_id == Underlying.id)
    )
    rows: list[InstrumentUnderlying] = list(session.execute(stmt).scalars().all())

    adjustments: list[dict] = []

    # Cache split factors per (ticker, pricing_date) to avoid redundant API calls
    split_cache: dict[tuple[str, date], float] = {}

    for iu in rows:
        ticker = iu.underlying.ticker
        pricing_date = iu.instrument.pricing_date

        cache_key = (ticker, pricing_date)
        if cache_key not in split_cache:
            split_cache[cache_key] = get_splits_after(ticker, pricing_date)

        factor = split_cache[cache_key]

        if factor == 1.0 and iu.split_adjustment_factor == 1.0:
            continue  # No split, nothing to do

        if factor == iu.split_adjustment_factor:
            continue  # Already adjusted to this factor

        # Save originals on first adjustment (original_* is NULL initially from migration seed)
        orig_initial = iu.original_initial_price or iu.initial_price
        orig_coupon = iu.original_coupon_barrier_price or iu.coupon_barrier_price
        orig_downside = iu.original_downside_barrier_price or iu.downside_barrier_price

        new_initial = orig_initial / factor
        new_coupon = orig_coupon / factor
        new_downside = orig_downside / factor

        adj = {
            "instrument_cusip": iu.instrument.cusip,
            "ticker": ticker,
            "old_factor": iu.split_adjustment_factor,
            "new_factor": factor,
            "old_initial_price": iu.initial_price,
            "new_initial_price": round(new_initial, 4),
            "old_coupon_barrier_price": iu.coupon_barrier_price,
            "new_coupon_barrier_price": round(new_coupon, 4),
            "old_downside_barrier_price": iu.downside_barrier_price,
            "new_downside_barrier_price": round(new_downside, 4),
        }
        adjustments.append(adj)

        if not dry_run:
            iu.original_initial_price = orig_initial
            iu.original_coupon_barrier_price = orig_coupon
            iu.original_downside_barrier_price = orig_downside
            iu.split_adjustment_factor = factor
            iu.initial_price = round(new_initial, 4)
            iu.coupon_barrier_price = round(new_coupon, 4)
            iu.downside_barrier_price = round(new_downside, 4)

    if not dry_run and adjustments:
        session.commit()

    return adjustments
