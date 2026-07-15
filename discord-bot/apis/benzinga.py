"""Benzinga provider stub.

Not configured until BENZINGA_API_KEY is set. Benzinga is a strong
candidate for SEC filings, analyst ratings, and unusual-options-activity
feeds once configured.
"""

import os

import requests

from apis.base import AnalystAction, NewsItem, SecFiling

NAME = "benzinga"
BASE_URL = "https://api.benzinga.com/api/v2"


def is_configured() -> bool:
    return bool(os.environ.get("BENZINGA_API_KEY"))


def get_news(symbol: str, limit: int = 8) -> list[NewsItem] | None:
    # TODO: wire up /news once BENZINGA_API_KEY is set.
    return None


def get_analyst_action(symbol: str) -> AnalystAction | None:
    # TODO: wire up /calendar/ratings once BENZINGA_API_KEY is set.
    return None


def get_sec_filings(symbol: str, limit: int = 5) -> list[SecFiling] | None:
    # TODO: wire up SEC filings feed once BENZINGA_API_KEY is set.
    return None
