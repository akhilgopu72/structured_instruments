"""Candidate note screening service.

Monte Carlo model for comparing prospective worst-of autocallable contingent
income notes before purchase. All underlyings (the candidates' and those of
notes already held) are simulated jointly on one set of correlated monthly
paths, so each candidate is scored both on its own and on what it does to the
existing book.

Per candidate it reports:

- Fair value per $1,000 under the risk-neutral measure (how much of the
  coupon is real compensation vs. issuer margin).
- Expected after-tax return per year of capital at risk under a real-world
  drift (coupons taxed as ordinary income, principal losses as capital
  losses), plus probability and severity of principal loss.
- Portfolio fit: correlation of the note's P&L with the existing book's,
  probability it breaches when the book is already in its worst decile,
  change in the book's 5% CVaR from adding the stake, and the largest
  single-name concentration after purchase.

Existing notes are simulated from their *current* level vs. their own
strikes, while a candidate starts fresh at its pricing-date strike. That is
how the model sees "entry price": a name that has fallen hard is close to the
barriers of notes already held, but a new note on it gets a fresh 50-60%
cushion. Whether the fall itself predicts a rebound is a separate, optional
assumption (``reversal``), off by default.

Volatility comes from listed option implied vols (skew-aware: the average of
the ATM vol and the vol struck at 50% moneyness), falling back to realized
vol when no chain is available. Correlations and betas come from one year of
daily returns.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from sqlalchemy import select
from sqlalchemy.orm import Session

from structured_instruments.models.instrument import Instrument
from structured_instruments.models.position import PortfolioPosition
from structured_instruments.models.price import DailyPrice
from structured_instruments.models.valuation_date import ValuationDate

MONTHS_PER_YEAR = 12
DAYS_PER_MONTH = 365.25 / 12
REALIZED_VOL_FALLBACK_MULTIPLIER = 1.15  # implied usually trades above realized
BARRIER_MONEYNESS = 0.5  # strike used for the skew leg of the simulation vol


@dataclass
class CandidateNote:
    cusip: str
    issuer: str
    tickers: list[str]
    coupon_rate_annual: float
    coupon_barrier_pct: float
    downside_barrier_pct: float
    autocall_barrier_pct: float = 1.0
    num_observations: int = 24
    first_autocall_observation: int = 3


@dataclass
class HeldNote:
    """An active position, positioned at today's levels vs. its own strikes."""
    cusip: str
    principal: float
    tickers: list[str]
    current_pct: list[float]  # latest close / initial price, per ticker
    coupon_rate_monthly: float
    coupon_barrier_pct: float
    downside_barrier_pct: float
    autocall_barrier_pct: float
    obs_months: list[int]  # month index (1-based from today) of each remaining observation
    obs_autocall: list[bool]


@dataclass
class TaxAssumptions:
    # Coupons are ordinary income (not qualified dividends): federal top
    # bracket + 3.8% NIIT by default.
    coupon_rate: float = 0.408
    # Value of a capital loss on a breached note. 23.8% assumes there are
    # long-term gains elsewhere to offset; use 0 if there are none (only $3k/yr
    # is deductible against ordinary income).
    capital_loss_rate: float = 0.238
    state_rate: float = 0.0


@dataclass
class MarketInputs:
    tickers: list[str]
    sigma: np.ndarray  # simulation vol per ticker
    implied_atm: list[float | None]
    implied_barrier: list[float | None]
    realized_vol: np.ndarray
    dividend_yield: np.ndarray
    beta: np.ndarray
    corr: np.ndarray
    three_month_return: np.ndarray
    off_52w_high: np.ndarray

    def index(self, tickers: list[str]) -> list[int]:
        return [self.tickers.index(t) for t in tickers]


