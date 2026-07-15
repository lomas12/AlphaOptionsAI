"""Finnhub provider stub.

Not configured until FINNHUB_API_KEY is set. Finnhub is a strong candidate
for news, analyst actions, and insider transactions once configured.
"""

import os
from datetime import datetime, timezone

import requests

from apis.base import AnalystAction, InsiderTransaction, NewsItem, Quote

NAME = "finnhub"
BASE_URL = "https://finnhub.io/api/v1"


def is_configured() -> bool:
    return bool(os.environ.get("FINNHUB_API_KEY"))


def _params(extra: dict) -> dict:
    return {**extra, "token": os.environ.get("FINNHUB_API_KEY", "")}


def get_quote(symbol: str) -> Quote | None:
    if not is_configured():
        return None
    try:
        resp = requests.get(f"{BASE_URL}/quote", params=_params({"symbol": symbol}), timeout=10)
        resp.raise_for_status()
        data = resp.json()
        price = data.get("c")
        if not price:
            return None
        return Quote(
            symbol=symbol,
            price=float(price),
            previous_close=float(data["pc"]) if data.get("pc") else None,
            day_high=float(data["h"]) if data.get("h") else None,
            day_low=float(data["l"]) if data.get("l") else None,
            volume=None,
            avg_volume=None,
            source=NAME,
        )
    except Exception:
        return None


def get_news(symbol: str, limit: int = 8) -> list[NewsItem] | None:
    if not is_configured():
        return None
    try:
        resp = requests.get(
            f"{BASE_URL}/company-news",
            params=_params({"symbol": symbol, "from": "2020-01-01", "to": "2030-01-01"}),
            timeout=10,
        )
        resp.raise_for_status()
        items = resp.json() or []
    except Exception:
        return None
    if not items:
        return None

    news = []
    for item in items[:limit]:
        published_at = None
        if item.get("datetime"):
            published_at = datetime.fromtimestamp(item["datetime"], tz=timezone.utc)
        news.append(NewsItem(title=item.get("headline", ""), published_at=published_at, url=item.get("url"), source=NAME))
    return news or None


def get_analyst_action(symbol: str) -> AnalystAction | None:
    # TODO: wire up /stock/upgrade-downgrade once FINNHUB_API_KEY is set.
    return None


def get_insider_transactions(symbol: str, limit: int = 10) -> list[InsiderTransaction] | None:
    # TODO: wire up /stock/insider-transactions once FINNHUB_API_KEY is set.
    return None
