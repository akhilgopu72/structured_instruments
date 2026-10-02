"""Autocall evaluation service.

Checks whether an autocall condition is met on eligible review dates.
If ALL underlyings close >= their initial price (100%), the note is called.
"""
from __future__ import annotations

import json
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from structured_instruments.models.autocall_event import AutocallEvent
from structured_instruments.models.instrument import Instrument
from structured_instruments.models.valuation_date import ValuationDate
from structured_instruments.services.pricing import get_closing_price


def evaluate_autocall(
    session: Session,
    instrument: Instrument,
    val_date: ValuationDate,
) -> AutocallEvent | None:
    """Evaluate autocall for *instrument* on *val_date*.

    Returns ``None`` if the valuation date is not autocall-eligible.
    Otherwise returns an ``AutocallEvent`` indicating whether the note
    was called.
    """
    if not val_date.autocall_eligible:
        return None

    details: list[dict] = []

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
                "pct_of_initial": round(pct_of_initial, 6),
                "actual_price_date": str(actual_date),
            }
        )

    # Called only if ALL underlyings are at or above their initial price
    is_called = all(d["close_price"] >= d["initial_price"] for d in details)

    if is_called:
        instrument.status = "called"
        session.add(instrument)

    event = AutocallEvent(
        instrument_id=instrument.id,
        valuation_date_id=val_date.id,
        review_date=val_date.date,
        is_called=is_called,
        details_json=json.dumps(details),
    )
    session.add(event)
    session.commit()
    session.refresh(event)
    return event


def evaluate_all_pending_autocalls(
    session: Session,
    target_date: date | None = None,
) -> list[AutocallEvent]:
    """Find and evaluate all autocall-eligible valuation dates that are due
    but unevaluated.

    A valuation date is pending when:
    - Its date is <= *target_date* (defaults to today)
    - ``autocall_eligible`` is True
    - No ``AutocallEvent`` exists for that valuation_date_id
    - The parent instrument has status ``'active'``
    """
    cutoff = target_date if target_date is not None else date.today()

    already_evaluated = (
        select(AutocallEvent.valuation_date_id).scalar_subquery()
    )

    stmt = (
        select(ValuationDate)
        .join(Instrument, ValuationDate.instrument_id == Instrument.id)
        .where(
            ValuationDate.date <= cutoff,
            ValuationDate.autocall_eligible.is_(True),
            Instrument.status == "active",
            ValuationDate.id.not_in(already_evaluated),
        )
        .order_by(ValuationDate.date)
    )

    pending_dates: list[ValuationDate] = list(
        session.execute(stmt).scalars().all()
    )

    results: list[AutocallEvent] = []
    for vd in pending_dates:
        instrument = vd.instrument
        event = evaluate_autocall(session, instrument, vd)
        if event is not None:
            results.append(event)

    return results
