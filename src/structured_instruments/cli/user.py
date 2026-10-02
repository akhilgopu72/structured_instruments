"""si user add/list - Manage users."""
from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table
from sqlalchemy import select

from structured_instruments.database import get_session
from structured_instruments.models.user import User

console = Console()
user_app = typer.Typer(help="Manage users")


@user_app.command("add")
def add_user(
    name: str = typer.Argument(..., help="User name"),
):
    """Create a new user."""
    with get_session() as session:
        existing = session.execute(
            select(User).where(User.name == name)
        ).scalar_one_or_none()
        if existing:
            console.print(f"[yellow]User '{name}' already exists (id={existing.id})[/yellow]")
            return

        user = User(name=name)
        session.add(user)
        session.commit()
        session.refresh(user)
        console.print(f"[green]Created user '{user.name}' (id={user.id})[/green]")


@user_app.command("list")
def list_users():
    """List all users."""
    with get_session() as session:
        users = list(session.execute(select(User).order_by(User.id)).scalars().all())

        if not users:
            console.print("[dim]No users in database.[/dim]")
            return

        table = Table(title="Users")
        table.add_column("ID", style="dim", justify="right")
        table.add_column("Name", style="cyan")

        for u in users:
            table.add_row(str(u.id), u.name)

        console.print(table)
