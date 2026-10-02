from datetime import date

from sqlalchemy import Boolean, Date, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from structured_instruments.database import Base


class AutocallEvent(Base):
    __tablename__ = "autocall_event"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instrument.id"), nullable=False)
    valuation_date_id: Mapped[int] = mapped_column(ForeignKey("valuation_date.id"), nullable=False)
    review_date: Mapped[date] = mapped_column(Date, nullable=False)

    is_called: Mapped[bool] = mapped_column(Boolean, nullable=False)
    details_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    instrument: Mapped["Instrument"] = relationship(back_populates="autocall_events")  # noqa: F821
    valuation_date: Mapped["ValuationDate"] = relationship()  # noqa: F821
