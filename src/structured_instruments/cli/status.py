"""si status [--cusip X] - Show instrument status with rich formatting."""
from __future__ import annotations

from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from sqlalchemy import select

from structured_instruments.database import get_session
from structured_instruments.models.account import Account
from structured_instruments.models.coupon_event import CouponEvent
from structured_instruments.models.instrument import Instrument
from structured_instruments.models.position import PortfolioPosition
from structured_instruments.models.price import DailyPrice
from structured_instruments.models.user import User
from structured_instruments.models.valuation_date import ValuationDate

console = Console()


def _get_latest_price(session, underlying_id: int) -> float | None:
    """Return the most recent closing price in the DB for *underlying_id*."""
    stmt = (
        select(DailyPrice)
        .where(DailyPrice.underlying_id == underlying_id)
        .order_by(DailyPrice.date.desc())
        .limit(1)
    )
    price = session.execute(stmt).scalar_one_or_none()
    return float(price.close) if price is not None else None


def _display_instrument(session, instrument: Instrument, user_id: int | None = None) -> None:
    """Render a full status display for a single instrument."""
    # --- Header panel ---
    status_color = {
        "active": "green",
        "called": "yellow",
        "matured": "dim",
    }.get(instrument.status, "white")

    header = (
        f"[bold]{instrument.cusip}[/bold]  |  "
        f"Issuer: [cyan]{instrument.issuer}[/cyan]  |  "
        f"Status: [{status_color}]{instrument.status.upper()}[/{status_color}]  |  "
        f"{instrument.pricing_date} -> {instrument.maturity_date}"
    )
    console.print(Panel(header, title="Instrument", border_style="blue"))

    # --- Underlying status table ---
    und_table = Table(title="Underlying Status")
    und_table.add_column("Ticker", style="cyan", justify="left")
    und_table.add_column("Initial Price", justify="right")
    und_table.add_column("Current Price", justify="right")
    und_table.add_column("% of Initial", justify="right")
    und_table.add_column("Dist to Coupon Barrier", justify="right")
    und_table.add_column("Dist to Downside Barrier", justify="right")

    for iu in instrument.underlyings:
        ticker = iu.underlying.ticker
        initial = iu.initial_price
        current = _get_latest_price(session, iu.underlying_id)

        if current is not None:
            pct_initial = current / initial
            dist_coupon = (current - iu.coupon_barrier_price) / iu.coupon_barrier_price
            dist_downside = (current - iu.downside_barrier_price) / iu.downside_barrier_price

            pct_str = f"{pct_initial:.1%}"
            if pct_initial >= 1.0:
                pct_str = f"[green]{pct_str}[/green]"
            elif pct_initial >= instrument.coupon_barrier_pct:
                pct_str = f"[yellow]{pct_str}[/yellow]"
            else:
                pct_str = f"[red]{pct_str}[/red]"

            dist_coupon_str = f"{dist_coupon:+.1%}"
            if dist_coupon >= 0:
                dist_coupon_str = f"[green]{dist_coupon_str}[/green]"
            else:
                dist_coupon_str = f"[red]{dist_coupon_str}[/red]"

            dist_ds_str = f"{dist_downside:+.1%}"
            if dist_downside >= 0:
                dist_ds_str = f"[green]{dist_ds_str}[/green]"
            else:
                dist_ds_str = f"[red]{dist_ds_str}[/red]"

            und_table.add_row(
                ticker,
                f"${initial:,.2f}",
                f"${current:,.2f}",
                pct_str,
                dist_coupon_str,
                dist_ds_str,
            )
        else:
            und_table.add_row(
                ticker,
                f"${initial:,.2f}",
                "[dim]N/A[/dim]",
                "[dim]N/A[/dim]",
                "[dim]N/A[/dim]",
                "[dim]N/A[/dim]",
            )

    console.print(und_table)

    # --- Coupon summary ---
    coupon_stmt = (
        select(CouponEvent)
        .where(CouponEvent.instrument_id == instrument.id)
        .order_by(CouponEvent.evaluation_date)
    )
    coupon_events = list(session.execute(coupon_stmt).scalars().all())

    paid_count = sum(1 for e in coupon_events if e.is_paid)
    missed_count = sum(1 for e in coupon_events if not e.is_paid)
    total_income = sum(e.coupon_amount for e in coupon_events if e.is_paid and e.coupon_amount)

    coupon_summary = (
        f"Coupons: [green]{paid_count} paid[/green], "
        f"[red]{missed_count} missed[/red]  |  "
        f"Total income: [bold green]${total_income:,.2f}[/bold green]"
    )
    console.print(Panel(coupon_summary, title="Coupon Summary", border_style="green"))

    # --- Next valuation date ---
    from datetime import date as date_type

    next_vd_stmt = (
        select(ValuationDate)
        .where(
            ValuationDate.instrument_id == instrument.id,
            ValuationDate.date > date_type.today(),
        )
        .order_by(ValuationDate.date)
        .limit(1)
    )
    next_vd = session.execute(next_vd_stmt).scalar_one_or_none()
    if next_vd is not None:
        ac_tag = " [yellow](autocall eligible)[/yellow]" if next_vd.autocall_eligible else ""
        console.print(
            f"  Next valuation date: [bold cyan]{next_vd.date}[/bold cyan] "
            f"(#{next_vd.sequence_number}){ac_tag}"
        )
    else:
        console.print("  [dim]No upcoming valuation dates.[/dim]")

    # --- Position info ---
    pos = None
    if user_id is not None:
        pos_stmt = select(PortfolioPosition).where(
            PortfolioPosition.instrument_id == instrument.id,
            PortfolioPosition.user_id == user_id,
        )
        pos = session.execute(pos_stmt).scalar_one_or_none()
    else:
        # Show all positions
        for p in instrument.positions:
            console.print(
                f"  Position ({p.user.name}): principal [bold]${p.principal:,.2f}[/bold], "
                f"{p.num_notes} note(s), purchased {p.purchase_date}"
            )
        if not instrument.positions:
            console.print("  [dim]No positions recorded.[/dim]")
        pos = None  # already printed

    if user_id is not None:
        if pos is not None:
            console.print(
                f"  Position: principal [bold]${pos.principal:,.2f}[/bold], "
                f"{pos.num_notes} note(s), purchased {pos.purchase_date}"
            )
        else:
            console.print("  [dim]No position recorded for this user.[/dim]")

    console.print()


