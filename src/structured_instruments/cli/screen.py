"""si screen <candidates.json> - Rank prospective notes with a Monte Carlo model."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from structured_instruments.database import get_session
from structured_instruments.services.candidates import list_candidates, to_screen_note
from structured_instruments.services.market_signals import compute_signals
from structured_instruments.services.note_screener import (
    TaxAssumptions,
    load_candidates,
    load_held_notes,
    screen_candidates,
)

console = Console()

# Flag a note when real history was much harsher than the simulation.
REPLAY_RETURN_GAP = 0.03
REPLAY_LOSS_GAP = 0.10


def _pct(value: float | None, fmt: str = "{:.0%}") -> str:
    return "—" if value is None else fmt.format(value)


def _signals_table(tickers: list[str], barriers: dict[str, float]) -> Table:
    signals = compute_signals(tickers)
    table = Table(title="Ticker diagnostics (context only — not inputs to the valuation)")
    table.add_column("Ticker", style="cyan")
    table.add_column("Last", justify="right")
    table.add_column("52w range", justify="right")
    table.add_column("Pos", justify="right")
    table.add_column("Off high", justify="right")
    table.add_column("MACD", justify="right")
    table.add_column("200d", justify="right")
    table.add_column("Vol-profile support", justify="right")
    table.add_column("Put-OI wall", justify="right")
    table.add_column("Barrier if struck today", justify="right")

    for t in tickers:
        s = signals[t]
        if s.macd_bullish is None:
            macd = "—"
        else:
            macd = f"[green]bull[/green] {s.days_since_cross}d" if s.macd_bullish else f"[red]bear[/red] {s.days_since_cross}d"
        above = "—" if s.above_200dma is None else ("[green]above[/green]" if s.above_200dma else "[red]below[/red]")
        vol_sup = "—" if s.volume_support is None else f"${s.volume_support:,.2f} ({s.volume_support / s.last - 1:+.0%})"
        put_sup = "—" if s.put_oi_support is None else f"${s.put_oi_support:,.2f} ({s.put_oi_support / s.last - 1:+.0%})"
        barrier = barriers[t] * s.last
        table.add_row(
            t,
            f"${s.last:,.2f}",
            f"${s.low_52w:,.2f}–${s.high_52w:,.2f}",
            f"{s.range_position:.0%}",
            f"{s.off_high:+.0%}",
            macd,
            above,
            vol_sup,
            put_sup,
            f"${barrier:,.2f} ({barriers[t] - 1:+.0%})",
        )
    return table


def screen(
    candidates: Optional[Path] = typer.Argument(None, help="Candidates JSON (see data/candidates/); omit to use --month"),
    month: Optional[str] = typer.Option(None, help="Screen this month's candidates from the database (YYYY-MM)"),
    account_id: Optional[list[int]] = typer.Option(None, help="Score against this account's active notes (repeatable)"),
    stake: float = typer.Option(10_000, help="Dollar amount per candidate for portfolio-fit metrics"),
    coupon_tax: float = typer.Option(0.408, help="Tax rate on coupons (ordinary income + NIIT)"),
    state_tax: float = typer.Option(0.0, help="State income tax rate on coupons"),
    loss_tax: float = typer.Option(0.238, help="Tax value of a capital loss (0 if no gains to offset)"),
    erp: float = typer.Option(0.05, help="Equity risk premium for the real-world drift"),
    reversal: float = typer.Option(0.0, help="Rebound tilt: first-year drift += -reversal x recent loss"),
    reversal_signal: str = typer.Option("3m", help="Recent loss measure for --reversal: '3m' return or '52w' (off 52-week high)"),
    signals: bool = typer.Option(True, help="Show per-ticker 52w range / MACD / support diagnostics"),
    paths: int = typer.Option(50_000, help="Monte Carlo paths"),
) -> None:
    """Rank candidate notes by expected after-tax return per year at risk."""
    if candidates is not None:
        _, notes = load_candidates(candidates)
    elif month is not None:
        session = get_session()
        try:
            notes = [to_screen_note(c) for c in list_candidates(session, month)]
        finally:
            session.close()
        if not notes:
            console.print(f"[red]No candidates for {month}[/red]")
            raise typer.Exit(code=1)
    else:
        console.print("[red]Pass a candidates JSON file or --month[/red]")
        raise typer.Exit(code=1)
    tax = TaxAssumptions(coupon_rate=coupon_tax, capital_loss_rate=loss_tax, state_rate=state_tax)

    held = []
    if account_id:
        session = get_session()
        try:
            held = load_held_notes(session, account_id)
        finally:
            session.close()

    with console.status(f"Simulating {len(notes)} candidates + {len(held)} held notes, replaying history..."):
        risk_free, market, book, results = screen_candidates(
            notes, tax, held=held, stake=stake, equity_risk_premium=erp,
            reversal=reversal, reversal_signal=reversal_signal, n_paths=paths,
        )

    if book is not None:
        top = sorted(book.concentration.items(), key=lambda kv: -kv[1])[:5]
        console.print(
            f"[bold]Existing book[/bold]: ${book.principal:,.0f} in {len(book.notes)} notes  |  "
            f"expected after-tax P&L ${book.expected_aftertax_pnl:+,.0f}  |  5% CVaR ${book.cvar_5_aftertax:,.0f}  |  "
            f"P(any breach) {book.prob_any_breach:.0%}"
        )
        console.print("  Name exposure: " + ", ".join(f"{t} {s:.0%}" for t, s in top))
        for h in book.notes:
            levels = ", ".join(f"{t} {p:.0%}" for t, p in zip(h.tickers, h.current_pct))
            console.print(f"  {h.cusip} ${h.principal:,.0f}: {levels} (CB {h.coupon_barrier_pct:.0%}, DB {h.downside_barrier_pct:.0%})")

    table = Table(title=(
        f"Candidate screen (r={risk_free:.2%}, coupon tax={coupon_tax + state_tax:.1%}, "
        f"loss tax={loss_tax:.1%}, reversal={reversal} on {reversal_signal})"
    ))
    table.add_column("CUSIP", style="cyan")
    table.add_column("Basket")
    table.add_column("Cpn", justify="right")
    table.add_column("DB", justify="right")
    table.add_column("FV", justify="right")
    table.add_column("MC P(loss)", justify="right")
    table.add_column("Loss|br", justify="right")
    table.add_column("MC AT/yr", justify="right")
    table.add_column("Hist P(loss)", justify="right")
    table.add_column("Hist AT/yr", justify="right")
    table.add_column("Hist worst", justify="right")
    table.add_column("Hist starts", justify="right")
    if book is not None:
        table.add_column("ρ book", justify="right")
        table.add_column("P(br|tail)", justify="right")
        table.add_column("Tail add", justify="right")
        table.add_column("Max name", justify="right")
        table.add_column("Overlap", style="yellow")

    after_tax_cash = risk_free * (1 - coupon_tax - state_tax)

    def colored(value: float) -> str:
        s = f"{value:+.1%}"
        return f"[green]{s}[/green]" if value > after_tax_cash else f"[red]{s}[/red]"

    for r in results:
        n = r.note
        rp = r.replay
        flag = ""
        if rp is not None and (
            rp.aftertax_return_per_year < r.aftertax_return_per_year - REPLAY_RETURN_GAP
            or rp.prob_principal_loss > r.prob_principal_loss + REPLAY_LOSS_GAP
        ):
            flag = " [bold red]![/bold red]"
        row = [
            n.cusip + flag,
            " ".join(n.tickers),
            f"{n.coupon_rate_annual:.1%}",
            f"{n.downside_barrier_pct:.0%}",
            f"${r.fair_value:,.0f}",
            f"{r.prob_principal_loss:.0%}",
            f"-${r.expected_loss_given_breach:,.0f}",
            colored(r.aftertax_return_per_year),
            _pct(rp.prob_principal_loss) if rp else "—",
            colored(rp.aftertax_return_per_year) if rp else "—",
            f"{'-' if rp.worst_aftertax_pnl < 0 else '+'}${abs(rp.worst_aftertax_pnl):,.0f}" if rp else "—",
            f"{rp.first_start:%Y}–{rp.last_start:%Y}" if rp else "too short",
        ]
        if book is not None:
            name, share = r.max_concentration
            row += [
                f"{r.corr_with_book:.2f}",
                f"{r.prob_breach_in_book_tail:.0%}",
                f"${r.delta_book_cvar:,.0f}",
                f"{name} {share:.0%}",
                " ".join(r.overlap_tickers),
            ]
        table.add_row(*row)
    console.print(table)
    console.print(
        f"After-tax T-bill hurdle: {after_tax_cash:.2%}/yr. MC = Monte Carlo on implied vols; Hist = the note's terms "
        "replayed over every real 2-year window of its basket (overlapping windows — a few regimes, not independent "
        f"trials). [bold red]![/bold red] = history much harsher than MC. FV, Loss|br, Hist worst per $1,000. "
        f"ρ book / P(br|tail) / Tail add use a ${stake:,.0f} stake."
    )

    if signals:
        tickers = list(dict.fromkeys(t for r in results for t in r.note.tickers))
        # Lowest downside barrier per ticker across candidates, as a fraction of today's price.
        barriers: dict[str, float] = {}
        for r in results:
            for t in r.note.tickers:
                barriers[t] = min(barriers.get(t, 1.0), r.note.downside_barrier_pct)
        with console.status("Computing ticker diagnostics..."):
            console.print(_signals_table(tickers, barriers))
