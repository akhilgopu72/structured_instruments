from datetime import date

from sqlalchemy import Date, Float, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from structured_instruments.database import Base


class PortfolioPosition(Base):
    __tablename__ = "position"
    __table_args__ = (
        UniqueConstraint("account_id", "instrument_id", name="uq_account_instrument"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False)
    account_id: Mapped[int] = mapped_column(ForeignKey("account.id"), nullable=False)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instrument.id"), nullable=False)
    principal: Mapped[float] = mapped_column(Float, nullable=False)
    num_notes: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    purchase_date: Mapped[date] = mapped_column(Date, nullable=False)

    user: Mapped["User"] = relationship(back_populates="positions")  # noqa: F821
    account: Mapped["Account"] = relationship(back_populates="positions")  # noqa: F821
    instrument: Mapped["Instrument"] = relationship(back_populates="positions")  # noqa: F821