@dataclass
class ScreenResult:
    note: CandidateNote
    sigma: list[float]
    fair_value: float
    prob_autocall: float
    expected_life_years: float
    expected_coupons: float
    prob_principal_loss: float
    expected_loss_given_breach: float
    pretax_return_per_year: float
    aftertax_return_per_year: float
    cvar_5_aftertax: float
    # Portfolio fit (None when there is no existing book)
    corr_with_book: float | None = None
    prob_breach_in_book_tail: float | None = None
    delta_book_cvar: float | None = None
    max_concentration: tuple[str, float] | None = None
    overlap_tickers: list[str] = field(default_factory=list)
    replay: ReplayResult | None = None


@dataclass
class ReplayResult:
    """The note's terms applied to every real 2-year window of its basket."""
    windows: int
    first_start: date
    last_start: date
    prob_principal_loss: float
    prob_autocall: float
    aftertax_return_per_year: float
    worst_aftertax_pnl: float  # per $1,000


@dataclass
class BookSummary:
    principal: float
    notes: list[HeldNote]
    expected_aftertax_pnl: float
    cvar_5_aftertax: float
    prob_any_breach: float
    concentration: dict[str, float]


def load_candidates(path: Path) -> tuple[date, list[CandidateNote]]:
    """Load a candidates JSON file (see data/candidates/)."""
    raw = json.loads(path.read_text())
    pricing_date = datetime.strptime(raw["pricing_date"], "%Y-%m-%d").date()
    return pricing_date, [CandidateNote(**n) for n in raw["notes"]]


def load_held_notes(session: Session, account_ids: list[int], today: date | None = None) -> list[HeldNote]:
    """Active positions in *account_ids* that still have observations ahead."""
    today = today or date.today()
    stmt = (
        select(PortfolioPosition)
        .join(Instrument)
        .where(PortfolioPosition.account_id.in_(account_ids), Instrument.status == "active")
    )
    held: list[HeldNote] = []
    for pos in session.execute(stmt).scalars().all():
        inst = pos.instrument
        future = list(session.execute(
            select(ValuationDate)
            .where(ValuationDate.instrument_id == inst.id, ValuationDate.date > today)
            .order_by(ValuationDate.date)
        ).scalars().all())
        if not future:
            continue  # past final valuation but never settled — nothing left to simulate

        tickers, current_pct = [], []
        for iu in inst.underlyings:
            latest = session.execute(
                select(DailyPrice.close)
                .where(DailyPrice.underlying_id == iu.underlying_id)
                .order_by(DailyPrice.date.desc())
                .limit(1)
            ).scalar_one_or_none()
            if latest is None:
                break
            tickers.append(iu.underlying.ticker)
            current_pct.append(float(latest) / iu.initial_price)
        else:
            obs_months = [max(1, round((vd.date - today).days / DAYS_PER_MONTH)) for vd in future]
            held.append(HeldNote(
                cusip=inst.cusip,
                principal=pos.principal,
                tickers=tickers,
                current_pct=current_pct,
                coupon_rate_monthly=inst.coupon_rate_monthly,
                coupon_barrier_pct=inst.coupon_barrier_pct,
                downside_barrier_pct=inst.downside_barrier_pct,
                autocall_barrier_pct=inst.autocall_barrier_pct,
                obs_months=obs_months,
                obs_autocall=[vd.autocall_eligible for vd in future],
            ))
    return held


def get_risk_free_rate() -> float:
    """13-week T-bill yield, falling back to 4%."""
    try:
        irx = yf.Ticker("^IRX").history(period="5d")["Close"]
        if not irx.empty:
            return float(irx.iloc[-1]) / 100
    except Exception:
        pass
    return 0.04


