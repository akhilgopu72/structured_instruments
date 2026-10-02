import typer

from structured_instruments.database import init_db

app = typer.Typer(name="si", help="Structured Instruments monitoring CLI")


@app.callback()
def main():
    """Initialize database on startup."""
    init_db()


def register_commands():
    from structured_instruments.cli.add import add  # noqa: F401
    from structured_instruments.cli.prices import prices_app  # noqa: F401
    from structured_instruments.cli.evaluate import evaluate  # noqa: F401
    from structured_instruments.cli.status import status  # noqa: F401
    from structured_instruments.cli.serve import serve  # noqa: F401
    from structured_instruments.cli.user import user_app  # noqa: F401
    from structured_instruments.cli.account import account_app  # noqa: F401

    app.command()(add)
    app.add_typer(prices_app, name="prices")
    app.command()(evaluate)
    app.command()(status)
    app.command()(serve)
    app.add_typer(user_app, name="user")
    app.add_typer(account_app, name="account")


register_commands()
