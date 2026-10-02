from datetime import date

from pydantic import BaseModel


class PerformanceMetrics(BaseModel):
    total_principal: float
    total_coupon_income: float
    total_return_pct: float
    annualized_twr: float | None = None
    xirr: float | None = None
    holding_period_days: int


class SpyComparison(BaseModel):
    portfolio_total_return_pct: float
    spy_total_return_pct: float
    alpha_pct: float
    portfolio_annualized: float | None = None
    spy_annualized: float | None = None


class ChartDataPoint(BaseModel):
    date: date
    portfolio_value: float
    spy_value: float | None = None


class TaxComparisonResponse(BaseModel):
    gross_coupon_income: float
    federal_tax_on_coupons: float
    state_tax_on_coupons: float
    net_coupon_income: float
    effective_coupon_tax_rate: float
    spy_gross_return_dollars: float
    spy_federal_tax: float
    spy_state_tax: float
    spy_net_return_dollars: float
    spy_effective_tax_rate: float
    net_advantage: float
    tax_drag_pct: float
