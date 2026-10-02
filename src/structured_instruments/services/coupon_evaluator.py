"""Coupon evaluation service.

Evaluates whether coupons are paid on each valuation date by checking
whether ALL underlyings closed at or above their coupon barrier price.
"""
from __future__ import annotations

import json
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from structured_instruments.models.coupon_event import CouponEvent
from structured_instruments.models.instrument import Instrument, InstrumentUnderlying
from structured_instruments.models.valuation_date import ValuationDate
from structured_instruments.services.pricing import get_closing_price


def evaluate_coupon(
    session: Session,
    instrument: Instrument,
    val_date: ValuationDate,
) -> CouponEvent:
    """Evaluate a single coupon event for *instrument* on *val_date*.

    For each underlying, look up the closing price on the valuation date.
    If ALL underlyings close >= their coupon_barrier_price the coupon is paid;
    otherwise it is missed.  The worst performer (lowest pct of initial) is
    recorded along with a JSON blob of per-ticker details.
    """
    details: list[dict] = []
    worst_ticker: str | None = None
    worst_pct: float | None = None

    for iu in instrument.underlyings:
        ticker = iu.underlying.ticker
        actual_date, close_price = get_closing_price(
            session, iu.underlying_id, val_date.date
        )
        pct_of_initial = close_price / iu.initial_price

        details.append(
            {
                "ticker": ticker,
                "underlying_id": iu.underlying_id,
                "close_price": round(close_price, 4),
                "initial_price": round(iu.initial_price, 4),
                "coupon_barrier_price": round(iu.coupon_barrier_price, 4),
                "pct_of_initial": round(pct_of_initial, 6),
                "actual_price_date": str(actual_date),
            }
        )

        if worst_pct is None or pct_of_initial < worst_pct:
            worst_pct = pct_of_initial
            worst_ticker = ticker

    # Coupon is paid only if ALL underlyings are at or above their barrier
    all_above = all(
        d["close_price"] >= d["coupon_barrier_price"] for d in details
    )

    event = CouponEvent(
        instrument_id=instrument.id,
        valuation_date_id=val_date.id,
        evaluation_date=date.today(),
        is_paid=all_above,
        coupon_amount=None,
        worst_performer_ticker=worst_ticker,
        worst_performer_pct=round(worst_pct, 6) if worst_pct is not None else None,
        details_json=json.dumps(details),
    )
    session.add(event)
    session.commit()
    session.refresh(event)
    return event


def evaluate_all_pending(
    session: Session,
    target_date: date | None = None,
) -> list[CouponEvent]:
    """Find and evaluate all valuation dates that are due but unevaluated.

    A valuation date is "pending" when:
    - Its date is <= *target_date* (defaults to today)
    - No ``CouponEvent`` exists for that valuation_date_id
    - The parent instrument has status ``'active'``
    """
    cutoff = target_date if target_date is not None else date.today()

    # Sub-query: valuation_date_ids that already have a coupon event
    already_evaluated = (
        select(CouponEvent.valuation_date_id).scalar_subquery()
    )

    stmt = (
        select(ValuationDate)
        .join(Instrument, ValuationDate.instrument_id == Instrument.id)
        .where(
            ValuationDate.date <= cutoff,
            Instrument.status == "active",
            ValuationDate.id.not_in(already_evaluated),
        )
        .order_by(ValuationDate.date)
    )

    pending_dates: list[ValuationDate] = list(
        session.execute(stmt).scalars().all()
    )

    results: list[CouponEvent] = []
    for vd in pending_dates:
        instrument = vd.instrument
        event = evaluate_coupon(session, instrument, vd)
        results.append(event)

    return results