def _implied_vol_at(ticker: str, spot: float, moneyness: list[float], target_years: float) -> list[float | None]:
    """Interpolate put implied vol at each moneyness from the listed expiry
    closest to *target_years* out. Returns None entries when unavailable."""
    try:
        t = yf.Ticker(ticker)
        expiries = t.options
        if not expiries:
            return [None] * len(moneyness)
        today = date.today()
        expiry = min(
            expiries,
            key=lambda e: abs((datetime.strptime(e, "%Y-%m-%d").date() - today).days / 365.25 - target_years),
        )
        puts = t.option_chain(expiry).puts
        puts = puts[
            (puts["impliedVolatility"] > 0.05)
            & (puts["strike"] >= 0.3 * spot)
            & (puts["strike"] <= 1.1 * spot)
        ].sort_values("strike")
        if len(puts) < 2:
            return [None] * len(moneyness)
        k = (puts["strike"] / spot).to_numpy()
        iv = puts["impliedVolatility"].to_numpy()
        return [float(np.interp(m, k, iv)) for m in moneyness]
    except Exception:
        return [None] * len(moneyness)


def _nearest_psd(corr: np.ndarray) -> np.ndarray:
    vals, vecs = np.linalg.eigh(corr)
    vals = np.clip(vals, 1e-6, None)
    fixed = vecs @ np.diag(vals) @ vecs.T
    d = np.sqrt(np.diag(fixed))
    return fixed / np.outer(d, d)


def fetch_history(tickers: list[str]) -> tuple[pd.DataFrame, dict[str, float]]:
    """Two years of adjusted closes (plus SPY) and trailing-12m dividend yields."""
    all_tickers = sorted(set(tickers) | {"SPY"})
    df = yf.download(all_tickers, period="2y", progress=False, auto_adjust=True)["Close"]

    dividends: dict[str, float] = {}
    for t in tickers:
        try:
            divs = yf.Ticker(t).dividends
            if divs.empty:
                dividends[t] = 0.0
                continue
            cutoff = divs.index.max() - pd.Timedelta(days=365)
            trailing = float(divs[divs.index > cutoff].sum())
            dividends[t] = trailing / float(df[t].dropna().iloc[-1])
        except Exception:
            dividends[t] = 0.0
    return df, dividends


def load_market_inputs(tickers: list[str], term_years: float = 2.0) -> MarketInputs:
    """Build joint vol / correlation / beta inputs for every ticker."""
    history, dividends = fetch_history(tickers)
    closes = history[tickers + ["SPY"]].dropna(how="all")
    rets = np.log(closes / closes.shift(1)).iloc[1:]
    last_year = rets.iloc[-252:]

    realized = last_year[tickers].std().to_numpy() * np.sqrt(252)
    # Pairs with no overlapping history (recent IPOs) get a generic 0.3.
    corr = _nearest_psd(last_year[tickers].corr(min_periods=40).fillna(0.3).to_numpy())
    np.fill_diagonal(corr, 1.0)

    spy = last_year["SPY"]
    beta = np.array([
        last_year[t].cov(spy) / spy.var() if last_year[t].notna().sum() > 40 else 1.5
        for t in tickers
    ])

    filled = closes[tickers].ffill()
    spots = filled.iloc[-1]
    three_month = (spots / filled.iloc[-63] - 1).to_numpy()
    off_high = (spots / filled.iloc[-252:].max() - 1).to_numpy()

    implied_atm: list[float | None] = []
    implied_barrier: list[float | None] = []
    sigma = np.empty(len(tickers))
    for i, t in enumerate(tickers):
        atm, at_barrier = _implied_vol_at(t, float(spots[t]), [1.0, BARRIER_MONEYNESS], term_years)
        implied_atm.append(atm)
        implied_barrier.append(at_barrier)
        if atm is not None and at_barrier is not None:
            sigma[i] = 0.5 * (atm + at_barrier)
        else:
            sigma[i] = realized[i] * REALIZED_VOL_FALLBACK_MULTIPLIER

    return MarketInputs(
        tickers=tickers,
        sigma=sigma,
        implied_atm=implied_atm,
        implied_barrier=implied_barrier,
        realized_vol=realized,
        dividend_yield=np.array([dividends.get(t, 0.0) for t in tickers]),
        beta=beta,
        corr=corr,
        three_month_return=three_month,
        off_52w_high=off_high,
    )


