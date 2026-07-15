"""Market-wide context: SPY/QQQ/IWM trend, VIX, Treasury yield, Dollar
Index, sector rotation, and relative strength. Every field comes from a
live provider call; unavailable data is `None`, never guessed.
"""

from dataclasses import dataclass
from typing import Optional

from apis import router

INDEX_SYMBOLS = {"spy": "SPY", "qqq": "QQQ", "iwm": "IWM"}
SECTOR_ETFS = {
    "Technology": "XLK",
    "Financials": "XLF",
    "Energy": "XLE",
    "Healthcare": "XLV",
    "Industrials": "XLI",
    "Consumer Discretionary": "XLY",
    "Consumer Staples": "XLP",
    "Utilities": "XLU",
    "Materials": "XLB",
    "Real Estate": "XLRE",
    "Communication Services": "XLC",
}


@dataclass
class MarketContext:
    spy_trend: Optional[str]
    qqq_trend: Optional[str]
    iwm_trend: Optional[str]
    vix_level: Optional[float]
    vix_classification: Optional[str]
    treasury_10y_yield: Optional[float]
    dollar_index: Optional[float]
    sector_rotation: list[tuple[str, float]]  # (sector name, 1mo % change), best-first
    breadth_note: str  # honest note: breadth requires premium data


def _index_trend(symbol: str) -> Optional[str]:
    history_result = router.get_history(symbol, period="2mo", interval="1d")
    if not history_result.available:
        return None
    hist = history_result.value.df
    closes = hist["Close"].dropna()
    if len(closes) < 20:
        return None
    price = float(closes.iloc[-1])
    ema20 = float(closes.ewm(span=20, adjust=False).mean().iloc[-1])
    if price > ema20 * 1.002:
        return "Bullish"
    if price < ema20 * 0.998:
        return "Bearish"
    return "Neutral"


def _pct_change(symbol: str, period: str = "1mo") -> Optional[float]:
    history_result = router.get_history(symbol, period=period, interval="1d")
    if not history_result.available:
        return None
    closes = history_result.value.df["Close"].dropna()
    if len(closes) < 2:
        return None
    return round(float((closes.iloc[-1] - closes.iloc[0]) / closes.iloc[0] * 100), 2)


def get_market_context() -> MarketContext:
    spy_trend = _index_trend(INDEX_SYMBOLS["spy"])
    qqq_trend = _index_trend(INDEX_SYMBOLS["qqq"])
    iwm_trend = _index_trend(INDEX_SYMBOLS["iwm"])

    vix_quote = router.get_quote("^VIX")
    vix_level = vix_quote.value.price if vix_quote.available else None
    vix_classification = None
    if vix_level is not None:
        if vix_level < 15:
            vix_classification = "Low"
        elif vix_level < 25:
            vix_classification = "Normal"
        else:
            vix_classification = "Elevated"

    treasury_quote = router.get_quote("^TNX")
    treasury_10y_yield = treasury_quote.value.price if treasury_quote.available else None

    dollar_quote = router.get_quote("DX-Y.NYB")
    dollar_index = dollar_quote.value.price if dollar_quote.available else None

    sector_rotation = []
    for sector_name, etf in SECTOR_ETFS.items():
        change = _pct_change(etf)
        if change is not None:
            sector_rotation.append((sector_name, change))
    sector_rotation.sort(key=lambda x: x[1], reverse=True)

    return MarketContext(
        spy_trend=spy_trend,
        qqq_trend=qqq_trend,
        iwm_trend=iwm_trend,
        vix_level=vix_level,
        vix_classification=vix_classification,
        treasury_10y_yield=treasury_10y_yield,
        dollar_index=dollar_index,
        sector_rotation=sector_rotation,
        breadth_note="Market breadth (advance/decline) requires a premium data feed -- data unavailable from API.",
    )


def get_relative_strength(symbol: str, benchmark: str = "SPY", period: str = "3mo") -> Optional[float]:
    """Ticker's % change minus benchmark's % change over the period -- a
    simple, transparent relative-strength proxy."""
    symbol_change = _pct_change(symbol, period)
    benchmark_change = _pct_change(benchmark, period)
    if symbol_change is None or benchmark_change is None:
        return None
    return round(symbol_change - benchmark_change, 2)
