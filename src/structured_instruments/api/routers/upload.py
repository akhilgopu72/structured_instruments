"""Upload API router - parse prospectus PDFs and commit to portfolio."""
from __future__ import annotations

import tempfile
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from structured_instruments.api.dependencies import get_db, get_current_user
from structured_instruments.database import get_session
from structured_instruments.models.account import Account
from structured_instruments.models.instrument import Instrument, InstrumentUnderlying
from structured_instruments.models.position import PortfolioPosition
from structured_instruments.models.underlying import Underlying
from structured_instruments.models.user import User
from structured_instruments.models.valuation_date import ValuationDate
from structured_instruments.schemas.instrument import ParsedInstrumentData
from structured_instruments.services.pdf_parser import parse_prospectus_pdf
from structured_instruments.services.pricing import fetch_prices

router = APIRouter(prefix="/api/upload", tags=["upload"])


class ParsedFile(BaseModel):
    filename: str
    parsed: ParsedInstrumentData | None = None
    error: str | None = None
    existing_cusip: bool = False


class ParseResponse(BaseModel):
    files: list[ParsedFile]


class CommitItem(BaseModel):
    parsed: ParsedInstrumentData
    principal: float
    filename: str | None = None


class CommitRequest(BaseModel):
    account_id: int
    items: list[CommitItem]


class CommitResultItem(BaseModel):
    filename: str | None
    cusip: str
    status: str  # "added", "position_added", "error"
    message: str | None = None
    prices_backfilled: dict[str, int] = {}


class CommitResponse(BaseModel):
    results: list[CommitResultItem]


@router.post("/parse", response_model=ParseResponse)
async def parse_pdfs(
    files: list[UploadFile] = File(...),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> ParseResponse:
    """Parse one or more prospectus PDFs and return previews without persisting."""
    if not files:
        raise HTTPException(status_code=400, detail="At least one file is required")

    results: list[ParsedFile] = []
    for upload in files:
        filename = upload.filename or "upload.pdf"
        if not filename.lower().endswith(".pdf"):
            results.append(ParsedFile(filename=filename, error="File must be a PDF"))
            continue

        try:
            content = await upload.read()
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=True) as tmp:
                tmp.write(content)
                tmp.flush()
                parsed = parse_prospectus_pdf(Path(tmp.name))

            existing = session.execute(
                select(Instrument).where(Instrument.cusip == parsed.cusip)
            ).scalar_one_or_none()

            results.append(
                ParsedFile(
                    filename=filename,
                    parsed=parsed,
                    existing_cusip=existing is not None,
                )
            )
        except FileNotFoundError as exc:
            results.append(ParsedFile(filename=filename, error=str(exc)))
        except ValueError as exc:
            results.append(ParsedFile(filename=filename, error=f"Parsing error: {exc}"))
        except Exception as exc:
            results.append(ParsedFile(filename=filename, error=f"Error: {exc}"))

    return ParseResponse(files=results)


