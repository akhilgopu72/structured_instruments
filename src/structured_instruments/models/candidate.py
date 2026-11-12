from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from structured_instruments.database import Base


class CandidateOffering(Base):
    """A note being offered (not yet bought), parsed from a preliminary
    pricing supplement. Feeds the Modeling tab and the screener."""

    __tablename__ = "candidate_offering"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cusip: Mapped[str] = mapped_column(String(9), unique=True, nullable=False)
    issuer: Mapped[str] = mapped_column(String(200), nullable=False)
    tickers: Mapped[str] = mapped_column(String(100), nullable=False)  # comma-separated
    coupon_rate_annual: Mapped[float] = mapped_column(Float, nullable=False)
    coupon_barrier_pct: Mapped[float] = mapped_column(Float, nullable=False)
    downside_barrier_pct: Mapped[float] = mapped_column(Float, nullable=False)
    autocall_barrier_pct: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    num_observations: Mapped[int] = mapped_column(Integer, nullable=False, default=24)
    first_autocall_observation: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    pricing_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    maturity_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    offering_month: Mapped[str] = mapped_column(String(7), nullable=False)  # YYYY-MM of pricing date

    source: Mapped[str] = mapped_column(String(20), nullable=False)  # gmail, upload, import
    source_ref: Mapped[str | None] = mapped_column(String(100), nullable=True)  # gmail message id
    source_filename: Mapped[str | None] = mapped_column(String(300), nullable=True)
    email_subject: Mapped[str | None] = mapped_column(String(300), nullable=True)
    received_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Disagreements between the parsed terms and the attachment filename
    # (coupon / tickers / CUSIP), for a human to check.
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    dismissed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)

    @property
    def ticker_list(self) -> list[str]:
        return [t for t in self.tickers.split(",") if t]


class ScreenRun(Base):
    """One run of the candidate screener; results stored as JSON."""

    __tablename__ = "screen_run"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running")  # running, done, error
    offering_month: Mapped[str] = mapped_column(String(7), nullable=False)
    account_ids: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    params_json: Mapped[str] = mapped_column(Text, nullable=False)
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class GmailSyncState(Base):
    """Last Gmail sync outcome, shown on the Modeling tab."""

    __tablename__ = "gmail_sync_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_added: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class GmailProcessedAttachment(Base):
    """Every attachment the sync has handled, whatever the outcome, so each
    PDF is sent to the (paid) parser at most once."""

    __tablename__ = "gmail_processed_attachment"
    __table_args__ = (UniqueConstraint("message_id", "filename", name="uq_gmail_message_file"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    message_id: Mapped[str] = mapped_column(String(100), nullable=False)
    filename: Mapped[str] = mapped_column(String(300), nullable=False)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)  # candidate, duplicate, final, error
    cusip: Mapped[str | None] = mapped_column(String(9), nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    processed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
