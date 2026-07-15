"""Polygon.io provider stub.

Not configured until POLYGON_API_KEY is set. Once it is, these functions
call Polygon's real REST endpoints -- no other file needs to change; the
router will automatically prefer this provider over Yahoo for every
capability it implements.
"""

import os
from datetime import datetime

import requests

from apis.base import HistoryResult, OptionChainResult, OptionContract, Quote

NAME = "polygon"
BASE_URL = "https://api.polygon.io"


def is_configured() -> bool:
    return bool(os.environ.get("POLYGON_API_KEY"))


def _api_key() -> str:
    return os.environ.get("POLYGON_API_KEY", "")


def get_quote(symbol: str) -> Quote | None:
    if not is_configured():
        return None
    try:
        resp = requests.get(
            f"{BASE_URL}/v2/aggs/ticker/{symbol}/prev",
            params={"apiKey": _api_key()},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results") or []
        if not results:
            return None
        bar = results[0]
        return Quote(
            symbol=symbol,
            price=float(bar["c"]),
            previous_close=float(bar["c"]),
            day_high=float(bar.get("h")) if bar.get("h") else None,
            day_low=float(bar.get("l")) if bar.get("l") else None,
            volume=float(bar.get("v")) if bar.get("v") else None,
            avg_volume=None,
            source=NAME,
        )
    except Exception:
        return None


def get_history(symbol: str, period: str = "1y", interval: str = "1d") -> HistoryResult | None:
    # TODO: wire up /v2/aggs/ticker/{symbol}/range/... once POLYGON_API_KEY is set.
    return None


def get_option_expirations(symbol: str) -> list[str] | None:
    # TODO: wire up /v3/reference/options/contracts once POLYGON_API_KEY is set.
    return None


def get_option_chain(symbol: str, expiration: str) -> OptionChainResult | None:
    # TODO: wire up /v3/snapshot/options/{symbol} once POLYGON_API_KEY is set.
    return None