@router.post("/commit", response_model=CommitResponse)
def commit_instruments(
    body: CommitRequest,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db),
) -> CommitResponse:
    """Persist previously-parsed instruments to a user's account.

    Each item carries its own previously-parsed JSON and principal. Skips items
    whose CUSIP already has a position on the account, returning an explicit
    error for that file.
    """
    if not body.items:
        raise HTTPException(status_code=400, detail="At least one item is required")

    account = session.execute(
        select(Account).where(
            Account.id == body.account_id, Account.user_id == user.id
        )
    ).scalar_one_or_none()
    if account is None:
        raise HTTPException(
            status_code=400,
            detail=f"Account {body.account_id} not found for current user",
        )

    results: list[CommitResultItem] = []
    today = date.today()

    for item in body.items:
        parsed = item.parsed
        try:
            if item.principal <= 0:
                results.append(
                    CommitResultItem(
                        filename=item.filename,
                        cusip=parsed.cusip,
                        status="error",
                        message="Principal must be greater than 0",
                    )
                )
                continue

            existing = session.execute(
                select(Instrument).where(Instrument.cusip == parsed.cusip)
            ).scalar_one_or_none()

            if existing:
                existing_pos = session.execute(
                    select(PortfolioPosition).where(
                        PortfolioPosition.instrument_id == existing.id,
                        PortfolioPosition.account_id == body.account_id,
                    )
                ).scalar_one_or_none()
                if existing_pos:
                    results.append(
                        CommitResultItem(
                            filename=item.filename,
                            cusip=parsed.cusip,
                            status="error",
                            message=f"Account already has a position for {parsed.cusip}",
                        )
                    )
                    continue

                num_notes = int(item.principal / 1000)
                position = PortfolioPosition(
                    user_id=user.id,
                    account_id=body.account_id,
                    instrument_id=existing.id,
                    principal=item.principal,
                    num_notes=num_notes,
                    purchase_date=existing.pricing_date,
                )
                session.add(position)
                session.commit()
                results.append(
                    CommitResultItem(
                        filename=item.filename,
                        cusip=parsed.cusip,
                        status="position_added",
                        message="Added position to existing instrument",
                    )
                )
                continue

            instrument = Instrument(
                cusip=parsed.cusip,
                issuer=parsed.issuer,
                product_type=parsed.product_type,
                coupon_rate_annual=parsed.coupon_rate_annual,
                coupon_rate_monthly=parsed.coupon_rate_monthly,
                coupon_barrier_pct=parsed.coupon_barrier_pct,
                downside_barrier_pct=parsed.downside_barrier_pct,
                autocall_barrier_pct=parsed.autocall_barrier_pct,
                pricing_date=parsed.pricing_date,
                maturity_date=parsed.maturity_date,
                status="active",
            )
            session.add(instrument)
            session.flush()

            for u in parsed.underlyings:
                underlying = session.execute(
                    select(Underlying).where(Underlying.ticker == u.ticker)
                ).scalar_one_or_none()
                if underlying is None:
                    underlying = Underlying(ticker=u.ticker, name=u.name)
                    session.add(underlying)
                    session.flush()

                coupon_barrier_price = u.initial_price * parsed.coupon_barrier_pct
                downside_barrier_price = u.initial_price * parsed.downside_barrier_pct
                session.add(
                    InstrumentUnderlying(
                        instrument_id=instrument.id,
                        underlying_id=underlying.id,
                        initial_price=u.initial_price,
                        coupon_barrier_price=coupon_barrier_price,
                        downside_barrier_price=downside_barrier_price,
                    )
                )

            for v in parsed.valuation_dates:
                session.add(
                    ValuationDate(
                        instrument_id=instrument.id,
                        date=v.date,
                        autocall_eligible=v.autocall_eligible,
                        sequence_number=v.sequence_number,
                    )
                )

            num_notes = int(item.principal / 1000)
            position = PortfolioPosition(
                user_id=user.id,
                account_id=body.account_id,
                instrument_id=instrument.id,
                principal=item.principal,
                num_notes=num_notes,
                purchase_date=parsed.pricing_date,
            )
            session.add(position)
            session.commit()

            prices_backfilled: dict[str, int] = {}
            for u in parsed.underlyings:
                try:
                    count = fetch_prices(session, u.ticker, parsed.pricing_date, today)
                    prices_backfilled[u.ticker] = count
                except Exception:
                    prices_backfilled[u.ticker] = 0

            results.append(
                CommitResultItem(
                    filename=item.filename,
                    cusip=parsed.cusip,
                    status="added",
                    prices_backfilled=prices_backfilled,
                )
            )
        except Exception as exc:
            session.rollback()
            results.append(
                CommitResultItem(
                    filename=item.filename,
                    cusip=parsed.cusip,
                    status="error",
                    message=f"Database error: {exc}",
                )
            )

    return CommitResponse(results=results)