def simulate_growth(
    market: MarketInputs,
    drift: np.ndarray,
    num_months: int,
    n_paths: int,
    seed: int,
) -> np.ndarray:
    """Return (n_paths, num_months, n_tickers) gross growth S_t / S_today."""
    rng = np.random.default_rng(seed)
    dt = 1 / MONTHS_PER_YEAR
    chol = np.linalg.cholesky(market.corr)
    z = rng.standard_normal((n_paths, num_months, len(market.tickers))) @ chol.T
    step = (drift - 0.5 * market.sigma**2) * dt + market.sigma * np.sqrt(dt) * z
    return np.exp(np.cumsum(step, axis=1))


def _note_cash_flows(
    worst: np.ndarray,
    obs_months: np.ndarray,
    autocall_eligible: np.ndarray,
    coupon: float,
    coupon_barrier: float,
    downside_barrier: float,
    autocall_barrier: float,
    principal: float,
    tax: TaxAssumptions,
) -> dict[str, np.ndarray]:
    """Per-path cash flows for one note.

    *worst* is (n_paths, n_obs) worst-of level vs. initial at each remaining
    observation. Cash flows are returned as (n_paths, n_obs) matrices aligned
    to *obs_months*.
    """
    n_paths, n_obs = worst.shape
    rows = np.arange(n_paths)

    called = (worst >= autocall_barrier) & autocall_eligible[None, :]
    is_called = called.any(axis=1)
    term_idx = np.where(is_called, called.argmax(axis=1), n_obs - 1)

    alive = np.arange(n_obs)[None, :] <= term_idx[:, None]
    coupons = np.where((worst >= coupon_barrier) & alive, coupon, 0.0)

    final_level = worst[rows, term_idx]
    breached = (~is_called) & (final_level < downside_barrier)
    redemption = np.where(breached, principal * final_level, principal)
    principal_loss = principal - redemption

    pretax = coupons.copy()
    pretax[rows, term_idx] += redemption

    aftertax = coupons * (1 - tax.coupon_rate - tax.state_rate)
    aftertax[rows, term_idx] += redemption + principal_loss * tax.capital_loss_rate

    return {
        "pretax": pretax,
        "aftertax": aftertax,
        "coupons": coupons,
        "term_years": obs_months[term_idx] / MONTHS_PER_YEAR,
        "is_called": is_called,
        "breached": breached,
        "principal_loss": principal_loss,
    }


def _candidate_flows(note: CandidateNote, market: MarketInputs, growth: np.ndarray, tax: TaxAssumptions) -> dict:
    worst = growth[:, : note.num_observations, market.index(note.tickers)].min(axis=2)
    obs = np.arange(1, note.num_observations + 1)
    return _note_cash_flows(
        worst,
        obs,
        obs >= note.first_autocall_observation,
        1000 * note.coupon_rate_annual / MONTHS_PER_YEAR,
        note.coupon_barrier_pct,
        note.downside_barrier_pct,
        note.autocall_barrier_pct,
        1000.0,
        tax,
    )


def _held_flows(note: HeldNote, market: MarketInputs, growth: np.ndarray, tax: TaxAssumptions) -> dict:
    months = np.array(note.obs_months)
    levels = growth[:, months - 1, :][:, :, market.index(note.tickers)] * np.array(note.current_pct)
    return _note_cash_flows(
        levels.min(axis=2),
        months,
        np.array(note.obs_autocall),
        note.principal * note.coupon_rate_monthly,
        note.coupon_barrier_pct,
        note.downside_barrier_pct,
        note.autocall_barrier_pct,
        note.principal,
        tax,
    )


TRADING_DAYS_PER_MONTH = 21
MIN_REPLAY_WINDOWS = 120  # ~6 months of start dates


