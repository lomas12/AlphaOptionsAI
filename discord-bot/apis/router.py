"""Provider router: tries each data provider in priority order and returns
the first real result. This is the ONLY place that knows about provider
priority -- add a new provider by dropping a module in apis/ with matching
function names, then adding it to PROVIDERS below.

Priority: Polygon.io > Tradier > Alpaca > Finnhub > Benzinga > Yahoo Finance.
Yahoo is last because it's the only one that needs no API key, making it
the guaranteed fallback.
"""

import logging
from typing import Any, Callable, Optional

from apis import alpaca, benzinga, finnhub, polygon, tradier, yahoo

logger = logging.getLogger("alphaoptionsai.apis")

PROVIDERS = [polygon, tradier, alpaca, finnhub, benzinga, yahoo]


class DataResult:
    """Wraps a value with which provider actually served it (or None if no
    provider had it) -- callers use this to show 'Data unavailable from
    API' instead of silently omitting a field."""

    def __init__(self, value: Any, source: Optional[str]):
        self.value = value
        self.source = source

    @property
    def available(self) -> bool:
        return self.value is not None


def _call_in_priority_order(method_name: str, *args, **kwargs) -> DataResult:
    for provider in PROVIDERS:
        if not getattr(provider, "is_configured", lambda: False)():
            continue
        func: Optional[Callable] = getattr(provider, method_name, None)
        if func is None:
            continue
        try:
            result = func(*args, **kwargs)
        except Exception as exc:
            logger.warning("Provider %s.%s failed: %s", provider.NAME, method_name, exc)
            continue
        if result is not None:
            return DataResult(result, provider.NAME)
    return DataResult(None, None)


def get_quote(symbol: str) -> DataResult:
    return _call_in_priority_order("get_quote", symbol)


def get_history(symbol: str, period: str = "1y", interval: str = "1d") -> DataResult:
    return _call_in_priority_order("get_history", symbol, period, interval)


def get_option_expirations(symbol: str) -> DataResult:
    return _call_in_priority_order("get_option_expirations", symbol)


def get_option_chain(symbol: str, expiration: str) -> DataResult:
    return _call_in_priority_order("get_option_chain", symbol, expiration)


def get_news(symbol: str, limit: int = 8) -> DataResult:
    return _call_in_priority_order("get_news", symbol, limit)


def get_analyst_action(symbol: str) -> DataResult:
    return _call_in_priority_order("get_analyst_action", symbol)


def get_earnings_info(symbol: str) -> DataResult:
    return _call_in_priority_order("get_earnings_info", symbol)


def get_insider_transactions(symbol: str, limit: int = 10) -> DataResult:
    return _call_in_priority_order("get_insider_transactions", symbol, limit)


def get_sec_filings(symbol: str, limit: int = 5) -> DataResult:
    return _call_in_priority_order("get_sec_filings", symbol, limit)


def configured_providers() -> list[str]:
    return [p.NAME for p in PROVIDERS if getattr(p, "is_configured", lambda: False)()]
