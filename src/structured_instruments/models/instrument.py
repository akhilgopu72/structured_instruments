from datetime import date

from typing import Optional

from sqlalchemy import Date, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from structured_instruments.database import Base


class Instrument(Base):
    __tablename__ = "instrument"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cusip: Mapped[str] = mapped_column(String(9), unique=True, nullable=False)
    issuer: Mapped[str] = mapped_column(String(200), nullable=False)
    product_type: Mapped[str] = mapped_column(String(100), nullable=True)

    coupon_rate_annual: Mapped[float] = mapped_column(Float, nullable=False)
    coupon_rate_monthly: Mapped[float] = mapped_column(Float, nullable=False)
    coupon_barrier_pct: Mapped[float] = mapped_column(Float, nullable=False)  # e.g. 0.60 for 60%
    downside_barrier_pct: Mapped[float] = mapped_column(Float, nullable=False)  # e.g. 0.50 for 50%
    autocall_barrier_pct: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)  # typically 100%

    pricing_date: Mapped[date] = mapped_column(Date, nullable=False)
    maturity_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")  # active, called, matured

    underlyings: Mapped[list["InstrumentUnderlying"]] = relationship(back_populates="instrument", cascade="all, delete-orphan")
    valuation_dates: Mapped[list["ValuationDate"]] = relationship(back_populates="instrument", cascade="all, delete-orphan")  # noqa: F821
    coupon_events: Mapped[list["CouponEvent"]] = relationship(back_populates="instrument", cascade="all, delete-orphan")  # noqa: F821
    autocall_events: Mapped[list["AutocallEvent"]] = relationship(back_populates="instrument", cascade="all, delete-orphan")  # noqa: F821
    positions: Mapped[list["PortfolioPosition"]] = relationship(back_populates="instrument")  # noqa: F821


class InstrumentUnderlying(Base):
    __tablename__ = "instrument_underlying"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instrument.id"), nullable=False)
    underlying_id: Mapped[int] = mapped_column(ForeignKey("underlying.id"), nullable=False)

    initial_price: Mapped[float] = mapped_column(Float, nullable=False)
    coupon_barrier_price: Mapped[float] = mapped_column(Float, nullable=False)
    downside_barrier_price: Mapped[float] = mapped_column(Float, nullable=False)

    split_adjustment_factor: Mapped[float] = mapped_column(Float, default=1.0, server_default="1.0")
    original_initial_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    original_coupon_barrier_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    original_downside_barrier_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    instrument: Mapped["Instrument"] = relationship(back_populates="underlyings")
    underlying: Mapped["Underlying"] = relationship(back_populates="instrument_links")  # noqa: F821
