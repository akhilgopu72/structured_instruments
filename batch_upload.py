"""Batch upload script for processing multiple prospectuses in parallel.

Usage:
    python batch_upload.py <csv_mapping> <pdf_folder> --user "Name" --account-id N [--workers N]

The CSV must have columns: CUSIP, Amount
PDFs in the folder should be named <CUSIP>.pdf
"""

import argparse
import csv
import sys
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from sqlalchemy import select

from structured_instruments.database import get_session
from structured_instruments.models.account import Account
from structured_instruments.models.instrument import Instrument, InstrumentUnderlying
from structured_instruments.models.position import PortfolioPosition
from structured_instruments.models.underlying import Underlying
from structured_instruments.models.user import User
from structured_instruments.models.valuation_date import ValuationDate
from structured_instruments.services.pdf_parser import parse_prospectus_pdf
from structured_instruments.services.pricing import fetch_prices


def load_entries(csv_path: Path, pdf_folder: Path) -> list[tuple[str, float, Path]]:
    """Read CSV and return list of (cusip, amount, pdf_path) tuples."""
    entries = []
    with open(csv_path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            cusip = row["CUSIP"].strip()
            amount = float(row["Amount"].strip())
            # Fix missing leading zero (e.g. 6744EUB1 -> 06744EUB1)
            if len(cusip) == 8 and cusip[0].isdigit():
                cusip = "0" + cusip
            pdf_path = pdf_folder / f"{cusip}.pdf"
            if not pdf_path.exists():
                print(f"  WARNING: PDF not found for {cusip} at {pdf_path}, skipping")
                continue
            entries.append((cusip, amount, pdf_path))
    return entries


def parse_pdf(pdf_path: Path) -> object:
    """Parse a single PDF - designed to run in thread pool."""
    return parse_prospectus_pdf(pdf_path)


def save_instrument(parsed, principal: float, user_id: int, account_id: int) -> str:
    """Save a parsed instrument to DB. Returns status message."""
    with get_session() as session:
        existing = session.execute(
            select(Instrument).where(Instrument.cusip == parsed.cusip)
        ).scalar_one_or_none()

        if existing:
            existing_pos = session.execute(
                select(PortfolioPosition).where(
                    PortfolioPosition.instrument_id == existing.id,
                    PortfolioPosition.account_id == account_id,
                )
            ).scalar_one_or_none()
            if existing_pos:
                return f"SKIP {parsed.cusip}: position already exists"

            num_notes = int(principal / 1000)
            position = PortfolioPosition(
                user_id=user_id,
                account_id=account_id,
                instrument_id=existing.id,
                principal=principal,
                num_notes=num_notes,
                purchase_date=existing.pricing_date,
            )
            session.add(position)
            session.commit()
            return f"OK   {parsed.cusip}: added position to existing instrument"

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

            inst_underlying = InstrumentUnderlying(
                instrument_id=instrument.id,
                underlying_id=underlying.id,
                initial_price=u.initial_price,
                coupon_barrier_price=u.initial_price * parsed.coupon_barrier_pct,
                downside_barrier_price=u.initial_price * parsed.downside_barrier_pct,
            )
            session.add(inst_underlying)

        for v in parsed.valuation_dates:
            val_date = ValuationDate(
                instrument_id=instrument.id,
                date=v.date,
                autocall_eligible=v.autocall_eligible,
                sequence_number=v.sequence_number,
            )
            session.add(val_date)

        num_notes = int(principal / 1000)
        position = PortfolioPosition(
            user_id=user_id,
            account_id=account_id,
            instrument_id=instrument.id,
            principal=principal,
            num_notes=num_notes,
            purchase_date=parsed.pricing_date,
        )
        session.add(position)
        session.commit()
        return f"OK   {parsed.cusip}: created instrument + position (${principal:,.0f})"


def main():
    parser = argparse.ArgumentParser(description="Batch upload prospectuses")
    parser.add_argument("csv_mapping", type=Path, help="Path to CSV mapping file (CUSIP, Amount)")
    parser.add_argument("pdf_folder", type=Path, help="Folder containing <CUSIP>.pdf files")
    parser.add_argument("--user", "-u", required=True, help="User name")
    parser.add_argument("--account-id", "-a", type=int, required=True, help="Account ID")
    parser.add_argument("--workers", "-w", type=int, default=5, help="Max parallel PDF parsers (default: 5)")
    args = parser.parse_args()

    csv_path = args.csv_mapping.resolve()
    pdf_folder = args.pdf_folder.resolve()

    if not csv_path.exists():
        print(f"ERROR: CSV not found: {csv_path}")
        sys.exit(1)
    if not pdf_folder.is_dir():
        print(f"ERROR: PDF folder not found: {pdf_folder}")
        sys.exit(1)

    entries = load_entries(csv_path, pdf_folder)
    print(f"Loaded {len(entries)} entries from {csv_path}\n")

    # Validate user and account
    with get_session() as session:
        user = session.execute(
            select(User).where(User.name == args.user)
        ).scalar_one_or_none()
        if user is None:
            print(f"ERROR: User '{args.user}' not found")
            sys.exit(1)
        user_id = user.id

        account = session.execute(
            select(Account).where(Account.id == args.account_id)
        ).scalar_one_or_none()
        if account is None:
            print(f"ERROR: Account {args.account_id} not found")
            sys.exit(1)
        if account.user_id != user_id:
            print(f"ERROR: Account {args.account_id} does not belong to user '{args.user}'")
            sys.exit(1)
        print(f"User: {args.user} (id={user_id}), Account: {account.name} (id={args.account_id})\n")

    # Phase 1: Parse all PDFs in parallel
    print(f"=== Phase 1: Parsing {len(entries)} PDFs (max {args.workers} concurrent) ===\n")
    parsed_results = {}  # cusip -> (parsed, amount)
    errors = []

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        future_to_entry = {
            executor.submit(parse_pdf, pdf_path): (cusip, amount)
            for cusip, amount, pdf_path in entries
        }
        for future in as_completed(future_to_entry):
            cusip, amount = future_to_entry[future]
            try:
                parsed = future.result()
                parsed_results[cusip] = (parsed, amount)
                print(f"  PARSED {cusip} -> {parsed.issuer}, {len(parsed.underlyings)} underlyings")
            except Exception as e:
                errors.append((cusip, str(e)))
                print(f"  FAILED {cusip}: {e}")

    print(f"\nParsed: {len(parsed_results)}, Failed: {len(errors)}\n")

    # Phase 2: Save to DB sequentially
    print(f"=== Phase 2: Saving {len(parsed_results)} instruments to database ===\n")
    saved = 0
    all_parsed = []
    for cusip, (parsed, amount) in parsed_results.items():
        try:
            msg = save_instrument(parsed, amount, user_id, args.account_id)
            print(f"  {msg}")
            saved += 1
            all_parsed.append(parsed)
        except Exception as e:
            print(f"  FAIL {cusip}: {e}")
            traceback.print_exc()
            errors.append((cusip, str(e)))

    print(f"\nSaved: {saved}\n")

    # Phase 3: Backfill prices in parallel
    unique_tickers = {}
    for parsed in all_parsed:
        for u in parsed.underlyings:
            if u.ticker not in unique_tickers:
                unique_tickers[u.ticker] = parsed.pricing_date
            else:
                # Use the earliest pricing date for backfill
                if parsed.pricing_date < unique_tickers[u.ticker]:
                    unique_tickers[u.ticker] = parsed.pricing_date

    print(f"=== Phase 3: Backfilling prices for {len(unique_tickers)} unique tickers ===\n")
    today = date.today()

    def backfill_one(ticker, start_date):
        with get_session() as session:
            count = fetch_prices(session, ticker, start_date, today)
            return ticker, count

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(backfill_one, ticker, start): ticker
            for ticker, start in unique_tickers.items()
        }
        for future in as_completed(futures):
            ticker = futures[future]
            try:
                _, count = future.result()
                print(f"  {ticker}: {count} prices backfilled")
            except Exception as e:
                print(f"  {ticker}: FAILED ({e})")

    # Summary
    print(f"\n=== DONE ===")
    print(f"Instruments processed: {saved}/{len(entries)}")
    if errors:
        print(f"\nErrors ({len(errors)}):")
        for cusip, err in errors:
            print(f"  {cusip}: {err}")


if __name__ == "__main__":
    main()