def fetch_replay_history(tickers: list[str]) -> pd.DataFrame:
    """Full split-adjusted (not dividend-adjusted) closes: note holders don't
    receive dividends, so price return is what the barriers see."""
    return yf.download(sorted(set(tickers)), period="max", progress=False, auto_adjust=False)["Close"]


def replay_note(note: CandidateNote, closes: pd.DataFrame, tax: TaxAssumptions) -> ReplayResult | None:
    """Apply *note* to every historical start date with a full term after it.

    Windows overlap heavily (one per trading day), so the result reflects a
    handful of distinct market regimes, not thousands of independent trials.
    Returns None when the basket's shared history is too short.
    """
    basket = closes[note.tickers].dropna()
    prices = basket.to_numpy()
    span = note.num_observations * TRADING_DAYS_PER_MONTH
    n_starts = len(prices) - span
    if n_starts < MIN_REPLAY_WINDOWS:
        return None

    obs_offsets = np.arange(1, note.num_observations + 1) * TRADING_DAYS_PER_MONTH
    starts = np.arange(n_starts)
    levels = prices[starts[:, None] + obs_offsets[None, :]] / prices[starts][:, None, :]
    worst = levels.min(axis=2)

    obs = np.arange(1, note.num_observations + 1)
    flows = _note_cash_flows(
        worst,
        obs,
        obs >= note.first_autocall_observation,
        1000 * note.coupon_rate_annual / MONTHS_PER_YEAR,
        note.coupon_barrier_pct,
        note.downside_barrier_pct,
        note.autocall_barrier_pct,
        1000.0,
        tax,
    )
    aftertax_pnl = flows["aftertax"].sum(axis=1) - 1000
    return ReplayResult(
        windows=n_starts,
        first_start=basket.index[0].date(),
        last_start=basket.index[n_starts - 1].date(),
        prob_principal_loss=float(flows["breached"].mean()),
        prob_autocall=float(flows["is_called"].mean()),
        aftertax_return_per_year=float(aftertax_pnl.mean() / 1000 / flows["term_years"].mean()),
        worst_aftertax_pnl=float(aftertax_pnl.min()),
    )


def _cvar(pnl: np.ndarray, q: float = 0.05) -> float:
    return float(np.sort(pnl)[: max(1, int(len(pnl) * q))].mean())


def _concentration(exposures: list[tuple[list[str], float]]) -> dict[str, float]:
    """Share of principal exposed to each ticker. Worst-of notes put the whole
    principal at risk to every name in the basket, so shares can sum > 100%."""
    total = sum(p for _, p in exposures)
    out: dict[str, float] = {}
    for tickers, principal in exposures:
        for t in tickers:
            out[t] = out.get(t, 0.0) + principal / total
    return out


