"""Instruments API router."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from structured_instruments.api.dependencies import get_db, get_account_filter
from structured_instruments.models.autocall_event import AutocallEvent
from structured_instruments.models.coupon_event import CouponEvent
from structured_instruments.models.instrument import Instrument, InstrumentUnderlying
from structured_instruments.models.position import PortfolioPosition
from structured_instruments.models.price import DailyPrice
from structured_instruments.models.valuation_date import ValuationDate
from structured_instruments.schemas.instrument import (
    InstrumentDetail,
    InstrumentSummary,
    UnderlyingStatus,
)

router = APIRouter(prefix="/api/instruments", tags=["instruments"])


@router.get("/", response_model=list[InstrumentSummary])
def list_instruments(
    account_ids: list[int] = Depends(get_account_filter),
    session: Session = Depends(get_db),
) -> list[InstrumentSummary]:
    """List instruments where the user has a position in the selected accounts."""
    if not account_ids:
        return []

    stmt = (
        select(Instrument)
        .join(PortfolioPosition)
        .where(PortfolioPosition.account_id.in_(account_ids))
        .distinct()
        .order_by(Instrument.pricing_date.desc())
    )
    instruments = list(session.execute(stmt).scalars().all())

    results: list[InstrumentSummary] = []
    for inst in instruments:
        # Count paid and missed coupons
        paid_stmt = select(func.count()).where(
            CouponEvent.instrument_id == inst.id,
            CouponEvent.is_paid.is_(True),
        )
        coupons_received = session.execute(paid_stmt).scalar_one()

        missed_stmt = select(func.count()).where(
            CouponEvent.instrument_id == inst.id,
            CouponEvent.is_paid.is_(False),
        )
        coupons_missed = session.execute(missed_stmt).scalar_one()

        # Sum principal across selected accounts for this instrument
        pos_stmt = select(PortfolioPosition).where(
            PortfolioPosition.instrument_id == inst.id,
            PortfolioPosition.account_id.in_(account_ids),
        )
        positions = list(session.execute(pos_stmt).scalars().all())
        principal = sum(p.principal for p in positions) if positions else None

        # Compute total coupon income: paid events * each position's principal * rate
        total_coupon_income = 0.0
        for pos in positions:
            total_coupon_income += coupons_received * pos.principal * inst.coupon_rate_monthly

        # Call date: review date of the autocall event that called the note (if any)
        call_date = None
        if inst.status == "called":
            call_date_stmt = (
                select(AutocallEvent.review_date)
                .where(
                    AutocallEvent.instrument_id == inst.id,
                    AutocallEvent.is_called.is_(True),
                )
                .order_by(AutocallEvent.review_date)
                .limit(1)
            )
            call_date = session.execute(call_date_stmt).scalar_one_or_none()

        results.append(
            InstrumentSummary(
                cusip=inst.cusip,
                issuer=inst.issuer,
                product_type=inst.product_type,
                coupon_rate_annual=inst.coupon_rate_annual,
                coupon_barrier_pct=inst.coupon_barrier_pct,
                downside_barrier_pct=inst.downside_barrier_pct,
                pricing_date=inst.pricing_date,
                maturity_date=inst.maturity_date,
                status=inst.status,
                principal=principal,
                coupons_received=coupons_received,
                coupons_missed=coupons_missed,
                total_coupon_income=round(total_coupon_income, 2),
                call_date=call_date,
            )
        )

    return results


@router.get("/{cusip}", response_model=InstrumentDetail)
def get_instrument(
    cusip: str,
    account_ids: list[int] = Depends(get_account_filter),
    session: Session = Depends(get_db),
) -> InstrumentDetail:
    """Get full instrument detail with underlying status."""
    stmt = select(Instrument).where(Instrument.cusip == cusip)
    inst = session.execute(stmt).scalar_one_or_none()

    if inst is None:
        raise HTTPException(status_code=404, detail=f"Instrument {cusip} not found")

    # Coupon stats
    paid_stmt = select(func.count()).where(
        CouponEvent.instrument_id == inst.id,
        CouponEvent.is_paid.is_(True),
    )
    coupons_received = session.execute(paid_stmt).scalar_one()

    missed_stmt = select(func.count()).where(
        CouponEvent.instrument_id == inst.id,
        CouponEvent.is_paid.is_(False),
    )
    coupons_missed = session.execute(missed_stmt).scalar_one()

    # Sum principal across selected accounts
    pos_stmt = select(PortfolioPosition).where(
        PortfolioPosition.instrument_id == inst.id,
        PortfolioPosition.account_id.in_(account_ids),
    )
    positions = list(session.execute(pos_stmt).scalars().all())
    principal = sum(p.principal for p in positions) if positions else None

    # Compute total coupon income per-account
    total_coupon_income = 0.0
    for pos in positions:
        total_coupon_income += coupons_received * pos.principal * inst.coupon_rate_monthly

    # Next valuation date
    today = date.today()
    next_vd_stmt = (
        select(ValuationDate.date)
        .where(
            ValuationDate.instrument_id == inst.id,
            ValuationDate.date > today,
        )
        .order_by(ValuationDate.date)
        .limit(1)
    )
    next_valuation_date = session.execute(next_vd_stmt).scalar_one_or_none()

    # Call date: review date of the autocall event that called the note (if any)
    call_date = None
    if inst.status == "called":
        call_date_stmt = (
            select(AutocallEvent.review_date)
            .where(
                AutocallEvent.instrument_id == inst.id,
                AutocallEvent.is_called.is_(True),
            )
            .order_by(AutocallEvent.review_date)
            .limit(1)
        )
        call_date = session.execute(call_date_stmt).scalar_one_or_none()

    # Underlying status
    underlyings: list[UnderlyingStatus] = []
    for iu in inst.underlyings:
        und = iu.underlying
        # Latest price
        price_stmt = (
            select(DailyPrice.close)
            .where(
                DailyPrice.underlying_id == und.id,
                DailyPrice.date <= today,
            )
            .order_by(DailyPrice.date.desc())
            .limit(1)
        )
        current_price = session.execute(price_stmt).scalar_one_or_none()

        pct_of_initial = None
        above_coupon = None
        above_downside = None
        if current_price is not None:
            pct_of_initial = round(current_price / iu.initial_price, 6)
            above_coupon = current_price >= iu.coupon_barrier_price
            above_downside = current_price >= iu.downside_barrier_price

        underlyings.append(
            UnderlyingStatus(
                ticker=und.ticker,
                name=und.name,
                initial_price=iu.initial_price,
                coupon_barrier_price=iu.coupon_barrier_price,
                downside_barrier_price=iu.downside_barrier_price,
                current_price=current_price,
                pct_of_initial=pct_of_initial,
                above_coupon_barrier=above_coupon,
                above_downside_barrier=above_downside,
            )
        )

    return InstrumentDetail(
        cusip=inst.cusip,
        issuer=inst.issuer,
        product_type=inst.product_type,
        coupon_rate_annual=inst.coupon_rate_annual,
        coupon_rate_monthly=inst.coupon_rate_monthly,
        coupon_barrier_pct=inst.coupon_barrier_pct,
        downside_barrier_pct=inst.downside_barrier_pct,
        autocall_barrier_pct=inst.autocall_barrier_pct,
        pricing_date=inst.pricing_date,
        maturity_date=inst.maturity_date,
        status=inst.status,
        principal=principal,
        coupons_received=coupons_received,
        coupons_missed=coupons_missed,
        total_coupon_income=round(total_coupon_income, 2),
        call_date=call_date,
        underlyings=underlyings,
        next_valuation_date=next_valuation_date,
    )
