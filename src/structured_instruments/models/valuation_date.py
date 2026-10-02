from datetime import date

from sqlalchemy import Boolean, Date, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from structured_instruments.database import Base


class ValuationDate(Base):
    __tablename__ = "valuation_date"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instrument.id"), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    autocall_eligible: Mapped[bool] = mapped_column(Boolean, default=False)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)  # 1-24

    instrument: Mapped["Instrument"] = relationship(back_populates="valuation_dates")  # noqa: F821
