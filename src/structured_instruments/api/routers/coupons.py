"""Coupons API router."""
from __future__ import annotations

import json
from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from structured_instruments.api.dependencies import get_db, get_account_filter
from structured_instruments.models.coupon_event import CouponEvent
from structured_instruments.models.instrument import Instrument
from structured_instruments.models.position import PortfolioPosition
from structured_instruments.models.valuation_date import ValuationDate
from structured_instruments.schemas.coupon import CouponCalendarEntry, CouponUnderlyingDetail

router = APIRouter(prefix="/api/coupons", tags=["coupons"])


@router.get("/calendar", response_model=list[CouponCalendarEntry])
def get_calendar(
    account_ids: list[int] = Depends(get_account_filter),
    session: Session = Depends(get_db),
) -> list[CouponCalendarEntry]:
    """All valuation dates with status, amounts, and worst performers for selected accounts."""
    today = date.today()

    if not account_ids:
        return []

    # Get positions from selected accounts and sum principal per instrument
    pos_stmt = (
        select(PortfolioPosition)
        .where(PortfolioPosition.account_id.in_(account_ids))
    )
    positions = list(session.execute(pos_stmt).scalars().all())
    user_instrument_ids = list({p.instrument_id for p in positions})
    # Sum principal per instrument across selected accounts
    principal_by_inst: dict[int, float] = {}
    for p in positions:
        principal_by_inst[p.instrument_id] = principal_by_inst.get(p.instrument_id, 0) + p.principal

    if not user_instrument_ids:
        return []

    # Get valuation dates for these instruments
    stmt = (
        select(ValuationDate)
        .join(Instrument)
        .where(ValuationDate.instrument_id.in_(user_instrument_ids))
        .order_by(ValuationDate.date)
    )
    val_dates = list(session.execute(stmt).scalars().all())

    results: list[CouponCalendarEntry] = []
    for vd in val_dates:
        inst = vd.instrument

        # Check if there's a coupon event for this valuation date
        ce_stmt = select(CouponEvent).where(
            CouponEvent.valuation_date_id == vd.id
        )
        ce = session.execute(ce_stmt).scalar_one_or_none()

        if ce is not None:
            status = "paid" if ce.is_paid else "missed"
            # Compute coupon amount using summed principal across accounts
            principal = principal_by_inst.get(inst.id, 0)
            coupon_amount = principal * inst.coupon_rate_monthly
            worst_ticker = ce.worst_performer_ticker
            worst_pct = ce.worst_performer_pct

            # Parse details_json into structured list
            details: list[CouponUnderlyingDetail] | None = None
            if ce.details_json:
                try:
                    raw = json.loads(ce.details_json)
                    details = [CouponUnderlyingDetail(**item) for item in raw]
                except (json.JSONDecodeError, TypeError, KeyError):
                    details = None
        elif vd.date > today:
            status = "upcoming"
            principal = principal_by_inst.get(inst.id, 0)
            coupon_amount = principal * inst.coupon_rate_monthly
            worst_ticker = None
            worst_pct = None
            details = None
        else:
            # Past date but not yet evaluated
            status = "pending"
            coupon_amount = None
            worst_ticker = None
            worst_pct = None
            details = None

        results.append(
            CouponCalendarEntry(
                cusip=inst.cusip,
                issuer=inst.issuer,
                date=vd.date,
                sequence_number=vd.sequence_number,
                status=status,
                coupon_amount=round(coupon_amount, 2) if coupon_amount is not None else None,
                worst_performer_ticker=worst_ticker,
                worst_performer_pct=worst_pct,
                details=details,
            )
        )

    return results
