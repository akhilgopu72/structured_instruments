"""Refresh API router - fetch latest prices and re-evaluate coupons/autocalls."""
from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from structured_instruments.api.dependencies import get_db
from structured_instruments.services.autocall_evaluator import evaluate_all_pending_autocalls
from structured_instruments.services.coupon_evaluator import evaluate_all_pending
from structured_instruments.services.pricing import fetch_all_active

router = APIRouter(prefix="/api/refresh", tags=["refresh"])

_NYSE_CLOSE = time(16, 0)
_ET = ZoneInfo("America/New_York")


class RefreshResult(BaseModel):
    prices_updated: int
    coupons_evaluated: int
    autocalls_evaluated: int


@router.post("/", response_model=RefreshResult)
def refresh_data(session: Session = Depends(get_db)) -> RefreshResult:
    """Fetch latest prices for all active tickers, then evaluate pending coupons and autocalls.

    Returns a summary of how many prices were updated and how many
    coupon/autocall events were evaluated.
    """
    # 1. Fetch latest prices for all active tickers
    price_results = fetch_all_active(session, days=5)
    prices_updated = sum(price_results.values())

    # Cutoff for evaluation: include today only after the NYSE close, otherwise
    # use the prior day. Evaluating an observation date intraday would lock in
    # a provisional yfinance bar as the official close, and the evaluator's
    # already-evaluated guard would prevent any re-evaluation.
    now_et = datetime.now(_ET)
    cutoff = now_et.date() if now_et.time() >= _NYSE_CLOSE else now_et.date() - timedelta(days=1)

    # 2. Evaluate pending coupons
    coupon_events = evaluate_all_pending(session, target_date=cutoff)
    coupons_evaluated = len(coupon_events)

    # 3. Evaluate pending autocalls
    autocall_events = evaluate_all_pending_autocalls(session, target_date=cutoff)
    autocalls_evaluated = len(autocall_events)

    return RefreshResult(
        prices_updated=prices_updated,
        coupons_evaluated=coupons_evaluated,
        autocalls_evaluated=autocalls_evaluated,
    )
