from datetime import date

from pydantic import BaseModel


class UnderlyingStatus(BaseModel):
    ticker: str
    name: str | None
    initial_price: float
    coupon_barrier_price: float
    downside_barrier_price: float
    current_price: float | None = None
    pct_of_initial: float | None = None
    above_coupon_barrier: bool | None = None
    above_downside_barrier: bool | None = None


class InstrumentSummary(BaseModel):
    cusip: str
    issuer: str
    product_type: str | None
    coupon_rate_annual: float
    coupon_barrier_pct: float
    downside_barrier_pct: float
    pricing_date: date
    maturity_date: date
    status: str
    principal: float | None = None
    coupons_received: int = 0
    coupons_missed: int = 0
    total_coupon_income: float = 0.0
    call_date: date | None = None

    model_config = {"from_attributes": True}


class InstrumentDetail(InstrumentSummary):
    coupon_rate_monthly: float
    autocall_barrier_pct: float
    underlyings: list[UnderlyingStatus] = []
    next_valuation_date: date | None = None


class ParsedInstrumentData(BaseModel):
    cusip: str
    issuer: str
    product_type: str | None = None
    coupon_rate_annual: float
    coupon_rate_monthly: float
    coupon_barrier_pct: float
    downside_barrier_pct: float
    autocall_barrier_pct: float = 1.0
    pricing_date: date
    maturity_date: date
    underlyings: list["ParsedUnderlying"]
    valuation_dates: list["ParsedValuationDate"]


class ParsedUnderlying(BaseModel):
    ticker: str
    name: str | None = None
    initial_price: float


class ParsedValuationDate(BaseModel):
    date: date
    autocall_eligible: bool = False
    sequence_number: int
