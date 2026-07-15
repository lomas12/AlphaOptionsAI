"""Tradier provider stub.

Not configured until TRADIER_API_KEY is set. Tradier is a strong candidate
for real-time options chains (including greeks) -- once configured, wire
`get_option_chain` to GET /v1/markets/options/chains.
"""

import os

import requests

from apis.base import HistoryResult, OptionChainResult, OptionContract, Quote

NAME = "tradier"
BASE_URL = "https://api.tradier.com/v1"


def is_configured() -> bool:
    return bool(os.environ.get("TRADIER_API_KEY"))


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {os.environ.get('TRADIER_API_KEY', '')}",
        "Accept": "application/json",
    }


def get_quote(symbol: str) -> Quote | None:
    if not is_configured():
        return None
    try:
        resp = requests.get(
            f"{BASE_URL}/markets/quotes",
            params={"symbols": symbol},
            headers=_headers(),
            timeout=10,
        )
        resp.raise_for_status()
        quote = resp.json().get("quotes", {}).get("quote")
        if not quote:
            return None
        return Quote(
            symbol=symbol,
            price=float(quote["last"]),
            previous_close=float(quote.get("prevclose")) if quote.get("prevclose") else None,
            day_high=float(quote.get("high")) if quote.get("high") else None,
            day_low=float(quote.get("low")) if quote.get("low") else None,
            volume=float(quote.get("volume")) if quote.get("volume") else None,
            avg_volume=float(quote.get("average_volume")) if quote.get("average_volume") else None,
            source=NAME,
        )
    except Exception:
        return None


def get_history(symbol: str, period: str = "1y", interval: str = "1d") -> HistoryResult | None:
    # TODO: wire up /v1/markets/history once TRADIER_API_KEY is set.
    return None


def get_option_expirations(symbol: str) -> list[str] | None:
    if not is_configured():
        return None
    try:
        resp = requests.get(
            f"{BASE_URL}/markets/options/expirations",
            params={"symbol": symbol},
            headers=_headers(),
            timeout=10,
        )
        resp.raise_for_status()
        dates = resp.json().get("expirations", {}).get("date")
        if not dates:
            return None
        return dates if isinstance(dates, list) else [dates]
    except Exception:
        return None


def get_option_chain(symbol: str, expiration: str) -> OptionChainResult | None:
    if not is_configured():
        return None
    try:
        resp = requests.get(
            f"{BASE_URL}/markets/options/chains",
            params={"symbol": symbol, "expiration": expiration, "greeks": "true"},
            headers=_headers(),
            timeout=10,
        )
        resp.raise_for_status()
        options = resp.json().get("options", {}).get("option") or []
    except Exception:
        return None

    calls, puts = [], []
    for opt in options:
        contract = OptionContract(
            option_type=opt.get("option_type", ""),
            strike=float(opt.get("strike", 0)),
            expiration=expiration,
            bid=float(opt.get("bid") or 0),
            ask=float(opt.get("ask") or 0),
            last_price=float(opt.get("last") or 0),
            volume=int(opt.get("volume") or 0),
            open_interest=int(opt.get("open_interest") or 0),
            implied_vol=float((opt.get("greeks") or {}).get("mid_iv") or 0),
            source=NAME,
        )
        (calls if contract.option_type == "call" else puts).append(contract)

    if not calls and not puts:
        return None
    return OptionChainResult(expirations=[expiration], calls=calls, puts=puts, source=NAME)
