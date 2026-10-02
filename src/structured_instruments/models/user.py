from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from structured_instruments.database import Base


class User(Base):
    __tablename__ = "user"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)

    positions: Mapped[list["PortfolioPosition"]] = relationship(back_populates="user")  # noqa: F821
    accounts: Mapped[list["Account"]] = relationship(back_populates="user")  # noqa: F821
