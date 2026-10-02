"""Performance calculation service.

Provides TWR, XIRR, and SPY comparison metrics for the portfolio.
"""
from __future__ import annotations

from datetime import date, timedelta

from scipy.optimize import brentq
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from structured_instruments.models.autocall_event import AutocallEvent
from structured_instruments.models.coupon_event import CouponEvent
from structured_instruments.models.instrument import Instrument
from structured_instruments.models.position import PortfolioPosition
from structured_instruments.models.price import DailyPrice
from structured_instruments.models.underlying import Underlying
from structured_instruments.models.valuation_date import ValuationDate
from structured_instruments.schemas.performance import (
    ChartDataPoint,
    PerformanceMetrics,
    SpyComparison,
    TaxComparisonResponse,
)


def calculate_portfolio_metrics(session: Session, account_ids: list[int]) -> PerformanceMetrics:
    """Calculate TWR, XIRR, and total return metrics for selected accounts."""
    if not account_ids:
        return PerformanceMetrics(
            total_principal=0,
            total_coupon_income=0,
            total_return_pct=0,
            annualized_twr=None,
            xirr=None,
            holding_period_days=0,
        )

    # Load every position for the selected accounts (active, called, matured).
    # Called positions had their principal returned, but their realized coupons
    # are still real income — they need to count toward total income, and their
    # capital needs to count toward principal-years for the period it was at risk.
    stmt = (
        select(PortfolioPosition)
        .join(Instrument)
        .where(PortfolioPosition.account_id.in_(account_ids))
    )
    positions = list(session.execute(stmt).scalars().all())

    today = date.today()

    if not positions:
        return PerformanceMetrics(
            total_principal=0,
            total_coupon_income=0,
            total_return_pct=0,
            annualized_twr=None,
            xirr=None,
            holding_period_days=0,
        )

    # Displayed "Total Principal" = capital currently at risk (matches Dashboard).
    active_principal = sum(
        p.principal for p in positions if p.instrument.status != "called"
    )

    # Walk the active-principal timeline to find the peak (high-water mark of
    # money at risk). When a called note's principal is returned and reinvested
    # into a new note, that's the same dollars rotating — peak captures the
    # real capital deployed without double-counting the reinvestment.
    timeline_events: list[tuple[date, float]] = []
    for pos in positions:
        timeline_events.append((pos.purchase_date, pos.principal))
        inst = pos.instrument
        if inst.status == "called":
            call_event = next(
                (ae for ae in inst.autocall_events if ae.is_called), None
            )
            if call_event is not None:
                timeline_events.append((call_event.review_date, -pos.principal))
        elif inst.status == "matured":
            timeline_events.append((min(inst.maturity_date, today), -pos.principal))
    timeline_events.sort(key=lambda x: x[0])
    running = 0.0
    peak_principal = 0.0
    for _, delta in timeline_events:
        running += delta
        peak_principal = max(peak_principal, running)

    # Income and principal-years (dollar-years at risk) summed across every
    # position. Called positions contribute for their pre-call window;
    # reinvestment positions contribute for their post-purchase window.
    principal_years = 0.0
    total_coupon_income = 0.0
    for pos in positions:
        inst = pos.instrument

        paid_count_stmt = select(func.count()).where(
            CouponEvent.instrument_id == inst.id,
            CouponEvent.is_paid.is_(True),
        )
        paid_count = session.execute(paid_count_stmt).scalar_one()
        total_coupon_income += paid_count * pos.principal * inst.coupon_rate_monthly

        if inst.status == "called":
            call_event = next(
                (ae for ae in inst.autocall_events if ae.is_called), None
            )
            exit_date = call_event.review_date if call_event is not None else today
        elif inst.status == "matured":
            exit_date = min(inst.maturity_date, today)
        else:
            exit_date = today
        days_at_risk = max((exit_date - pos.purchase_date).days, 0)
        principal_years += pos.principal * (days_at_risk / 365.25)

    if peak_principal == 0:
        return PerformanceMetrics(
            total_principal=0,
            total_coupon_income=round(total_coupon_income, 2),
            total_return_pct=0,
            annualized_twr=None,
            xirr=None,
            holding_period_days=0,
        )

    total_return = total_coupon_income / peak_principal

    # Effective years of full deployment at peak. principal_years / peak_principal
    # answers: "if my peak capital had been deployed continuously, for how many
    # years would it have accumulated the same dollar-years of exposure?" That's
    # the right T for annualizing this cumulative return.
    effective_years = principal_years / peak_principal

    annualized_twr = None
    if effective_years > 0:
        annualized_twr = (1 + total_return) ** (1 / effective_years) - 1

    xirr = _calculate_xirr(session, positions, today)

    # Display the longest holding span (earliest purchase → today). The
    # annualization uses weighted_avg_years internally, not this value.
    earliest_purchase = min(p.purchase_date for p in positions)
    holding_period_days = (today - earliest_purchase).days

    return PerformanceMetrics(
        total_principal=active_principal,
        total_coupon_income=round(total_coupon_income, 2),
        total_return_pct=round(total_return * 100, 4),
        annualized_twr=round(annualized_twr * 100, 4) if annualized_twr is not None else None,
        xirr=round(xirr * 100, 4) if xirr is not None else None,
        holding_period_days=holding_period_days,
    )


