"""Per-ticker technical diagnostics for candidate screening.

These are context, not inputs to the note valuation: a note's barriers are
set off the pricing-date close, and its outcome is decided over two years,
well beyond the horizon where MACD or nearby support levels say much. They
help judge entry timing and sanity-check the simulation.

- 52-week range: low/high, where the last close sits in it, distance off the high.
- MACD (12/26/9 on daily closes): line vs. signal, days since the last cross,
  and whether price is above its 200-day average.
- Support: there is no free order-book feed (and resting orders only reflect
  the next minutes), so two proxies are used:
    * volume profile — the price band below the last close where the most
      volume traded over the past year;
    * put open-interest wall — the strike below spot with the most put open
      interest in the nearest monthly expiry 3+ weeks out.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

import numpy as np
import pandas as pd
import yfinance as yf

VOLUME_PROFILE_BINS = 30
# Ignore bands within this distance of the last close: after a selloff the
# heaviest volume is usually right at the current price, which says nothing
# about where buyers stepped in below it.
SUPPORT_MIN_DISTANCE = 0.03


@dataclass
class TickerSignals:
    ticker: str
    last: float
    low_52w: float
    high_52w: float
    range_position: float  # 0 = at 52w low, 1 = at 52w high
    off_high: float  # last / 52w high - 1
    macd_bullish: bool | None
    days_since_cross: int | None
    above_200dma: bool | None
    volume_support: float | None
    put_oi_support: float | None
    put_oi_expiry: str | None


def _macd(close: pd.Series) -> tuple[bool | None, int | None]:
    if len(close) < 35:
        return None, None
    line = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
    signal = line.ewm(span=9, adjust=False).mean()
    above = (line > signal).to_numpy()
    crosses = np.nonzero(above[1:] != above[:-1])[0]
    days = int(len(above) - 1 - (crosses[-1] + 1)) if len(crosses) else None
    return bool(above[-1]), days


def _volume_support(ohlcv: pd.DataFrame, last: float) -> float | None:
    """Midpoint of the highest-volume price band at least 3% below *last* over ~1 year."""
    year = ohlcv.iloc[-252:].dropna()
    if len(year) < 60:
        return None
    typical = (year["High"] + year["Low"] + year["Close"]) / 3
    edges = np.linspace(typical.min(), typical.max(), VOLUME_PROFILE_BINS + 1)
    idx = np.clip(np.digitize(typical, edges) - 1, 0, VOLUME_PROFILE_BINS - 1)
    vol_by_bin = np.bincount(idx, weights=year["Volume"].to_numpy(), minlength=VOLUME_PROFILE_BINS)
    mids = (edges[:-1] + edges[1:]) / 2
    below = mids < last * (1 - SUPPORT_MIN_DISTANCE)
    if not below.any():
        return None
    return float(mids[below][np.argmax(vol_by_bin[below])])


def _put_oi_support(ticker: str, spot: float) -> tuple[float | None, str | None]:
    try:
        t = yf.Ticker(ticker)
        today = date.today()
        expiries = [
            e for e in t.options
            if (datetime.strptime(e, "%Y-%m-%d").date() - today).days >= 21
        ]
        if not expiries:
            return None, None
        expiry = expiries[0]
        puts = t.option_chain(expiry).puts
        puts = puts[(puts["strike"] < spot) & (puts["openInterest"] > 0)]
        if puts.empty:
            return None, expiry
        return float(puts.loc[puts["openInterest"].idxmax(), "strike"]), expiry
    except Exception:
        return None, None


def compute_signals(tickers: list[str]) -> dict[str, TickerSignals]:
    data = yf.download(sorted(set(tickers)), period="2y", progress=False, auto_adjust=True, group_by="ticker")
    out: dict[str, TickerSignals] = {}
    for t in tickers:
        ohlcv = data[t].dropna(subset=["Close"])
        close = ohlcv["Close"]
        last = float(close.iloc[-1])
        year = close.iloc[-252:]
        lo, hi = float(year.min()), float(year.max())
        bullish, days = _macd(close)
        put_wall, expiry = _put_oi_support(t, last)
        out[t] = TickerSignals(
            ticker=t,
            last=last,
            low_52w=lo,
            high_52w=hi,
            range_position=(last - lo) / (hi - lo) if hi > lo else 0.5,
            off_high=last / hi - 1,
            macd_bullish=bullish,
            days_since_cross=days,
            above_200dma=bool(last > close.iloc[-200:].mean()) if len(close) >= 200 else None,
            volume_support=_volume_support(ohlcv, last),
            put_oi_support=put_wall,
            put_oi_expiry=expiry,
        )
    return out
