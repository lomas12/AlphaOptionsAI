"""Sector Rotation Engine: ranks the 11 major S&P sectors by relative
strength vs SPY (real ETF price data, batched download) and boosts/damps
per-trade confidence based on the ticker's sector rank.
"""

import logging
import threading
import time as time_module
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from core import database
from core.market import SECTOR_ETFS  # single source of truth for the 11 sectors

logger = logging.getLogger("alphaoptionsai.sectors")

CACHE_TTL_SECONDS = 30 * 60
SECTOR_REFETCH_DAYS = 7  # how often to re-check a ticker whose sector lookup failed

# Yahoo `info["sector"]` names -> our canonical SPDR sector names
_YAHOO_SECTOR_MAP = {
    "Technology": "Technology",
    "Healthcare": "Healthcare",
    "Financial Services": "Financials",
    "Financial": "Financials",
    "Energy": "Energy",
    "Industrials": "Industrials",
    "Utilities": "Utilities",
    "Consumer Defensive": "Consumer Staples",
    "Consumer Cyclical": "Consumer Discretionary",
    "Basic Materials": "Materials",
    "Communication Services": "Communication Services",
    "Real Estate": "Real Estate",
}


@dataclass
class SectorRank:
    sector: str
    etf: str
    rank: int                      # 1 = strongest
    score: float                   # blended relative-strength score
    ret_1m_pct: Optional[float]
    ret_3m_pct: Optional[float]
    rel_1m_pct: Optional[float]    # vs SPY
    rel_3m_pct: Optional[float]    # vs SPY
    above_ema50: Optional[bool]


@dataclass
class SectorRankings:
    ranks: list[SectorRank]
    spy_ret_1m_pct: Optional[float]
    as_of: str
    unavailable: list[str]


_cache_lock = threading.Lock()
_cached: Optional[SectorRankings] = None
_cached_at: float = 0.0


def compute_sector_rankings() -> SectorRankings:
    import pandas as pd
    import yfinance as yf

    symbols = list(SECTOR_ETFS.values()) + ["SPY"]
    closes_by_symbol: dict = {}
    unavailable: list[str] = []
    try:
        df = yf.download(symbols, period="6mo", interval="1d", group_by="ticker", progress=False, threads=True, auto_adjust=True)
        for sym in symbols:
            try:
                sub = df[sym] if isinstance(df.columns, pd.MultiIndex) else df
                closes = sub["Close"].dropna()
                if len(closes) >= 63:
                    closes_by_symbol[sym] = closes
                else:
                    unavailable.append(sym)
            except Exception:
                unavailable.append(sym)
    except Exception as exc:
        logger.error("Sector data download failed: %s", exc)
        unavailable = symbols

    def pct_ret(closes, sessions: int) -> Optional[float]:
        if len(closes) <= sessions:
            return None
        return float((closes.iloc[-1] / closes.iloc[-sessions - 1] - 1) * 100)

    spy_1m = pct_ret(closes_by_symbol["SPY"], 21) if "SPY" in closes_by_symbol else None
    spy_3m = pct_ret(closes_by_symbol["SPY"], 63) if "SPY" in closes_by_symbol else None

    entries: list[SectorRank] = []
    for sector, etf in SECTOR_ETFS.items():
        closes = closes_by_symbol.get(etf)
        if closes is None:
            continue
        ret_1m = pct_ret(closes, 21)
        ret_3m = pct_ret(closes, 63)
        rel_1m = round(ret_1m - spy_1m, 2) if (ret_1m is not None and spy_1m is not None) else None
        rel_3m = round(ret_3m - spy_3m, 2) if (ret_3m is not None and spy_3m is not None) else None
        ema50 = float(closes.ewm(span=50, adjust=False).mean().iloc[-1])
        above = bool(float(closes.iloc[-1]) > ema50)
        # Blend: recent relative strength dominates, structure breaks ties.
        score = 0.0
        score += (rel_1m if rel_1m is not None else (ret_1m or 0.0)) * 0.55
        score += (rel_3m if rel_3m is not None else (ret_3m or 0.0)) * 0.30
        score += 1.5 if above else -1.5
        entries.append(SectorRank(
            sector=sector, etf=etf, rank=0, score=round(score, 2),
            ret_1m_pct=round(ret_1m, 2) if ret_1m is not None else None,
            ret_3m_pct=round(ret_3m, 2) if ret_3m is not None else None,
            rel_1m_pct=rel_1m, rel_3m_pct=rel_3m, above_ema50=above,
        ))

    entries.sort(key=lambda e: e.score, reverse=True)
    for i, entry in enumerate(entries, start=1):
        entry.rank = i

    return SectorRankings(
        ranks=entries,
        spy_ret_1m_pct=round(spy_1m, 2) if spy_1m is not None else None,
        as_of=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        unavailable=unavailable,
    )


def get_sector_rankings(max_age_seconds: int = CACHE_TTL_SECONDS) -> SectorRankings:
    global _cached, _cached_at
    with _cache_lock:
        if _cached is not None and (time_module.monotonic() - _cached_at) < max_age_seconds:
            return _cached
    fresh = compute_sector_rankings()
    with _cache_lock:
        if fresh.ranks or _cached is None:
            _cached, _cached_at = fresh, time_module.monotonic()
        return _cached


def get_ticker_sector(symbol: str) -> Optional[str]:
    """Ticker -> canonical sector name, cached in SQLite. Returns None when
    Yahoo has no sector for it (ETFs, indexes) — callers apply no boost then."""
    cached = database.get_ticker_sector(symbol)
    if cached is not None:
        sector, fetched_at = cached
        if sector:
            return sector
        try:
            fetched = datetime.fromisoformat(fetched_at)
        except ValueError:
            fetched = datetime.now(timezone.utc)
        if datetime.now(timezone.utc) - fetched < timedelta(days=SECTOR_REFETCH_DAYS):
            return None  # known-missing, don't hammer the API

    try:
        import yfinance as yf
        raw = yf.Ticker(symbol).info.get("sector")
    except Exception:
        raw = None
    sector = _YAHOO_SECTOR_MAP.get(raw) if raw else None
    database.set_ticker_sector(symbol, sector)
    return sector


def confidence_boost(sector: Optional[str], rankings: SectorRankings) -> tuple[float, Optional[str]]:
    """Bounded (±4) confidence adjustment from the sector's current rank."""
    if not sector or not rankings.ranks:
        return 0.0, None
    entry = next((r for r in rankings.ranks if r.sector == sector), None)
    if entry is None:
        return 0.0, None
    total = len(rankings.ranks)
    if entry.rank <= 3:
        boost = {1: 4.0, 2: 3.0, 3: 2.0}[entry.rank]
        return boost, f"{sector} is the #{entry.rank} sector ({entry.rel_1m_pct:+.1f}% vs SPY, 1mo): +{boost:g}"
    if entry.rank >= total - 2:
        boost = {0: -4.0, 1: -3.0, 2: -2.0}[total - entry.rank]
        return boost, f"{sector} is ranked #{entry.rank}/{total} ({entry.rel_1m_pct:+.1f}% vs SPY, 1mo): {boost:g}"
    return 0.0, f"{sector} is mid-pack (#{entry.rank}/{total}) — no sector adjustment"