def _calculate_xirr(
    session: Session,
    positions: list[PortfolioPosition],
    today: date,
) -> float | None:
    """Calculate XIRR using scipy's brentq solver."""
    if not positions:
        return None

    cash_flows: list[tuple[date, float]] = []

    for pos in positions:
        instrument = pos.instrument

        # Initial outflow
        cash_flows.append((pos.purchase_date, -pos.principal))

        # Coupon inflows from paid coupon events
        coupon_stmt = (
            select(CouponEvent)
            .join(ValuationDate)
            .where(
                CouponEvent.instrument_id == instrument.id,
                CouponEvent.is_paid.is_(True),
            )
        )
        coupons = list(session.execute(coupon_stmt).scalars().all())
        coupon_amount = pos.principal * instrument.coupon_rate_monthly
        for ce in coupons:
            cash_flows.append((ce.valuation_date.date, coupon_amount))

        # Terminal cash flow: current value (active), returned principal (called), or
        # principal at maturity (matured). Without this, redeemed positions show no
        # inflow and XIRR collapses to a large negative rate.
        if instrument.status == "active":
            cash_flows.append((today, pos.principal))
        elif instrument.status == "called":
            called_event = next(
                (ae for ae in instrument.autocall_events if ae.is_called),
                None,
            )
            if called_event is not None:
                cash_flows.append((called_event.review_date, pos.principal))
        elif instrument.status == "matured":
            cash_flows.append((instrument.maturity_date, pos.principal))

    if len(cash_flows) < 2:
        return None

    # Sort by date
    cash_flows.sort(key=lambda x: x[0])

    # Reference date for XIRR calculation
    ref_date = cash_flows[0][0]

    def xirr_func(rate: float) -> float:
        return sum(
            cf / (1 + rate) ** ((d - ref_date).days / 365.25)
            for d, cf in cash_flows
        )

    try:
        result = brentq(xirr_func, -0.99, 10.0, maxiter=1000)
        return float(result)
    except (ValueError, RuntimeError):
        return None


def _get_spy_prices(session: Session, start_date: date, end_date: date) -> dict[date, float]:
    """Return a dict of date -> adjusted close price for SPY.

    Fetches directly from yfinance with auto_adjust=True to ensure
    dividend-adjusted prices are always current, then falls back to DB
    if the download fails.
    """
    import yfinance as yf

    # Fetch fresh adjusted prices from yfinance
    try:
        df = yf.download(
            "SPY",
            start=start_date - timedelta(days=10),
            end=end_date + timedelta(days=1),
            progress=False,
        )
        if not df.empty:
            if hasattr(df.columns, "nlevels") and df.columns.nlevels > 1:
                df.columns = df.columns.droplevel("Ticker")
            result: dict[date, float] = {}
            for ts, row in df.iterrows():
                d = ts.date() if hasattr(ts, "date") else ts
                result[d] = float(row["Close"])
            return result
    except Exception:
        pass

    # Fallback: use DB prices (may have stale dividend adjustments)
    spy_stmt = select(Underlying).where(Underlying.ticker == "SPY")
    spy = session.execute(spy_stmt).scalar_one_or_none()
    if spy is None:
        return {}
    price_stmt = (
        select(DailyPrice)
        .where(
            DailyPrice.underlying_id == spy.id,
            DailyPrice.date >= start_date - timedelta(days=10),
            DailyPrice.date <= end_date,
        )
        .order_by(DailyPrice.date)
    )
    prices = list(session.execute(price_stmt).scalars().all())
    return {p.date: p.close for p in prices}


