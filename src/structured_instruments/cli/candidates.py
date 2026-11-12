"""si candidates / si gmail - manage offered notes and the Gmail feed."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from structured_instruments.database import get_session
from structured_instruments.services import gmail_ingest
from structured_instruments.services.candidates import import_json, list_candidates

console = Console()

candidates_app = typer.Typer(help="Offered notes being considered (Modeling tab)")
gmail_app = typer.Typer(help="Pull offering emails from Gmail into candidates")


@candidates_app.command("import")
def import_candidates(path: Path = typer.Argument(..., help="Candidates JSON (see data/candidates/)")) -> None:
    """Load hand-entered candidates from a JSON file."""
    session = get_session()
    try:
        added, skipped = import_json(session, path)
    finally:
        session.close()
    console.print(f"Added {added}, skipped {skipped} already present.")


@candidates_app.command("list")
def list_cmd(month: Optional[str] = typer.Option(None, help="YYYY-MM")) -> None:
    """Show candidates."""
    session = get_session()
    try:
        rows = list_candidates(session, month)
        table = Table(title=f"Candidates{f' ({month})' if month else ''}")
        for col in ("Month", "CUSIP", "Issuer", "Basket", "Cpn", "CB", "DB", "Source", "Review"):
            table.add_column(col)
        for c in rows:
            table.add_row(
                c.offering_month, c.cusip, c.issuer, " ".join(c.ticker_list),
                f"{c.coupon_rate_annual:.2%}", f"{c.coupon_barrier_pct:.0%}", f"{c.downside_barrier_pct:.0%}",
                c.source, c.review_notes or "",
            )
        console.print(table)
    finally:
        session.close()


@gmail_app.command("auth")
def gmail_auth() -> None:
    """One-time browser consent for read-only Gmail access."""
    gmail_ingest.authorize()
    console.print(f"[green]Connected.[/green] Token saved to {gmail_ingest.TOKEN_FILE}")


@gmail_app.command("sync")
def gmail_sync() -> None:
    """Fetch new offering PDFs and add them as candidates."""
    session = get_session()
    try:
        with console.status("Checking Gmail and parsing new PDFs..."):
            result = gmail_ingest.sync_and_record(session)
    finally:
        session.close()
    console.print(f"Scanned {result.messages_seen} emails; added {len(result.added)}: {', '.join(result.added) or '-'}")
    if result.skipped_final:
        console.print(f"[yellow]Final prospectuses (use Add instead):[/yellow] {', '.join(result.skipped_final)}")
    for err in result.errors:
        console.print(f"[red]{err}[/red]")
