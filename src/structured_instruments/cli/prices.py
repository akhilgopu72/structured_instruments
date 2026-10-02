"""si prices fetch / si prices backfill / si prices adjust-splits - Price management commands."""
from datetime import date, datetime
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from structured_instruments.database import get_session
from structured_instruments.services.pricing import (
    fetch_all_active,
    fetch_prices,
)

prices_app = typer.Typer(help="Price data management")
console = Console()


@prices_app.command("adjust-splits")
def adjust_splits(
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would change without applying"),
):
    """Detect stock splits and adjust barrier prices, then re-fetch and re-evaluate."""
    from sqlalchemy import delete, select

    from structured_instruments.models.autocall_event import AutocallEvent
    from structured_instruments.models.coupon_event import CouponEvent
    from structured_instruments.models.instrument import Instrument
    from structured_instruments.services.autocall_evaluator import evaluate_all_pending_autocalls
    from structured_instruments.services.coupon_evaluator import evaluate_all_pending
    from structured_instruments.services.split_adjuster import adjust_splits as do_adjust

    with get_session() as session:
        # 1. Detect and apply split adjustments
        console.print("[bold]Detecting stock splits ...[/bold]")
        adjustments = do_adjust(session, dry_run=dry_run)

        if not adjustments:
            console.print("[dim]No split adjustments needed.[/dim]")
            return

        table = Table(title="Split Adjustments" + (" (DRY RUN)" if dry_run else ""))
        table.add_column("CUSIP", style="cyan")
        table.add_column("Ticker", style="white")
        table.add_column("Factor", justify="right")
        table.add_column("Old Initial", justify="right")
        table.add_column("New Initial", justify="right", style="green")
        table.add_column("Old Coupon Barrier", justify="right")
        table.add_column("New Coupon Barrier", justify="right", style="green")

        for adj in adjustments:
            table.add_row(
                adj["instrument_cusip"],
                adj["ticker"],
                f"{adj['new_factor']:.1f}",
                f"${adj['old_initial_price']:,.4f}",
                f"${adj['new_initial_price']:,.4f}",
                f"${adj['old_coupon_barrier_price']:,.4f}",
                f"${adj['new_coupon_barrier_price']:,.4f}",
            )

        console.print(table)

        if dry_run:
            console.print("[yellow]Dry run — no changes applied.[/yellow]")
            return

        # 2. Collect affected instrument IDs and tickers
        affected_cusips = {adj["instrument_cusip"] for adj in adjustments}
        affected_tickers = {adj["ticker"] for adj in adjustments}

        stmt = select(Instrument).where(Instrument.cusip.in_(affected_cusips))
        affected_instruments: list[Instrument] = list(
            session.execute(stmt).scalars().all()
        )
        affected_ids = [inst.id for inst in affected_instruments]

        # 3. Delete stale coupon and autocall events for affected instruments
        if affected_ids:
            del_coupons = delete(CouponEvent).where(CouponEvent.instrument_id.in_(affected_ids))
            del_autocalls = delete(AutocallEvent).where(AutocallEvent.instrument_id.in_(affected_ids))
            c_count = session.execute(del_coupons).rowcount
            a_count = session.execute(del_autocalls).rowcount
            console.print(f"  Deleted {c_count} stale coupon event(s), {a_count} autocall event(s).")

            # 4. Reset any wrongly "called" instruments to "active"
            for inst in affected_instruments:
                if inst.status == "called":
                    inst.status = "active"
                    console.print(f"  Reset {inst.cusip} status from 'called' to 'active'.")

            session.commit()

        # 5. Re-fetch prices with update_existing for affected tickers
        console.print("[bold]Re-fetching prices for affected tickers ...[/bold]")
        from structured_instruments.models.instrument import InstrumentUnderlying
        from structured_instruments.models.underlying import Underlying

        for ticker in sorted(affected_tickers):
            iu_stmt = (
                select(InstrumentUnderlying)
                .join(Underlying, InstrumentUnderlying.underlying_id == Underlying.id)
                .where(Underlying.ticker == ticker)
            )
            iu_rows = list(session.execute(iu_stmt).scalars().all())
            if iu_rows:
                earliest_date = min(iu.instrument.pricing_date for iu in iu_rows)
                count = fetch_prices(
                    session, ticker, earliest_date, date.today(), update_existing=True
                )
                console.print(f"  {ticker}: updated {count} price row(s).")

        # 6. Re-evaluate all pending coupons and autocalls
        console.print("[bold]Re-evaluating coupons and autocalls ...[/bold]")
        coupon_events = evaluate_all_pending(session)
        autocall_events = evaluate_all_pending_autocalls(session)
        console.print(
            f"  Evaluated {len(coupon_events)} coupon date(s), "
            f"{len(autocall_events)} autocall date(s)."
        )

        console.print("[green]Split adjustment complete.[/green]")


@prices_app.command("fetch")
def fetch():
    """Fetch latest prices for all active tickers + SPY."""
    with get_session() as session:
        console.print("[bold]Fetching prices for all active tickers + SPY ...[/bold]")
        results = fetch_all_active(session)

        table = Table(title="Price Fetch Results")
        table.add_column("Ticker", style="cyan", justify="left")
        table.add_column("New Rows", style="green", justify="right")

        total = 0
        for ticker, count in sorted(results.items()):
            table.add_row(ticker, str(count))
            total += count

        table.add_section()
        table.add_row("[bold]Total[/bold]", f"[bold]{total}[/bold]")

        console.print(table)
        console.print(f"[green]Done.[/green] {total} new price rows inserted.")


@prices_app.command("backfill")
def backfill(
    ticker: str = typer.Option(..., "--ticker", "-t", help="Ticker symbol"),
    start: str = typer.Option(..., "--from", help="Start date (YYYY-MM-DD)"),
    end: Optional[str] = typer.Option(None, "--to", help="End date (YYYY-MM-DD)"),
):
    """Backfill historical prices for a ticker."""
    start_date = datetime.strptime(start, "%Y-%m-%d").date()
    end_date = datetime.strptime(end, "%Y-%m-%d").date() if end else date.today()

    if start_date > end_date:
        console.print("[red]Error:[/red] --from date must be before --to date.")
        raise typer.Exit(code=1)

    with get_session() as session:
        console.print(
            f"[bold]Backfilling [cyan]{ticker}[/cyan] from {start_date} to {end_date} ...[/bold]"
        )
        count = fetch_prices(session, ticker, start_date, end_date)

        table = Table(title=f"Backfill Results for {ticker}")
        table.add_column("Ticker", style="cyan", justify="left")
        table.add_column("Date Range", justify="center")
        table.add_column("New Rows", style="green", justify="right")

        table.add_row(ticker, f"{start_date} -> {end_date}", str(count))

        console.print(table)
        console.print(f"[green]Done.[/green] {count} new price rows inserted.")
