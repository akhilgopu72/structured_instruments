"""Pricing service - fetch and store OHLCV data via yfinance."""
from __future__ import annotations

from datetime import date, timedelta

import yfinance as yf
from sqlalchemy import select
from sqlalchemy.orm import Session

from structured_instruments.models.instrument import InstrumentUnderlying
from structured_instruments.models.price import DailyPrice
from structured_instruments.models.underlying import Underlying


def ensure_spy_exists(session: Session) -> Underlying:
    """Return the SPY underlying row, creating it if it does not exist."""
    stmt = select(Underlying).where(Underlying.ticker == "SPY")
    spy = session.execute(stmt).scalar_one_or_none()
    if spy is None:
        spy = Underlying(ticker="SPY", name="SPDR S&P 500 ETF Trust")
        session.add(spy)
        session.commit()
        session.refresh(spy)
    return spy


def _get_or_create_underlying(session: Session, ticker: str) -> Underlying:
    """Return the Underlying for *ticker*, creating it if needed."""
    stmt = select(Underlying).where(Underlying.ticker == ticker)
    und = session.execute(stmt).scalar_one_or_none()
    if und is None:
        und = Underlying(ticker=ticker, name=ticker)
        session.add(und)
        session.commit()
        session.refresh(und)
    return und


def fetch_prices(
    session: Session,
    ticker: str,
    start_date: date,
    end_date: date,
    update_existing: bool = False,
) -> int:
    """Download OHLCV data for *ticker* between *start_date* and *end_date* (inclusive).

    Uses upsert logic: rows that already exist (same underlying_id + date) are
    skipped by default.  When *update_existing* is True, existing rows are
    updated with fresh data (useful after a stock split when stored prices are stale).

    Returns the number of rows inserted or updated.
    """
    und = _get_or_create_underlying(session, ticker)

    # yfinance end is exclusive, so add one day
    df = yf.download(ticker, start=start_date, end=end_date + timedelta(days=1), progress=False)

    if df.empty:
        return 0

    # If yfinance returns MultiIndex columns (e.g. when a single ticker is
    # passed but the result still has a ticker level), flatten them.
    if hasattr(df.columns, "nlevels") and df.columns.nlevels > 1:
        df.columns = df.columns.droplevel("Ticker")
        # Remove duplicate columns that may arise after droplevel
        df = df.loc[:, ~df.columns.duplicated()]

    count = 0
    for ts, row in df.iterrows():
        price_date = ts.date() if hasattr(ts, "date") else ts

        def _scalar(val):
            """Extract a Python scalar, handling Series/array edge cases."""
            import pandas as pd
            if isinstance(val, pd.Series):
                val = val.iloc[0]
            return None if pd.isna(val) else float(val)

        close_val = _scalar(row["Close"])
        if close_val is None:
            continue  # skip rows with no close price

        # Check if this date already exists
        exists_stmt = select(DailyPrice).where(
            DailyPrice.underlying_id == und.id,
            DailyPrice.date == price_date,
        )
        existing = session.execute(exists_stmt).scalar_one_or_none()

        if existing is not None:
            if not update_existing:
                continue
            # Update existing row with fresh split-adjusted data
            existing.open = _scalar(row["Open"])
            existing.high = _scalar(row["High"])
            existing.low = _scalar(row["Low"])
            existing.close = close_val
            existing.volume = int(_scalar(row["Volume"])) if _scalar(row["Volume"]) is not None else None
            count += 1
        else:
            dp = DailyPrice(
                underlying_id=und.id,
                date=price_date,
                open=_scalar(row["Open"]),
                high=_scalar(row["High"]),
                low=_scalar(row["Low"]),
                close=close_val,
                volume=int(_scalar(row["Volume"])) if _scalar(row["Volume"]) is not None else None,
            )
            session.add(dp)
            count += 1

    session.commit()
    return count


def fetch_all_active(session: Session, days: int = 5) -> dict[str, int]:
    """Fetch prices for the last *days* calendar days for every active ticker.

    Active tickers are the distinct underlyings referenced by
    ``InstrumentUnderlying`` plus SPY (always included).

    Returns a dict mapping ticker -> number of rows inserted.
    """
    ensure_spy_exists(session)

    # Gather unique underlying ids from instrument links
    stmt = select(InstrumentUnderlying.underlying_id).distinct()
    linked_ids: list[int] = list(session.execute(stmt).scalars().all())

    # Resolve to Underlying objects
    tickers: set[str] = {"SPY"}
    if linked_ids:
        und_stmt = select(Underlying).where(Underlying.id.in_(linked_ids))
        for und in session.execute(und_stmt).scalars().all():
            tickers.add(und.ticker)

    end_date = date.today()
    start_date = end_date - timedelta(days=days)

    results: dict[str, int] = {}
    for ticker in sorted(tickers):
        count = fetch_prices(session, ticker, start_date, end_date)
        results[ticker] = count

    return results


def get_closing_price(
    session: Session,
    underlying_id: int,
    target_date: date,
) -> tuple[date, float]:
    """Return ``(actual_date, close_price)`` for the most recent trading day
    on or before *target_date*.

    If no price is found within 5 business days before *target_date*, a
    ``ValueError`` is raised.
    """
    # 5 business days ~ 9 calendar days (generous buffer for holidays)
    lookback = target_date - timedelta(days=9)

    stmt = (
        select(DailyPrice)
        .where(
            DailyPrice.underlying_id == underlying_id,
            DailyPrice.date <= target_date,
            DailyPrice.date >= lookback,
        )
        .order_by(DailyPrice.date.desc())
        .limit(1)
    )
    price = session.execute(stmt).scalar_one_or_none()

    if price is None:
        raise ValueError(
            f"No price found for underlying_id={underlying_id} within 5 business "
            f"days of {target_date}"
        )

    return price.date, float(price.close)
