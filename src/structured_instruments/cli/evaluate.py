"""si evaluate [--date DATE] - Run coupon + autocall evaluation."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from structured_instruments.database import get_session
from structured_instruments.services.autocall_evaluator import (
    evaluate_all_pending_autocalls,
)
from structured_instruments.services.coupon_evaluator import evaluate_all_pending

console = Console()


def evaluate(
    date: Optional[str] = typer.Option(
        None, "--date", "-d", help="Specific date to evaluate (YYYY-MM-DD)"
    ),
):
    """Evaluate coupon payments and autocall conditions."""
    target_date = None
    if date is not None:
        try:
            target_date = datetime.strptime(date, "%Y-%m-%d").date()
        except ValueError:
            console.print("[red]Error:[/red] Invalid date format. Use YYYY-MM-DD.")
            raise typer.Exit(code=1)

    with get_session() as session:
        # --- Coupon evaluation ---
        console.print("[bold]Evaluating coupon payments ...[/bold]")
        coupon_events = evaluate_all_pending(session, target_date)

        if coupon_events:
            table = Table(title="Coupon Evaluation Results")
            table.add_column("Date", style="cyan", justify="center")
            table.add_column("CUSIP", style="white", justify="left")
            table.add_column("Status", justify="center")
            table.add_column("Amount", style="green", justify="right")
            table.add_column("Worst Performer", justify="left")

            for ev in coupon_events:
                status_str = (
                    "[green]PAID[/green]" if ev.is_paid else "[red]MISSED[/red]"
                )
                amount_str = (
                    f"${ev.coupon_amount:,.2f}" if ev.coupon_amount else "-"
                )
                worst = (
                    f"{ev.worst_performer_ticker} ({ev.worst_performer_pct:.1%})"
                    if ev.worst_performer_ticker
                    else "-"
                )
                cusip = ev.instrument.cusip if ev.instrument else "?"
                table.add_row(
                    str(ev.valuation_date.date),
                    cusip,
                    status_str,
                    amount_str,
                    worst,
                )

            console.print(table)
            console.print(
                f"[green]Evaluated {len(coupon_events)} coupon date(s).[/green]"
            )
        else:
            console.print("[dim]No pending coupon dates to evaluate.[/dim]")

        # --- Autocall evaluation ---
        console.print()
        console.print("[bold]Evaluating autocall conditions ...[/bold]")
        autocall_events = evaluate_all_pending_autocalls(session, target_date)

        if autocall_events:
            ac_table = Table(title="Autocall Evaluation Results")
            ac_table.add_column("Date", style="cyan", justify="center")
            ac_table.add_column("CUSIP", style="white", justify="left")
            ac_table.add_column("Result", justify="center")

            for ev in autocall_events:
                result_str = (
                    "[bold green]CALLED[/bold green]"
                    if ev.is_called
                    else "[dim]Not Called[/dim]"
                )
                cusip = ev.instrument.cusip if ev.instrument else "?"
                ac_table.add_row(
                    str(ev.review_date),
                    cusip,
                    result_str,
                )

            console.print(ac_table)
            console.print(
                f"[green]Evaluated {len(autocall_events)} autocall date(s).[/green]"
            )
        else:
            console.print("[dim]No pending autocall dates to evaluate.[/dim]")
