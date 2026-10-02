from datetime import date

from sqlalchemy import Boolean, Date, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from structured_instruments.database import Base


class CouponEvent(Base):
    __tablename__ = "coupon_event"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instrument.id"), nullable=False)
    valuation_date_id: Mapped[int] = mapped_column(ForeignKey("valuation_date.id"), nullable=False)
    evaluation_date: Mapped[date] = mapped_column(Date, nullable=False)

    is_paid: Mapped[bool] = mapped_column(Boolean, nullable=False)
    coupon_amount: Mapped[float] = mapped_column(Float, nullable=True)
    worst_performer_ticker: Mapped[str | None] = mapped_column(String(10), nullable=True)
    worst_performer_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    details_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    instrument: Mapped["Instrument"] = relationship(back_populates="coupon_events")  # noqa: F821
    valuation_date: Mapped["ValuationDate"] = relationship()  # noqa: F821
