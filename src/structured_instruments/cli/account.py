"""si account add/list - Manage accounts."""
from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table
from sqlalchemy import select

from structured_instruments.database import get_session
from structured_instruments.models.account import Account
from structured_instruments.models.user import User

console = Console()
account_app = typer.Typer(help="Manage accounts")

VALID_ACCOUNT_TYPES = ["personal", "roth_ira", "traditional_ira", "401k"]


@account_app.command("add")
def add_account(
    user_name: str = typer.Option(..., "--user", "-u", help="User name"),
    name: str = typer.Option(..., "--name", "-n", help="Account name (e.g. 'Schwab Roth')"),
    account_type: str = typer.Option(..., "--type", "-t", help=f"Account type: {', '.join(VALID_ACCOUNT_TYPES)}"),
):
    """Create a new account for a user."""
    if account_type not in VALID_ACCOUNT_TYPES:
        console.print(f"[red]Invalid account type '{account_type}'. Must be one of: {', '.join(VALID_ACCOUNT_TYPES)}[/red]")
        raise typer.Exit(code=1)

    with get_session() as session:
        user = session.execute(
            select(User).where(User.name == user_name)
        ).scalar_one_or_none()
        if user is None:
            console.print(f"[red]User '{user_name}' not found[/red]")
            raise typer.Exit(code=1)

        existing = session.execute(
            select(Account).where(Account.user_id == user.id, Account.name == name)
        ).scalar_one_or_none()
        if existing:
            console.print(f"[yellow]Account '{name}' already exists for user '{user_name}' (id={existing.id})[/yellow]")
            return

        account = Account(user_id=user.id, name=name, account_type=account_type)
        session.add(account)
        session.commit()
        session.refresh(account)
        console.print(f"[green]Created account '{account.name}' (id={account.id}, type={account.account_type}) for user '{user_name}'[/green]")


@account_app.command("list")
def list_accounts(
    user_name: str = typer.Option(..., "--user", "-u", help="User name"),
):
    """List accounts for a user."""
    with get_session() as session:
        user = session.execute(
            select(User).where(User.name == user_name)
        ).scalar_one_or_none()
        if user is None:
            console.print(f"[red]User '{user_name}' not found[/red]")
            raise typer.Exit(code=1)

        accounts = list(
            session.execute(
                select(Account).where(Account.user_id == user.id).order_by(Account.id)
            ).scalars().all()
        )

        if not accounts:
            console.print(f"[dim]No accounts for user '{user_name}'.[/dim]")
            return

        table = Table(title=f"Accounts for {user_name}")
        table.add_column("ID", style="dim", justify="right")
        table.add_column("Name", style="cyan")
        table.add_column("Type", style="yellow")

        for a in accounts:
            table.add_row(str(a.id), a.name, a.account_type)

        console.print(table)
