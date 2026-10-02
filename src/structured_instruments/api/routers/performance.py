"""Performance API router."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from structured_instruments.api.dependencies import get_db, get_account_filter
from structured_instruments.schemas.performance import (
    ChartDataPoint,
    PerformanceMetrics,
    SpyComparison,
    TaxComparisonResponse,
)
from structured_instruments.services.performance import (
    calculate_portfolio_metrics,
    calculate_spy_comparison,
    calculate_tax_comparison,
    get_chart_data,
)

router = APIRouter(prefix="/api/performance", tags=["performance"])


@router.get("/portfolio", response_model=PerformanceMetrics)
def get_portfolio_metrics(
    account_ids: list[int] = Depends(get_account_filter),
    session: Session = Depends(get_db),
) -> PerformanceMetrics:
    """TWR, XIRR, and total return metrics."""
    return calculate_portfolio_metrics(session, account_ids)


@router.get("/vs-spy", response_model=SpyComparison)
def get_spy_comparison(
    account_ids: list[int] = Depends(get_account_filter),
    session: Session = Depends(get_db),
) -> SpyComparison:
    """Portfolio vs SPY comparison."""
    return calculate_spy_comparison(session, account_ids)


@router.get("/chart-data", response_model=list[ChartDataPoint])
def get_chart_data_endpoint(
    account_ids: list[int] = Depends(get_account_filter),
    session: Session = Depends(get_db),
) -> list[ChartDataPoint]:
    """Time series for cumulative return chart."""
    return get_chart_data(session, account_ids)


@router.get("/tax-comparison", response_model=TaxComparisonResponse)
def get_tax_comparison(
    ordinary_rate: float = Query(0.37, ge=0, le=1, description="Federal ordinary income tax rate"),
    ltcg_rate: float = Query(0.20, ge=0, le=1, description="Federal long-term capital gains rate"),
    state_rate: float = Query(0.0, ge=0, le=1, description="State income tax rate"),
    spy_tax_treatment: str = Query("auto", description="SPY tax treatment: auto, income, or ltcg"),
    account_ids: list[int] = Depends(get_account_filter),
    session: Session = Depends(get_db),
) -> TaxComparisonResponse:
    """After-tax comparison: portfolio coupons vs SPY returns."""
    return calculate_tax_comparison(session, account_ids, ordinary_rate, ltcg_rate, state_rate, spy_tax_treatment)