def _get_spy_raw_prices(start_date: date, end_date: date) -> dict[date, float]:
    """Return a dict of date -> raw (unadjusted) close price for SPY.

    Used to separate price-only returns from dividend returns in tax calculations.
    """
    import yfinance as yf

    try:
        df = yf.download(
            "SPY",
            start=start_date - timedelta(days=10),
            end=end_date + timedelta(days=1),
            progress=False,
            auto_adjust=False,
        )
        if not df.empty:
            if hasattr(df.columns, "nlevels") and df.columns.nlevels > 1:
                df.columns = df.columns.droplevel("Ticker")
            result: dict[date, float] = {}
            for ts, row in df.iterrows():
                d = ts.date() if hasattr(ts, "date") else ts
                result[d] = float(row["Close"])
            return result
    except Exception:
        pass
    return {}


def _get_spy_price_on_date(spy_prices: dict[date, float], target: date) -> float | None:
    """Find the SPY price on or just before target date."""
    best = None
    for d, price in sorted(spy_prices.items()):
        if d <= target:
            best = price
        else:
            break
    return best


def calculate_spy_comparison(session: Session, account_ids: list[int]) -> SpyComparison:
    """Compare portfolio return vs. SPY return over the same period."""
    metrics = calculate_portfolio_metrics(session, account_ids)

    if not account_ids:
        return SpyComparison(
            portfolio_total_return_pct=metrics.total_return_pct,
            spy_total_return_pct=0.0,
            alpha_pct=metrics.total_return_pct,
            portfolio_annualized=metrics.annualized_twr,
            spy_annualized=None,
        )

    # Include every position the user has held. For called notes, the SPY
    # "twin" is sold on the call date — the same way the user got their
    # principal back — so SPY return is measured over the actual dollar-years
    # at risk, matching the portfolio metric.
    stmt = (
        select(PortfolioPosition)
        .join(Instrument)
        .where(PortfolioPosition.account_id.in_(account_ids))
    )
    positions = list(session.execute(stmt).scalars().all())

    if not positions:
        return SpyComparison(
            portfolio_total_return_pct=metrics.total_return_pct,
            spy_total_return_pct=0.0,
            alpha_pct=metrics.total_return_pct,
            portfolio_annualized=metrics.annualized_twr,
            spy_annualized=None,
        )

    earliest_purchase = min(p.purchase_date for p in positions)
    today = date.today()
    spy_prices = _get_spy_prices(session, earliest_purchase, today)

    if not spy_prices:
        return SpyComparison(
            portfolio_total_return_pct=metrics.total_return_pct,
            spy_total_return_pct=0.0,
            alpha_pct=metrics.total_return_pct,
            portfolio_annualized=metrics.annualized_twr,
            spy_annualized=None,
        )

    current_spy_price = _get_spy_price_on_date(spy_prices, today)
    if current_spy_price is None:
        return SpyComparison(
            portfolio_total_return_pct=metrics.total_return_pct,
            spy_total_return_pct=0.0,
            alpha_pct=metrics.total_return_pct,
            portfolio_annualized=metrics.annualized_twr,
            spy_annualized=None,
        )

    # Build the same active-principal timeline as the portfolio side so the
    # SPY return % uses the same peak-capital denominator. The SPY twin's
    # lifecycle mirrors each position's, so its peak equals peak_principal.
    timeline_events: list[tuple[date, float]] = []
    for pos in positions:
        timeline_events.append((pos.purchase_date, pos.principal))
        inst = pos.instrument
        if inst.status == "called":
            ce = next((ae for ae in inst.autocall_events if ae.is_called), None)
            if ce is not None:
                timeline_events.append((ce.review_date, -pos.principal))
        elif inst.status == "matured":
            timeline_events.append((min(inst.maturity_date, today), -pos.principal))
    timeline_events.sort(key=lambda x: x[0])
    running = 0.0
    peak_principal = 0.0
    for _, delta in timeline_events:
        running += delta
        peak_principal = max(peak_principal, running)

    spy_gain_dollars = 0.0
    spy_principal_years = 0.0
    for pos in positions:
        inst = pos.instrument
        buy_price = _get_spy_price_on_date(spy_prices, pos.purchase_date)
        if not buy_price or buy_price <= 0:
            continue
        shares = pos.principal / buy_price

        if inst.status == "called":
            call_event = next(
                (ae for ae in inst.autocall_events if ae.is_called), None
            )
            exit_date = call_event.review_date if call_event is not None else today
            exit_price = _get_spy_price_on_date(spy_prices, exit_date) or current_spy_price
        elif inst.status == "matured":
            exit_date = min(inst.maturity_date, today)
            exit_price = _get_spy_price_on_date(spy_prices, exit_date) or current_spy_price
        else:
            exit_date = today
            exit_price = current_spy_price

        spy_gain_dollars += shares * exit_price - pos.principal
        days_at_risk = max((exit_date - pos.purchase_date).days, 0)
        spy_principal_years += pos.principal * (days_at_risk / 365.25)

    if peak_principal == 0:
        return SpyComparison(
            portfolio_total_return_pct=metrics.total_return_pct,
            spy_total_return_pct=0.0,
            alpha_pct=metrics.total_return_pct,
            portfolio_annualized=metrics.annualized_twr,
            spy_annualized=None,
        )

    spy_return = spy_gain_dollars / peak_principal
    spy_return_pct = round(spy_return * 100, 4)

    # Annualize against effective years of full deployment at peak — same
    # construction as the portfolio side, so the comparison is apples-to-apples.
    effective_years = spy_principal_years / peak_principal
    spy_annualized = None
    if effective_years > 0:
        spy_annualized = round(
            ((1 + spy_return) ** (1 / effective_years) - 1) * 100, 4
        )

    alpha_pct = round(metrics.total_return_pct - spy_return_pct, 4)

    return SpyComparison(
        portfolio_total_return_pct=metrics.total_return_pct,
        spy_total_return_pct=spy_return_pct,
        alpha_pct=alpha_pct,
        portfolio_annualized=metrics.annualized_twr,
        spy_annualized=spy_annualized,
    )


