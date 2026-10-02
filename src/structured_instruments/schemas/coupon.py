from datetime import date

from pydantic import BaseModel


class CouponUnderlyingDetail(BaseModel):
    ticker: str
    close_price: float
    initial_price: float
    pct_of_initial: float
    coupon_barrier_price: float
    actual_price_date: str


class CouponCalendarEntry(BaseModel):
    cusip: str
    issuer: str
    date: date
    sequence_number: int
    status: str  # "paid", "missed", "upcoming", "pending"
    coupon_amount: float | None = None
    worst_performer_ticker: str | None = None
    worst_performer_pct: float | None = None
    details: list[CouponUnderlyingDetail] | None = None
