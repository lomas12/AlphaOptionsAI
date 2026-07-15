"""News, analyst actions, insider activity, SEC filings, earnings, and a
transparent keyword-based sentiment score.

Real NLP sentiment analysis would require a paid API (Benzinga/Finnhub
sentiment endpoints); until one is configured this uses a keyword
heuristic on real headlines, clearly labeled as such.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from apis import router
from apis.base import AnalystAction, InsiderTransaction, NewsItem, SecFiling

POSITIVE_WORDS = {
    "beat", "beats", "surge", "surges", "soar", "soars", "rally", "rallies",
    "upgrade", "upgraded", "record", "growth", "outperform", "bullish",
    "strong", "gain", "gains", "jump", "jumps", "rise", "rises", "buy",
}
NEGATIVE_WORDS = {
    "miss", "misses", "plunge", "plunges", "crash", "crashes", "downgrade",
    "downgraded", "warning", "warns", "bearish", "weak", "loss", "losses",
    "fall", "falls", "drop", "drops", "sell", "lawsuit", "recall", "cut",
}


@dataclass
class TickerNewsContext:
    news_items: list[NewsItem]
    news_sentiment: Optional[str]
    sentiment_score: int
    analyst_action: Optional[AnalystAction]
    insider_transactions: list[InsiderTransaction]
    sec_filings: list[SecFiling]
    earnings_date_source: Optional[str]


def _score_headline(title: str) -> int:
    words = {w.strip(".,!?:;'\"").lower() for w in title.split()}
    score = 0
    if words & POSITIVE_WORDS:
        score += 1
    if words & NEGATIVE_WORDS:
        score -= 1
    return score


def get_ticker_news_context(symbol: str) -> TickerNewsContext:
    news_result = router.get_news(symbol, limit=8)
    news_items = news_result.value if news_result.available else []

    sentiment_score = sum(_score_headline(item.title) for item in news_items)
    news_sentiment = None
    if news_items:
        if sentiment_score > 0:
            news_sentiment = "Positive"
        elif sentiment_score < 0:
            news_sentiment = "Negative"
        else:
            news_sentiment = "Neutral"

    analyst_result = router.get_analyst_action(symbol)
    insider_result = router.get_insider_transactions(symbol, limit=10)
    filings_result = router.get_sec_filings(symbol, limit=5)

    return TickerNewsContext(
        news_items=news_items[:5],
        news_sentiment=news_sentiment,
        sentiment_score=sentiment_score,
        analyst_action=analyst_result.value if analyst_result.available else None,
        insider_transactions=insider_result.value if insider_result.available else [],
        sec_filings=filings_result.value if filings_result.available else [],
        earnings_date_source=None,
    )