def get_chart_data(session: Session, account_ids: list[int]) -> list[ChartDataPoint]:
    """Generate time series data for portfolio value vs SPY value chart.

    Called positions are included for their active window (purchase_date →
    call_date) so the chart shows the historical capital dip when a note is
    redeemed. After call_date, both the position's principal and its SPY twin
    shares are removed from the running totals — mirroring the user receiving
    their principal back and "selling" the equivalent SPY exposure.
    """
    if not account_ids:
        return []

    stmt = (
        select(PortfolioPosition)
        .join(Instrument)
        .where(PortfolioPosition.account_id.in_(account_ids))
    )
    positions = list(session.execute(stmt).scalars().all())

    if not positions:
        return []

    earliest_purchase = min(p.purchase_date for p in positions)
    today = date.today()

    # Get SPY prices
    spy_prices = _get_spy_prices(session, earliest_purchase, today)

    # Build per-position records: principal, purchase date, call date (if any),
    # SPY shares purchased on entry. When a note is called, both the principal
    # and its SPY lot drop out of the portfolio on the call date.
    position_records: list[dict] = []
    for pos in positions:
        inst = pos.instrument
        call_date: date | None = None
        if inst.status == "called":
            ae_stmt = (
                select(AutocallEvent.review_date)
                .where(
                    AutocallEvent.instrument_id == inst.id,
                    AutocallEvent.is_called.is_(True),
                )
                .order_by(AutocallEvent.review_date)
                .limit(1)
            )
            row = session.execute(ae_stmt).first()
            if row is not None:
                call_date = row[0]

        buy_price = _get_spy_price_on_date(spy_prices, pos.purchase_date)
        spy_shares = pos.principal / buy_price if buy_price and buy_price > 0 else 0.0

        position_records.append(
            {
                "purchase_date": pos.purchase_date,
                "principal": pos.principal,
                "call_date": call_date,
                "spy_shares": spy_shares,
            }
        )

    # Build cumulative paid-coupon schedule from paid coupon events. Called
    # positions' coupons are included — they're realized cash income, and the
    # metric cards now count them too.
    coupon_events_raw: list[tuple[date, float]] = []
    for pos in positions:
        inst = pos.instrument
        coupon_amount = pos.principal * inst.coupon_rate_monthly
        ce_stmt = (
            select(ValuationDate.date)
            .join(CouponEvent, CouponEvent.valuation_date_id == ValuationDate.id)
            .where(
                CouponEvent.instrument_id == inst.id,
                CouponEvent.is_paid.is_(True),
            )
            .order_by(ValuationDate.date)
        )
        for (val_date,) in session.execute(ce_stmt).all():
            coupon_events_raw.append((val_date, coupon_amount))

    coupon_events_raw.sort(key=lambda x: x[0])
    coupon_schedule: list[tuple[date, float]] = []
    cumulative = 0.0
    for val_date, amount in coupon_events_raw:
        cumulative += amount
        coupon_schedule.append((val_date, cumulative))

    # Generate one point per day
    chart_data: list[ChartDataPoint] = []
    current_date = earliest_purchase
    coupon_idx = 0
    cumulative_income = 0.0
    last_spy_price: float | None = None

    while current_date <= today:
        # Active positions: purchased on/before today, not yet called
        active_principal = 0.0
        active_spy_shares = 0.0
        for pr in position_records:
            if pr["purchase_date"] > current_date:
                continue
            if pr["call_date"] is not None and pr["call_date"] <= current_date:
                continue
            active_principal += pr["principal"]
            active_spy_shares += pr["spy_shares"]

        # Update cumulative coupon income (step function)
        while coupon_idx < len(coupon_schedule) and coupon_schedule[coupon_idx][0] <= current_date:
            cumulative_income = coupon_schedule[coupon_idx][1]
            coupon_idx += 1

        portfolio_value = active_principal + cumulative_income

        # SPY value: active shares at current price
        spy_value: float | None = None
        if current_date in spy_prices:
            last_spy_price = spy_prices[current_date]
        if last_spy_price is not None and active_spy_shares > 0:
            spy_value = round(active_spy_shares * last_spy_price, 2)

        chart_data.append(
            ChartDataPoint(
                date=current_date,
                portfolio_value=round(portfolio_value, 2),
                spy_value=spy_value,
            )
        )

        current_date += timedelta(days=1)

    return chart_data


