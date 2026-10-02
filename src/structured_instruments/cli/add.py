"""si add <pdf_path> --principal <amount> --user <name> - Parse PDF and add instrument."""

from datetime import date
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table
from sqlalchemy import select

from structured_instruments.database import get_session
from structured_instruments.models.account import Account
from structured_instruments.models.instrument import Instrument, InstrumentUnderlying
from structured_instruments.models.position import PortfolioPosition
from structured_instruments.models.underlying import Underlying
from structured_instruments.models.user import User
from structured_instruments.models.valuation_date import ValuationDate
from structured_instruments.services.pdf_parser import parse_prospectus_pdf

console = Console()


def add(
    pdf_path: Path = typer.Argument(..., help="Path to prospectus PDF"),
    principal: float = typer.Option(..., "--principal", "-p", help="Principal amount invested"),
    user_name: str = typer.Option(..., "--user", "-u", help="User name (created if not exists)"),
    account_id: int = typer.Option(..., "--account-id", "-a", help="Account ID to add position to"),
):
    """Parse a prospectus PDF and add the instrument to the database."""
    # 1. Validate PDF exists
    pdf_path = pdf_path.resolve()
    if not pdf_path.exists():
        console.print(f"[red]Error: PDF not found at {pdf_path}[/red]")
        raise typer.Exit(code=1)
    if not pdf_path.suffix.lower() == ".pdf":
        console.print("[red]Error: File must be a PDF[/red]")
        raise typer.Exit(code=1)

    # 2. Parse the PDF
    console.print(f"\n[bold blue]Parsing prospectus:[/bold blue] {pdf_path.name}")
    console.print("[dim]Sending PDF to Claude for extraction...[/dim]\n")

    try:
        parsed = parse_prospectus_pdf(pdf_path)
    except FileNotFoundError as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(code=1)
    except ValueError as exc:
        console.print(f"[red]Parsing error: {exc}[/red]")
        raise typer.Exit(code=1)
    except Exception as exc:
        console.print(f"[red]API error: {exc}[/red]")
        raise typer.Exit(code=1)

    # 3. Validate account
    session = get_session()
    try:
        account = session.execute(
            select(Account).where(Account.id == account_id)
        ).scalar_one_or_none()
        if account is None:
            console.print(f"[red]Error: Account with id {account_id} not found[/red]")
            raise typer.Exit(code=1)

        # Verify the account belongs to the specified user (or user will be created)
        user = session.execute(
            select(User).where(User.name == user_name)
        ).scalar_one_or_none()
        if user is not None and account.user_id != user.id:
            console.print(f"[red]Error: Account {account_id} does not belong to user '{user_name}'[/red]")
            raise typer.Exit(code=1)
    finally:
        session.close()

    # 4. Display extracted data
    _display_parsed_data(parsed, principal, user_name)

    # 5. Confirm
    if not typer.confirm("\nProceed with adding this instrument?"):
        console.print("[yellow]Cancelled.[/yellow]")
        raise typer.Exit(code=0)

    # 6. Save to database
    _save_to_database(parsed, principal, user_name, account_id)

    # 6. Trigger price backfill
    _backfill_prices(parsed)

    console.print(f"\n[bold green]Successfully added instrument {parsed.cusip} for user {user_name}![/bold green]")


def _display_parsed_data(parsed, principal: float, user_name: str) -> None:
    """Display the parsed instrument data in rich tables for user review."""
    # Main instrument details table
    details_table = Table(title="Extracted Instrument Details", show_header=False, border_style="blue")
    details_table.add_column("Field", style="cyan", width=25)
    details_table.add_column("Value", style="white")

    details_table.add_row("CUSIP", parsed.cusip)
    details_table.add_row("Issuer", parsed.issuer)
    details_table.add_row("Product Type", parsed.product_type or "N/A")
    details_table.add_row("Annual Coupon Rate", f"{parsed.coupon_rate_annual:.4%}")
    details_table.add_row("Monthly Coupon Rate", f"{parsed.coupon_rate_monthly:.6%}")
    details_table.add_row("Coupon Barrier", f"{parsed.coupon_barrier_pct:.2%}")
    details_table.add_row("Downside Barrier", f"{parsed.downside_barrier_pct:.2%}")
    details_table.add_row("Autocall Barrier", f"{parsed.autocall_barrier_pct:.2%}")
    details_table.add_row("Pricing Date", str(parsed.pricing_date))
    details_table.add_row("Maturity Date", str(parsed.maturity_date))
    details_table.add_row("Principal", f"${principal:,.2f}")
    details_table.add_row("Number of Notes", str(int(principal / 1000)))
    details_table.add_row("User", user_name)

    console.print(details_table)

    # Underlyings table
    und_table = Table(title="\nUnderlying Securities", border_style="green")
    und_table.add_column("Ticker", style="cyan")
    und_table.add_column("Name", style="white")
    und_table.add_column("Initial Price", style="yellow", justify="right")
    und_table.add_column("Coupon Barrier Price", style="magenta", justify="right")
    und_table.add_column("Downside Barrier Price", style="red", justify="right")

    for u in parsed.underlyings:
        coupon_barrier_price = u.initial_price * parsed.coupon_barrier_pct
        downside_barrier_price = u.initial_price * parsed.downside_barrier_pct
        und_table.add_row(
            u.ticker,
            u.name or "N/A",
            f"${u.initial_price:.2f}",
            f"${coupon_barrier_price:.2f}",
            f"${downside_barrier_price:.2f}",
        )

    console.print(und_table)

    # Valuation dates table
    val_table = Table(title="\nValuation Dates", border_style="yellow")
    val_table.add_column("#", style="dim", justify="right")
    val_table.add_column("Date", style="white")
    val_table.add_column("Autocall Eligible", style="cyan", justify="center")

    for v in parsed.valuation_dates:
        eligible_str = "[green]Yes[/green]" if v.autocall_eligible else "[dim]No[/dim]"
        val_table.add_row(str(v.sequence_number), str(v.date), eligible_str)

    console.print(val_table)


