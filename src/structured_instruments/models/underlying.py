from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from structured_instruments.database import Base


class Underlying(Base):
    __tablename__ = "underlying"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker: Mapped[str] = mapped_column(String(10), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=True)

    prices: Mapped[list["DailyPrice"]] = relationship(back_populates="underlying")  # noqa: F821
    instrument_links: Mapped[list["InstrumentUnderlying"]] = relationship(back_populates="underlying")  # noqa: F821
