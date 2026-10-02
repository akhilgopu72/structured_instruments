"""Prices API router."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from structured_instruments.api.dependencies import get_db
from structured_instruments.services.pricing import fetch_all_active

router = APIRouter(prefix="/api/prices", tags=["prices"])


@router.post("/fetch")
def trigger_price_fetch(session: Session = Depends(get_db)) -> dict[str, int]:
    """Trigger price update for all active tickers."""
    results = fetch_all_active(session)
    return results
