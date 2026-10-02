from sqlalchemy import Integer, String, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from structured_instruments.database import Base


class Account(Base):
    __tablename__ = "account"
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_user_account_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    account_type: Mapped[str] = mapped_column(String(50), nullable=False)

    user: Mapped["User"] = relationship(back_populates="accounts")  # noqa: F821
    positions: Mapped[list["PortfolioPosition"]] = relationship(back_populates="account")  # noqa: F821
