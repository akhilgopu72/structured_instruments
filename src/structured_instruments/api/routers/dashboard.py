"""Dashboard API router."""
from __future__ import annotations

import calendar
from datetime import date, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select, func, or_
from sqlalchemy.orm import Session

from structured_instruments.api.dependencies import get_db, get_account_filter
from structured_instruments.models.coupon_event import CouponEvent
from structured_instruments.models.instrument import Instrument, InstrumentUnderlying
from structured_instruments.models.position import PortfolioPosition
from structured_instruments.models.price import DailyPrice
from structured_instruments.models.valuation_date import ValuationDate
from structured_instruments.schemas.dashboard import (
    BarrierStatus,
    PortfolioSummary,
    UpcomingDate,
)

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=PortfolioSummary)
def get_summary(
    account_ids: list[int] = Depends(get_account_filter),
    session: Session = Depends(get_db),
) -> PortfolioSummary:
    """Portfolio totals and upcoming valuation dates for the selected accounts."""
    if not account_ids:
        return PortfolioSummary(
            total_principal=0,
            total_coupon_income=0,
            active_instruments=0,
            called_instruments=0,
            upcoming_valuation_dates=[],
        )

    # Total principal for selected accounts (excludes called instruments — that capital was returned)
    principal_stmt = (
        select(func.coalesce(func.sum(PortfolioPosition.principal), 0.0))
        .join(Instrument, PortfolioPosition.instrument_id == Instrument.id)
        .where(
            PortfolioPosition.account_id.in_(account_ids),
            Instrument.status != "called",
        )
    )
    total_principal = float(session.execute(principal_stmt).scalar_one())

    # Instrument IDs from selected accounts
    inst_id_stmt = select(PortfolioPosition.instrument_id).where(
        PortfolioPosition.account_id.in_(account_ids)
    ).distinct()
    user_instrument_ids = [
        row[0] for row in session.execute(inst_id_stmt).all()
    ]

    # Total coupon income computed from paid events * position principal * rate
    total_coupon_income = 0.0
    if user_instrument_ids:
        pos_stmt = (
            select(PortfolioPosition)
            .join(Instrument)
            .where(PortfolioPosition.account_id.in_(account_ids))
        )
        positions = list(session.execute(pos_stmt).scalars().all())
        for pos in positions:
            inst = pos.instrument
            paid_count_stmt = select(func.count()).where(
                CouponEvent.instrument_id == inst.id,
                CouponEvent.is_paid.is_(True),
            )
            paid_count = session.execute(paid_count_stmt).scalar_one()
            total_coupon_income += paid_count * pos.principal * inst.coupon_rate_monthly

    # Active / called instrument counts
    active_instruments = 0
    called_instruments = 0
    if user_instrument_ids:
        active_stmt = select(func.count()).where(
            Instrument.id.in_(user_instrument_ids),
            Instrument.status == "active",
        )
        active_instruments = session.execute(active_stmt).scalar_one()

        called_stmt = select(func.count()).where(
            Instrument.id.in_(user_instrument_ids),
            Instrument.status == "called",
        )
        called_instruments = session.execute(called_stmt).scalar_one()

    # Valuation dates for the current month (with status).
    # Include every active note's dates this month, plus any date — active or
    # called — that already has a coupon event this month. The latter keeps a
    # note that was called this month visible, since it still earned (or missed)
    # interest for the current month. Terminated notes' empty future-schedule
    # dates (no coupon event) stay hidden.
    today = date.today()
    month_start = today.replace(day=1)
    last_day = calendar.monthrange(today.year, today.month)[1]
    month_end = today.replace(day=last_day)
    upcoming_dates: list[UpcomingDate] = []
    if user_instrument_ids:
        upcoming_stmt = (
            select(ValuationDate)
            .join(Instrument)
            .outerjoin(CouponEvent, CouponEvent.valuation_date_id == ValuationDate.id)
            .where(
                ValuationDate.date >= month_start,
                ValuationDate.date <= month_end,
                ValuationDate.instrument_id.in_(user_instrument_ids),
                or_(
                    Instrument.status != "called",
                    CouponEvent.id.isnot(None),
                ),
            )
            .order_by(ValuationDate.date)
        )
        upcoming_rows = list(session.execute(upcoming_stmt).scalars().all())

        for vd in upcoming_rows:
            inst = vd.instrument
            coupon_paid = session.execute(
                select(CouponEvent.is_paid).where(
                    CouponEvent.valuation_date_id == vd.id
                )
            ).scalar_one_or_none()

            upcoming_dates.append(
                UpcomingDate(
                    cusip=inst.cusip,
                    issuer=inst.issuer,
                    date=vd.date,
                    autocall_eligible=vd.autocall_eligible,
                    sequence_number=vd.sequence_number,
                    is_paid=coupon_paid,
                )
            )

    return PortfolioSummary(
        total_principal=total_principal,
        total_coupon_income=round(total_coupon_income, 2),
        active_instruments=active_instruments,
        called_instruments=called_instruments,
        upcoming_valuation_dates=upcoming_dates,
    )


@router.get("/barrier-status", response_model=list[BarrierStatus])
def get_barrier_status(
    account_ids: list[int] = Depends(get_account_filter),
    session: Session = Depends(get_db),
) -> list[BarrierStatus]:
    """All underlyings across selected accounts' instruments with barrier distances."""
    today = date.today()

    if not account_ids:
        return []

    # Get instrument IDs from selected accounts
    inst_id_stmt = select(PortfolioPosition.instrument_id).where(
        PortfolioPosition.account_id.in_(account_ids)
    ).distinct()
    user_instrument_ids = [
        row[0] for row in session.execute(inst_id_stmt).all()
    ]

    if not user_instrument_ids:
        return []

    stmt = (
        select(InstrumentUnderlying)
        .join(Instrument)
        .where(InstrumentUnderlying.instrument_id.in_(user_instrument_ids))
        .order_by(Instrument.cusip)
    )
    ius = list(session.execute(stmt).scalars().all())

    results: list[BarrierStatus] = []
    for iu in ius:
        inst = iu.instrument
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

        pct_of_initial: float | None = None
        distance_coupon: float | None = None
        distance_downside: float | None = None

        if current_price is not None:
            pct_of_initial = round(current_price / iu.initial_price, 6)
            distance_coupon = round(
                ((current_price - iu.coupon_barrier_price) / iu.coupon_barrier_price) * 100, 4
            )
            distance_downside = round(
                ((current_price - iu.downside_barrier_price) / iu.downside_barrier_price) * 100, 4
            )

        results.append(
            BarrierStatus(
                cusip=inst.cusip,
                issuer=inst.issuer,
                ticker=und.ticker,
                initial_price=iu.initial_price,
                coupon_barrier_price=iu.coupon_barrier_price,
                downside_barrier_price=iu.downside_barrier_price,
                current_price=current_price,
                pct_of_initial=pct_of_initial,
                distance_to_coupon_barrier_pct=distance_coupon,
                distance_to_downside_barrier_pct=distance_downside,
            )
        )

    return results
