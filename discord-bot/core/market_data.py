"""Pre-flight market data validation.

Before any recommendation is generated, we require a verified, fresh
current price -- never an estimate, a cached/stale value, or a hardcoded
number. This module:

1. Fetches a quote from the provider router.
2. Cross-checks the primary price against a second, independently
   timestamped reading from the same call (see `apis/yahoo.py`) -- if they
   disagree by more than a small tolerance, the quote is rejected.
3. Rejects quotes with no timestamp, or with a timestamp older than the
   staleness threshold while the market is open.
4. Retries (re-fetches) once before giving up.

If a valid, verified price still can't be produced, `get_verified_quote`
raises `MarketDataUnavailableError` -- callers must surface this as
"Market data unavailable" rather than falling back to a guessed price.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

from apis import router

logger = logging.getLogger("alphaoptionsai.market_data")

NY_TZ = ZoneInfo("America/New_York")
MARKET_OPEN = time(9, 30)
MARKET_CLOSE = time(16, 0)
STALE_THRESHOLD_MINUTES = 15
PRICE_MISMATCH_TOLERANCE_PCT = 1.5
MAX_FETCH_ATTEMPTS = 2


class MarketDataUnavailableError(Exception):
    """Raised when a verified, current price cannot be obtained. Callers
    must surface this as 'Market data unavailable' -- never fall back to
    an estimated, cached, or hardcoded price."""


@dataclass
class VerifiedQuote:
    symbol: str
    price: float
    source: str
    as_of: datetime  # UTC, always present on a verified quote


def _is_market_hours(now_utc: datetime) -> bool:
    now_et = now_utc.astimezone(NY_TZ)
    if now_et.weekday() >= 5:
        return False
    return MARKET_OPEN <= now_et.time() <= MARKET_CLOSE


def _validate(quote, now_utc: datetime) -> tuple[bool, str]:
    if quote is None or quote.price is None or quote.price <= 0:
        return False, "no price returned"

    if quote.as_of is None:
        return False, "quote has no verifiable timestamp"

    age_minutes = (now_utc - quote.as_of).total_seconds() / 60
    if age_minutes < -5:
        return False, "quote timestamp is in the future"
    if _is_market_hours(now_utc) and age_minutes > STALE_THRESHOLD_MINUTES:
        return False, f"quote is stale ({age_minutes:.0f} min old during market hours, limit {STALE_THRESHOLD_MINUTES})"

    if quote.cross_check_price is not None and quote.cross_check_price > 0:
        diff_pct = abs(quote.price - quote.cross_check_price) / quote.cross_check_price * 100
        if diff_pct > PRICE_MISMATCH_TOLERANCE_PCT:
            return False, f"price disagrees with latest market quote by {diff_pct:.2f}% (limit {PRICE_MISMATCH_TOLERANCE_PCT}%)"

    return True, ""


def get_verified_quote(symbol: str, *, now: datetime | None = None) -> VerifiedQuote:
    """Returns a verified, fresh current price or raises
    MarketDataUnavailableError. Never estimates or hardcodes a price."""
    now_utc = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)

    last_reason = "no data returned from any configured provider"
    for attempt in range(1, MAX_FETCH_ATTEMPTS + 1):
        quote_result = router.get_quote(symbol)
        quote = quote_result.value
        is_valid, reason = _validate(quote, now_utc)
        if is_valid:
            return VerifiedQuote(symbol=symbol, price=quote.price, source=quote.source, as_of=quote.as_of)
        last_reason = reason
        logger.warning("Quote validation attempt %s/%s for %s rejected: %s", attempt, MAX_FETCH_ATTEMPTS, symbol, last_reason)

    raise MarketDataUnavailableError(f"Market data unavailable for {symbol}: {last_reason}.")
