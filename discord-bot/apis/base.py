"""Shared data contracts for every market-data provider.

Every provider module (yahoo.py, polygon.py, tradier.py, alpaca.py,
finnhub.py, benzinga.py) exposes the same function names and returns these
same dataclasses (or `None` when data truly isn't available). This is what
lets `apis/router.py` fall back from one provider to the next, and lets a
new paid provider be "plugged in" later just by filling in its module and
adding an API key -- no changes needed anywhere else in the bot.

None of these fields are ever fabricated. A provider function returns
`None` (or omits an optional field) rather than guessing a value.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

import pandas as pd


@dataclass
class Quote:
    symbol: str
    price: float
    previous_close: Optional[float]
    day_high: Optional[float]
    day_low: Optional[float]
    volume: Optional[float]
    avg_volume: Optional[float]
    source: str
    # When this price was actually observed (UTC). Required for staleness
    # checks -- a provider that can't supply a real timestamp should leave
    # this None rather than guessing "now".
    as_of: Optional[datetime] = None
    # An independent second reading of the price (e.g. a different endpoint
    # or timeframe from the same provider), used to cross-check the primary
    # price above before it's trusted. Left None if no second reading exists.
    cross_check_price: Optional[float] = None


@dataclass
class HistoryResult:
    df: pd.DataFrame  # columns: Open, High, Low, Close, Volume
    source: str


@dataclass
class OptionContract:
    option_type: str  # "call" | "put"
    strike: float
    expiration: str
    bid: float
    ask: float
    last_price: float
    volume: int
    open_interest: int
    implied_vol: float
    source: str


@dataclass
class OptionChainResult:
    expirations: list[str]
    calls: list[OptionContract]
    puts: list[OptionContract]
    source: str


@dataclass
class NewsItem:
    title: str
    published_at: Optional[datetime]
    url: Optional[str]
    source: str


@dataclass
class AnalystAction:
    firm: Optional[str]
    action: Optional[str]  # "Upgrade" | "Downgrade" | "Initiated" | None
    to_grade: Optional[str]
    from_grade: Optional[str]
    action_date: Optional[date]
    source: str


@dataclass
class EarningsInfo:
    earnings_date: Optional[date]
    eps_estimate: Optional[float]
    revenue_estimate: Optional[float]
    source: str


@dataclass
class InsiderTransaction:
    insider: str
    transaction_type: str
    shares: Optional[float]
    value: Optional[float]
    transaction_date: Optional[date]
    source: str


@dataclass
class SecFiling:
    filing_type: str
    filing_date: Optional[date]
    url: Optional[str]
    source: str


class ProviderUnavailableError(Exception):
    """Raised internally when a provider can't serve a capability. The
    router catches this and tries the next provider in priority order."""