def status(
    cusip: Optional[str] = typer.Option(
        None, "--cusip", "-c", help="Filter by CUSIP"
    ),
    user_name: Optional[str] = typer.Option(
        None, "--user", "-u", help="Filter by user name"
    ),
    account_id_filter: Optional[int] = typer.Option(
        None, "--account-id", "-a", help="Filter by account ID"
    ),
):
    """Show current status of instruments."""
    with get_session() as session:
        user_id: int | None = None
        if user_name is not None:
            user = session.execute(
                select(User).where(User.name == user_name)
            ).scalar_one_or_none()
            if user is None:
                console.print(f"[red]User '{user_name}' not found[/red]")
                return
            user_id = user.id

        # Validate account_id if provided
        if account_id_filter is not None:
            account = session.execute(
                select(Account).where(Account.id == account_id_filter)
            ).scalar_one_or_none()
            if account is None:
                console.print(f"[red]Account with id {account_id_filter} not found[/red]")
                return
            if user_id is not None and account.user_id != user_id:
                console.print(f"[red]Account {account_id_filter} does not belong to user '{user_name}'[/red]")
                return

        if account_id_filter is not None:
            # Filter by specific account
            stmt = (
                select(Instrument)
                .join(PortfolioPosition)
                .where(PortfolioPosition.account_id == account_id_filter)
                .order_by(Instrument.cusip)
            )
        elif user_id is not None:
            # Show instruments where this user has a position
            stmt = (
                select(Instrument)
                .join(PortfolioPosition)
                .where(PortfolioPosition.user_id == user_id)
                .order_by(Instrument.cusip)
            )
        else:
            stmt = select(Instrument).order_by(Instrument.cusip)

        if cusip is not None:
            stmt = stmt.where(Instrument.cusip == cusip)

        instruments = list(session.execute(stmt).scalars().all())

        if not instruments:
            if cusip:
                console.print(f"[red]No instrument found with CUSIP {cusip}[/red]")
            else:
                console.print("[dim]No instruments in database.[/dim]")
            return

        label = f"Showing {len(instruments)} instrument(s)"
        if user_name:
            label += f" for user {user_name}"
        if account_id_filter is not None:
            label += f" (account {account_id_filter})"
        console.print(f"[bold]{label}[/bold]\n")

        for inst in instruments:
            _display_instrument(session, inst, user_id)
