"""Candidate offerings: notes being offered, not yet bought.

Preliminary pricing supplements go through the same ``pdf_parser`` as final
prospectuses (Add page, Gmail sync); a parse with blank initial prices becomes
a candidate here instead of a portfolio position.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from structured_instruments.models.candidate import CandidateOffering
from structured_instruments.schemas.instrument import ParsedInstrumentData
from structured_instruments.services.note_screener import CandidateNote

# Broker attachment names look like "48% Coupon ASTS RKLB IREN 83372H7B8 10.30.2026.pdf".
FILENAME_PATTERN = re.compile(
    r"(?P<coupon>\d+(?:\.\d+)?)%\s+(?:Coupon\s+)?(?P<tickers>[A-Z.\s]+?)\s+"
    r"(?P<cusip>[0-9A-Z]{9})\s+(?P<date>\d{2}\.\d{2}\.\d{4})",
)


@dataclass
class FilenameTerms:
    coupon_rate_annual: float
    tickers: list[str]
    cusip: str
    pricing_date: date


def parse_filename(filename: str) -> FilenameTerms | None:
    m = FILENAME_PATTERN.search(filename)
    if not m:
        return None
    try:
        pricing = datetime.strptime(m["date"], "%m.%d.%Y").date()
    except ValueError:
        return None
    return FilenameTerms(
        coupon_rate_annual=float(m["coupon"]) / 100,
        tickers=m["tickers"].split(),
        cusip=m["cusip"],
        pricing_date=pricing,
    )


def review_notes(parsed: ParsedInstrumentData, tickers: list[str], filename: str | None) -> list[str]:
    """Implausible values and disagreements with the attachment filename."""
    notes: list[str] = []
    if not (0 < parsed.coupon_rate_annual < 1.5):
        notes.append(f"coupon {parsed.coupon_rate_annual:.2%} looks implausible")
    for label, value in (
        ("coupon barrier", parsed.coupon_barrier_pct),
        ("downside barrier", parsed.downside_barrier_pct),
    ):
        if not (0.2 <= value <= 1.0):
            notes.append(f"{label} {value:.0%} looks implausible")
    if not (1 <= len(tickers) <= 5):
        notes.append(f"{len(tickers)} underlyings")
    if not parsed.valuation_dates:
        notes.append("no observation dates parsed (assumed 24 monthly, autocall from #3)")

    from_name = parse_filename(filename) if filename else None
    if from_name:
        if from_name.cusip != parsed.cusip:
            notes.append(f"CUSIP {parsed.cusip} != filename {from_name.cusip}")
        if abs(from_name.coupon_rate_annual - parsed.coupon_rate_annual) > 0.0026:
            notes.append(
                f"coupon {parsed.coupon_rate_annual:.2%} != filename {from_name.coupon_rate_annual:.2%}"
            )
        if set(from_name.tickers) != set(tickers):
            notes.append(f"tickers {','.join(tickers)} != filename {','.join(from_name.tickers)}")
    return notes


def upsert_from_parsed(
    session: Session,
    parsed: ParsedInstrumentData,
    source: str,
    filename: str | None = None,
    source_ref: str | None = None,
    email_subject: str | None = None,
    received_at: datetime | None = None,
) -> tuple[CandidateOffering, bool]:
    """Create (or return the existing) candidate for a parsed supplement.

    Returns (candidate, created). The same note often arrives twice (original
    email + a forward); the first parse wins.
    """
    cusip = parsed.cusip.strip().upper()
    existing = session.execute(
        select(CandidateOffering).where(CandidateOffering.cusip == cusip)
    ).scalar_one_or_none()
    if existing is not None:
        return existing, False

    tickers = [u.ticker.strip().upper().split()[0] for u in parsed.underlyings if u.ticker.strip()]
    vds = sorted(parsed.valuation_dates, key=lambda v: v.sequence_number)
    autocall_seq = [v.sequence_number for v in vds if v.autocall_eligible]
    notes = review_notes(parsed, tickers, filename)

    candidate = CandidateOffering(
        cusip=cusip,
        issuer=parsed.issuer,
        tickers=",".join(tickers),
        coupon_rate_annual=parsed.coupon_rate_annual,
        coupon_barrier_pct=parsed.coupon_barrier_pct,
        downside_barrier_pct=parsed.downside_barrier_pct,
        autocall_barrier_pct=parsed.autocall_barrier_pct,
        num_observations=len(vds) or 24,
        first_autocall_observation=min(autocall_seq) if autocall_seq else 3,
        pricing_date=parsed.pricing_date,
        maturity_date=parsed.maturity_date,
        offering_month=parsed.pricing_date.strftime("%Y-%m"),
        source=source,
        source_ref=source_ref,
        source_filename=filename,
        email_subject=email_subject,
        received_at=received_at,
        review_notes="; ".join(notes) or None,
    )
    session.add(candidate)
    session.commit()
    session.refresh(candidate)
    return candidate, True


def import_json(session: Session, path: Path) -> tuple[int, int]:
    """Load a hand-entered candidates file (data/candidates/*.json).
    Returns (added, skipped)."""
    raw = json.loads(path.read_text())
    pricing = datetime.strptime(raw["pricing_date"], "%Y-%m-%d").date()
    added = skipped = 0
    for n in raw["notes"]:
        exists = session.execute(
            select(CandidateOffering.id).where(CandidateOffering.cusip == n["cusip"])
        ).first()
        if exists:
            skipped += 1
            continue
        session.add(CandidateOffering(
            cusip=n["cusip"],
            issuer=n["issuer"],
            tickers=",".join(n["tickers"]),
            coupon_rate_annual=n["coupon_rate_annual"],
            coupon_barrier_pct=n["coupon_barrier_pct"],
            downside_barrier_pct=n["downside_barrier_pct"],
            autocall_barrier_pct=n.get("autocall_barrier_pct", 1.0),
            num_observations=n.get("num_observations", 24),
            first_autocall_observation=n.get("first_autocall_observation", 3),
            pricing_date=pricing,
            offering_month=pricing.strftime("%Y-%m"),
            source="import",
            source_filename=path.name,
        ))
        added += 1
    session.commit()
    return added, skipped


def list_candidates(session: Session, month: str | None = None, include_dismissed: bool = False) -> list[CandidateOffering]:
    stmt = select(CandidateOffering).order_by(CandidateOffering.coupon_rate_annual.desc())
    if month:
        stmt = stmt.where(CandidateOffering.offering_month == month)
    if not include_dismissed:
        stmt = stmt.where(CandidateOffering.dismissed.is_(False))
    return list(session.execute(stmt).scalars().all())


def to_screen_note(c: CandidateOffering) -> CandidateNote:
    return CandidateNote(
        cusip=c.cusip,
        issuer=c.issuer,
        tickers=c.ticker_list,
        coupon_rate_annual=c.coupon_rate_annual,
        coupon_barrier_pct=c.coupon_barrier_pct,
        downside_barrier_pct=c.downside_barrier_pct,
        autocall_barrier_pct=c.autocall_barrier_pct,
        num_observations=c.num_observations,
        first_autocall_observation=c.first_autocall_observation,
    )