def screen_candidates(
    notes: list[CandidateNote],
    tax: TaxAssumptions,
    held: list[HeldNote] | None = None,
    stake: float = 10_000,
    equity_risk_premium: float = 0.05,
    reversal: float = 0.0,
    reversal_signal: str = "3m",
    issuer_spread: float = 0.01,
    n_paths: int = 50_000,
    seed: int = 7,
) -> tuple[float, MarketInputs, BookSummary | None, list[ScreenResult]]:
    """Screen all candidates against the existing book.

    *reversal* tilts each name's first-year drift by ``-reversal x`` its
    recent loss — the trailing 3-month return (``reversal_signal="3m"``) or
    the distance below its 52-week high (``"52w"``). E.g. 0.5 and a -40%
    signal adds +20%/yr for a year. 0 means no view that losers rebound.

    Returns (risk_free_rate, market, book summary, results sorted by after-tax
    return per year, best first).
    """
    held = held or []
    tickers = sorted({t for n in notes for t in n.tickers} | {t for h in held for t in h.tickers})
    market = load_market_inputs(tickers)
    risk_free = get_risk_free_rate()
    horizon = max([n.num_observations for n in notes] + [max(h.obs_months) for h in held])

    rn_growth = simulate_growth(market, risk_free - market.dividend_yield, horizon, n_paths, seed)

    rw_drift = risk_free + market.beta * equity_risk_premium - market.dividend_yield
    rw_growth = simulate_growth(market, rw_drift, horizon, n_paths, seed + 1)
    if reversal:
        signal = market.off_52w_high if reversal_signal == "52w" else market.three_month_return
        tilt = np.clip(-reversal * signal, -0.5, 0.5)
        months = np.minimum(np.arange(1, horizon + 1), MONTHS_PER_YEAR) / MONTHS_PER_YEAR
        rw_growth = rw_growth * np.exp(months[None, :, None] * tilt[None, None, :])

    book_pnl = np.zeros(n_paths)
    book: BookSummary | None = None
    if held:
        any_breach = np.zeros(n_paths, dtype=bool)
        for h in held:
            flows = _held_flows(h, market, rw_growth, tax)
            book_pnl += flows["aftertax"].sum(axis=1) - h.principal
            any_breach |= flows["breached"]
        book = BookSummary(
            principal=sum(h.principal for h in held),
            notes=held,
            expected_aftertax_pnl=float(book_pnl.mean()),
            cvar_5_aftertax=_cvar(book_pnl),
            prob_any_breach=float(any_breach.mean()),
            concentration=_concentration([(h.tickers, h.principal) for h in held]),
        )
        book_tail = book_pnl <= np.quantile(book_pnl, 0.10)

    replay_closes = fetch_replay_history([t for n in notes for t in n.tickers])

    results: list[ScreenResult] = []
    for note in notes:
        rn = _candidate_flows(note, market, rn_growth, tax)
        obs_years = np.arange(1, note.num_observations + 1) / MONTHS_PER_YEAR
        fair_value = float((rn["pretax"] * np.exp(-(risk_free + issuer_spread) * obs_years)).sum(axis=1).mean())

        rw = _candidate_flows(note, market, rw_growth, tax)
        expected_life = float(rw["term_years"].mean())
        pretax_pnl = rw["pretax"].sum(axis=1) - 1000
        aftertax_pnl = rw["aftertax"].sum(axis=1) - 1000
        breached = rw["breached"]

        result = ScreenResult(
            note=note,
            sigma=[float(market.sigma[i]) for i in market.index(note.tickers)],
            fair_value=fair_value,
            prob_autocall=float(rw["is_called"].mean()),
            expected_life_years=expected_life,
            expected_coupons=float((rw["coupons"] > 0).sum(axis=1).mean()),
            prob_principal_loss=float(breached.mean()),
            expected_loss_given_breach=float(rw["principal_loss"][breached].mean()) if breached.any() else 0.0,
            # Dollar-years basis, consistent with services/performance.py.
            pretax_return_per_year=float(pretax_pnl.mean() / 1000 / expected_life),
            aftertax_return_per_year=float(aftertax_pnl.mean() / 1000 / expected_life),
            cvar_5_aftertax=_cvar(aftertax_pnl),
            replay=replay_note(note, replay_closes, tax),
        )

        if book is not None:
            scaled = aftertax_pnl * stake / 1000
            result.corr_with_book = float(np.corrcoef(scaled, book_pnl)[0, 1])
            result.prob_breach_in_book_tail = float(breached[book_tail].mean())
            # Extra dollars lost in the book's worst 5% of outcomes once the
            # stake is added (positive = deeper tail).
            result.delta_book_cvar = book.cvar_5_aftertax - _cvar(book_pnl + scaled)
            conc = _concentration([(h.tickers, h.principal) for h in held] + [(note.tickers, stake)])
            result.max_concentration = max(conc.items(), key=lambda kv: kv[1])
            result.overlap_tickers = sorted(set(note.tickers) & set(book.concentration))
        results.append(result)

    results.sort(key=lambda r: r.aftertax_return_per_year, reverse=True)
    return risk_free, market, book, results
