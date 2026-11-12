"""Candidates API router - offered notes, screener runs, and Gmail sync."""
from __future__ import annotations

import json
import threading
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from structured_instruments.api.dependencies import get_account_filter, get_current_user, get_db
from structured_instruments.database import get_session
from structured_instruments.models.candidate import CandidateOffering, GmailSyncState, ScreenRun
from structured_instruments.models.user import User
from structured_instruments.services import gmail_ingest
from structured_instruments.services.candidates import list_candidates
from structured_instruments.services.screen_runner import ScreenParams, latest_run, start_screen_run

router = APIRouter(prefix="/api/candidates", tags=["candidates"])

_sync_lock = threading.Lock()


class CandidateOut(BaseModel):
    cusip: str
    issuer: str
    tickers: list[str]
    coupon_rate_annual: float
    coupon_barrier_pct: float
    downside_barrier_pct: float
    autocall_barrier_pct: float
    num_observations: int
    first_autocall_observation: int
    pricing_date: date | None
    maturity_date: date | None
    offering_month: str
    source: str
    source_filename: str | None
    email_subject: str | None
    received_at: datetime | None
    review_notes: str | None
    dismissed: bool


class MonthOut(BaseModel):
    month: str
    count: int


class CandidatePatch(BaseModel):
    dismissed: bool


class ScreenRequest(BaseModel):
    month: str
    stake: float = 10_000
    coupon_tax: float = 0.408
    state_tax: float = 0.0
    loss_tax: float = 0.238
    erp: float = 0.05
    reversal: float = 0.0
    reversal_signal: str = "3m"


class ScreenRunOut(BaseModel):
    id: int
    status: str
    created_at: datetime
    finished_at: datetime | None
    account_ids: list[int]
    error: str | None
    result: dict | None


class GmailStatus(BaseModel):
    connected: bool
    syncing: bool
    last_run_at: datetime | None
    last_success_at: datetime | None
    last_added: int
    last_error: str | None


def _to_out(c: CandidateOffering) -> CandidateOut:
    return CandidateOut(
        cusip=c.cusip,
        issuer=c.issuer,
        tickers=c.ticker_list,
        coupon_rate_annual=c.coupon_rate_annual,
        coupon_barrier_pct=c.coupon_barrier_pct,
        downside_barrier_pct=c.downside_barrier_pct,
        autocall_barrier_pct=c.autocall_barrier_pct,
        num_observations=c.num_observations,
        first_autocall_observation=c.first_autocall_observation,
        pricing_date=c.pricing_date,
        maturity_date=c.maturity_date,
        offering_month=c.offering_month,
        source=c.source,
        source_filename=c.source_filename,
        email_subject=c.email_subject,
        received_at=c.received_at,
        review_notes=c.review_notes,
        dismissed=c.dismissed,
    )


@router.get("/months", response_model=list[MonthOut])
def list_months(
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> list[MonthOut]:
    rows = session.execute(
        select(CandidateOffering.offering_month, func.count())
        .where(CandidateOffering.dismissed.is_(False))
        .group_by(CandidateOffering.offering_month)
        .order_by(CandidateOffering.offering_month.desc())
    ).all()
    return [MonthOut(month=m, count=n) for m, n in rows]


@router.get("/", response_model=list[CandidateOut])
def get_candidates(
    month: str | None = None,
    include_dismissed: bool = False,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> list[CandidateOut]:
    return [_to_out(c) for c in list_candidates(session, month, include_dismissed)]


@router.patch("/{cusip}", response_model=CandidateOut)
def update_candidate(
    cusip: str,
    body: CandidatePatch,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> CandidateOut:
    c = session.execute(
        select(CandidateOffering).where(CandidateOffering.cusip == cusip)
    ).scalar_one_or_none()
    if c is None:
        raise HTTPException(status_code=404, detail=f"Candidate {cusip} not found")
    c.dismissed = body.dismissed
    session.commit()
    return _to_out(c)


def _run_out(run) -> ScreenRunOut:
    return ScreenRunOut(
        id=run.id,
        status=run.status,
        created_at=run.created_at,
        finished_at=run.finished_at,
        account_ids=[int(a) for a in run.account_ids.split(",") if a],
        error=run.error,
        result=json.loads(run.result_json) if run.result_json else None,
    )


@router.post("/screen", response_model=ScreenRunOut, status_code=202)
def screen(
    body: ScreenRequest,
    account_ids: list[int] = Depends(get_account_filter),
    session: Session = Depends(get_db),
) -> ScreenRunOut:
    """Start a screener run for *month* against the selected accounts' books."""
    params = ScreenParams(**body.model_dump(exclude={"month"}))
    run_id = start_screen_run(body.month, sorted(account_ids), params)
    return _run_out(session.get(ScreenRun, run_id))


@router.get("/screen/latest", response_model=ScreenRunOut | None)
def get_latest_screen(
    month: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> ScreenRunOut | None:
    run = latest_run(session, month)
    return _run_out(run) if run else None


@router.get("/gmail/status", response_model=GmailStatus)
def gmail_status(
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> GmailStatus:
    state = session.get(GmailSyncState, 1)
    return GmailStatus(
        connected=gmail_ingest.is_connected(),
        syncing=_sync_lock.locked(),
        last_run_at=state.last_run_at if state else None,
        last_success_at=state.last_success_at if state else None,
        last_added=state.last_added if state else 0,
        last_error=state.last_error if state else None,
    )


def run_gmail_sync_in_background() -> bool:
    """Start a sync unless one is already running. Returns whether it started."""
    if not gmail_ingest.is_connected() or not _sync_lock.acquire(blocking=False):
        return False

    def work() -> None:
        s = get_session()
        try:
            gmail_ingest.sync_and_record(s)
        except Exception:
            pass  # recorded in GmailSyncState
        finally:
            s.close()
            _sync_lock.release()

    threading.Thread(target=work, daemon=True).start()
    return True


@router.post("/gmail/sync", status_code=202)
def gmail_sync(user: User = Depends(get_current_user)) -> dict:
    if not gmail_ingest.is_connected():
        raise HTTPException(status_code=400, detail="Gmail not connected - run `si gmail auth`")
    return {"started": run_gmail_sync_in_background()}