def calculate_tax_comparison(
    session: Session,
    account_ids: list[int],
    ordinary_rate: float = 0.37,
    ltcg_rate: float = 0.20,
    state_rate: float = 0.0,
    spy_tax_treatment: str = "auto",
) -> TaxComparisonResponse:
    """Compare after-tax returns: portfolio coupons (ordinary income) vs SPY (capital gains)."""
    metrics = calculate_portfolio_metrics(session, account_ids)
    spy_data = calculate_spy_comparison(session, account_ids)

    # -- Portfolio (coupon) tax --
    gross_coupon_income = metrics.total_coupon_income
    federal_tax_on_coupons = gross_coupon_income * ordinary_rate
    state_tax_on_coupons = gross_coupon_income * state_rate
    net_coupon_income = gross_coupon_income - federal_tax_on_coupons - state_tax_on_coupons
    effective_coupon_tax_rate = (
        (federal_tax_on_coupons + state_tax_on_coupons) / gross_coupon_income
        if gross_coupon_income > 0
        else 0.0
    )

    # -- SPY tax (staggered investments) --
    holding_days = metrics.holding_period_days

    # Compute SPY gross return using staggered share purchases across every
    # position the user has held. Called notes' SPY twins are "sold" on the
    # call date — matching the principal-return event in real life — so the
    # SPY tax comparison aligns with how the portfolio metric is computed.
    stmt = (
        select(PortfolioPosition)
        .join(Instrument)
        .where(PortfolioPosition.account_id.in_(account_ids))
    )
    positions = list(session.execute(stmt).scalars().all())
    today = date.today()
    earliest_purchase = min(p.purchase_date for p in positions) if positions else today
    spy_prices = _get_spy_prices(session, earliest_purchase, today)

    # Use adjusted close for total return (includes dividends)
    total_spy_cost = 0.0
    total_spy_adj_value = 0.0
    current_spy_adj_price = _get_spy_price_on_date(spy_prices, today)

    # Also fetch raw (unadjusted) prices to separate price gain from dividends
    raw_spy_prices = _get_spy_raw_prices(earliest_purchase, today)
    current_spy_raw_price = _get_spy_price_on_date(raw_spy_prices, today) if raw_spy_prices else None

    total_spy_raw_value = 0.0
    for pos in positions:
        inst = pos.instrument
        buy_adj_price = _get_spy_price_on_date(spy_prices, pos.purchase_date)
        if not (buy_adj_price and buy_adj_price > 0 and current_spy_adj_price):
            continue

        if inst.status == "called":
            call_event = next(
                (ae for ae in inst.autocall_events if ae.is_called), None
            )
            exit_date = call_event.review_date if call_event is not None else today
            exit_adj_price = _get_spy_price_on_date(spy_prices, exit_date) or current_spy_adj_price
        elif inst.status == "matured":
            exit_date = min(inst.maturity_date, today)
            exit_adj_price = _get_spy_price_on_date(spy_prices, exit_date) or current_spy_adj_price
        else:
            exit_date = today
            exit_adj_price = current_spy_adj_price

        shares = pos.principal / buy_adj_price
        total_spy_cost += pos.principal
        total_spy_adj_value += shares * exit_adj_price

        if raw_spy_prices and current_spy_raw_price:
            buy_raw_price = _get_spy_price_on_date(raw_spy_prices, pos.purchase_date)
            if buy_raw_price and buy_raw_price > 0:
                exit_raw_price = (
                    _get_spy_price_on_date(raw_spy_prices, exit_date)
                    or current_spy_raw_price
                )
                raw_shares = pos.principal / buy_raw_price
                total_spy_raw_value += raw_shares * exit_raw_price

    # Total return from adjusted prices (includes dividends)
    spy_gross_return_dollars = total_spy_adj_value - total_spy_cost
    # Price-only return from raw prices
    spy_price_return_dollars = total_spy_raw_value - total_spy_cost if raw_spy_prices else spy_gross_return_dollars
    # Dividend income = total return - price return
    spy_dividend_dollars = max(spy_gross_return_dollars - spy_price_return_dollars, 0.0)

    # Determine capital gains rate based on holding period or explicit treatment
    if spy_tax_treatment == "income":
        gains_rate = ordinary_rate
    elif spy_tax_treatment == "ltcg":
        gains_rate = ltcg_rate
    else:  # auto
        gains_rate = ltcg_rate if holding_days > 365 else ordinary_rate

    # Price appreciation taxed at capital gains rate (negative = tax loss harvesting benefit)
    spy_price_tax = spy_price_return_dollars * gains_rate
    # Dividends taxed at qualified dividend rate (same as ltcg)
    spy_dividend_tax = spy_dividend_dollars * ltcg_rate
    spy_federal_tax = spy_price_tax + spy_dividend_tax

    spy_state_tax = spy_gross_return_dollars * state_rate
    spy_net_return_dollars = spy_gross_return_dollars - spy_federal_tax - spy_state_tax
    spy_effective_tax_rate = (
        (spy_federal_tax + spy_state_tax) / spy_gross_return_dollars
        if spy_gross_return_dollars > 0
        else 0.0
    )

    # -- Comparison --
    net_advantage = net_coupon_income - spy_net_return_dollars
    tax_drag_pct = effective_coupon_tax_rate - spy_effective_tax_rate

    return TaxComparisonResponse(
        gross_coupon_income=round(gross_coupon_income, 2),
        federal_tax_on_coupons=round(federal_tax_on_coupons, 2),
        state_tax_on_coupons=round(state_tax_on_coupons, 2),
        net_coupon_income=round(net_coupon_income, 2),
        effective_coupon_tax_rate=round(effective_coupon_tax_rate, 4),
        spy_gross_return_dollars=round(spy_gross_return_dollars, 2),
        spy_federal_tax=round(spy_federal_tax, 2),
        spy_state_tax=round(spy_state_tax, 2),
        spy_net_return_dollars=round(spy_net_return_dollars, 2),
        spy_effective_tax_rate=round(spy_effective_tax_rate, 4),
        net_advantage=round(net_advantage, 2),
        tax_drag_pct=round(tax_drag_pct, 4),
    )