def _save_to_database(parsed, principal: float, user_name: str, account_id: int) -> None:
    """Create all database records for the parsed instrument."""
    session = get_session()

    try:
        # Look up or create user
        user = session.execute(
            select(User).where(User.name == user_name)
        ).scalar_one_or_none()
        if user is None:
            user = User(name=user_name)
            session.add(user)
            session.flush()
            console.print(f"[green]Created new user: {user_name}[/green]")

        # Check if instrument already exists
        existing = session.query(Instrument).filter_by(cusip=parsed.cusip).first()
        if existing:
            # Instrument exists — check if this account already has a position
            existing_pos = session.execute(
                select(PortfolioPosition).where(
                    PortfolioPosition.instrument_id == existing.id,
                    PortfolioPosition.account_id == account_id,
                )
            ).scalar_one_or_none()
            if existing_pos:
                console.print(
                    f"[red]Error: Account {account_id} already has a position for CUSIP {parsed.cusip}[/red]"
                )
                raise typer.Exit(code=1)

            # Create position for existing instrument
            num_notes = int(principal / 1000)
            position = PortfolioPosition(
                user_id=user.id,
                account_id=account_id,
                instrument_id=existing.id,
                principal=principal,
                num_notes=num_notes,
                purchase_date=existing.pricing_date,
            )
            session.add(position)
            session.commit()
            console.print(
                f"[green]Added position for user '{user_name}' on existing instrument {parsed.cusip}.[/green]"
            )
            return

        # Create Instrument record
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
        session.flush()  # Get the instrument.id

        # Create or find Underlying records and create InstrumentUnderlying links
        for u in parsed.underlyings:
            underlying = session.query(Underlying).filter_by(ticker=u.ticker).first()
            if underlying is None:
                underlying = Underlying(ticker=u.ticker, name=u.name)
                session.add(underlying)
                session.flush()

            coupon_barrier_price = u.initial_price * parsed.coupon_barrier_pct
            downside_barrier_price = u.initial_price * parsed.downside_barrier_pct

            inst_underlying = InstrumentUnderlying(
                instrument_id=instrument.id,
                underlying_id=underlying.id,
                initial_price=u.initial_price,
                coupon_barrier_price=coupon_barrier_price,
                downside_barrier_price=downside_barrier_price,
            )
            session.add(inst_underlying)

        # Create ValuationDate records
        for v in parsed.valuation_dates:
            val_date = ValuationDate(
                instrument_id=instrument.id,
                date=v.date,
                autocall_eligible=v.autocall_eligible,
                sequence_number=v.sequence_number,
            )
            session.add(val_date)

        # Create PortfolioPosition record
        num_notes = int(principal / 1000)
        position = PortfolioPosition(
            user_id=user.id,
            account_id=account_id,
            instrument_id=instrument.id,
            principal=principal,
            num_notes=num_notes,
            purchase_date=parsed.pricing_date,
        )
        session.add(position)

        session.commit()
        console.print("[green]Database records created successfully.[/green]")

    except typer.Exit:
        session.rollback()
        raise
    except Exception as exc:
        session.rollback()
        console.print(f"[red]Database error: {exc}[/red]")
        raise typer.Exit(code=1)
    finally:
        session.close()


def _backfill_prices(parsed) -> None:
    """Trigger price backfill for each underlying ticker from pricing_date to today."""
    today = date.today()
    tickers = [u.ticker for u in parsed.underlyings]

    console.print(f"\n[blue]Backfilling prices for {', '.join(tickers)}...[/blue]")

    try:
        from structured_instruments.database import get_session
        from structured_instruments.services.pricing import fetch_prices

        with get_session() as session:
            for ticker in tickers:
                try:
                    count = fetch_prices(session, ticker, parsed.pricing_date, today)
                    console.print(f"  [green]Backfilled {count} prices for {ticker}[/green]")
                except Exception as exc:
                    console.print(f"  [yellow]Warning: Could not backfill {ticker}: {exc}[/yellow]")

    except ImportError:
        console.print(
            "[yellow]Warning: Pricing service not available. "
            "Skipping price backfill. Run 'si prices fetch' later to populate prices.[/yellow]"
        )
    except Exception as exc:
        console.print(f"[yellow]Warning: Price backfill failed: {exc}[/yellow]")
