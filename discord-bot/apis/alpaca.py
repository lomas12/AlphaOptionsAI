"""Alpaca provider stub.

Not configured until ALPACA_API_KEY_ID and ALPACA_API_SECRET_KEY are set.
Alpaca is best suited for real-time equity quotes/bars; it does not offer
an options chain endpoint on the standard market-data plan.
"""

import os

import requests

from apis.base import HistoryResult, Quote

NAME = "alpaca"
DATA_URL = "https://data.alpaca.markets"


def is_configured() -> bool:
    return bool(os.environ.get("ALPACA_API_KEY_ID") and os.environ.get("ALPACA_API_SECRET_KEY"))


def _headers() -> dict:
    return {
        "APCA-API-KEY-ID": os.environ.get("ALPACA_API_KEY_ID", ""),
        "APCA-API-SECRET-KEY": os.environ.get("ALPACA_API_SECRET_KEY", ""),
    }


def get_quote(symbol: str) -> Quote | None:
    if not is_configured():
        return None
    try:
        resp = requests.get(
            f"{DATA_URL}/v2/stocks/{symbol}/quotes/latest",
            headers=_headers(),
            timeout=10,
        )
        resp.raise_for_status()
        quote = resp.json().get("quote")
        if not quote:
            return None
        price = float(quote.get("ap") or quote.get("bp") or 0)
        if price <= 0:
            return None
        return Quote(
            symbol=symbol,
            price=price,
            previous_close=None,
            day_high=None,
            day_low=None,
            volume=None,
            avg_volume=None,
            source=NAME,
        )
    except Exception:
        return None


def get_history(symbol: str, period: str = "1y", interval: str = "1d") -> HistoryResult | None:
    # TODO: wire up /v2/stocks/{symbol}/bars once ALPACA_API_KEY_ID/SECRET are set.
    return None
