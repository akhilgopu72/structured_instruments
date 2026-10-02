from datetime import date

from pydantic import BaseModel


class PortfolioSummary(BaseModel):
    total_principal: float
    total_coupon_income: float
    active_instruments: int
    called_instruments: int
    upcoming_valuation_dates: list["UpcomingDate"] = []


class UpcomingDate(BaseModel):
    cusip: str
    issuer: str
    date: date
    autocall_eligible: bool
    sequence_number: int
    is_paid: bool | None = None


class BarrierStatus(BaseModel):
    cusip: str
    issuer: str
    ticker: str
    initial_price: float
    coupon_barrier_price: float
    downside_barrier_price: float
    current_price: float | None
    pct_of_initial: float | None
    distance_to_coupon_barrier_pct: float | None
    distance_to_downside_barrier_pct: float | None
