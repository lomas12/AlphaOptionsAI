"""Market-wide and per-ticker context: index trend, VIX, earnings, news
sentiment, and analyst actions. Every value here comes from a live yfinance
call -- if a source errors or is empty, the corresponding field is `None`
and the trade engine simply skips that factor instead of guessing.
"""

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Optional

import yfinance as yf

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
class MarketContext:
    spy_trend: Optional[str]
    qqq_trend: Optional[str]
    vix_level: Optional[float]
    vix_classification: Optional[str]


@dataclass
class TickerContext:
    earnings_date: Optional[date]
    days_to_earnings: Optional[int]
    news_sentiment: Optional[str]
    news_headlines: list[str]
    analyst_action: Optional[str]
    analyst_firm: Optional[str]


def _index_trend(symbol: str) -> Optional[str]:
    try:
        tk = yf.Ticker(symbol)
        hist = tk.history(period="2mo", interval="1d", auto_adjust=False)
        if hist is None or hist.empty or len(hist) < 20:
            return None
        closes = hist["Close"].dropna()
        price = float(closes.iloc[-1])
        ema20 = float(closes.ewm(span=20, adjust=False).mean().iloc[-1])
        if price > ema20 * 1.002:
            return "Bullish"
        if price < ema20 * 0.998:
            return "Bearish"
        return "Neutral"
    except Exception:
        return None


def get_market_context() -> MarketContext:
    spy_trend = _index_trend("SPY")
    qqq_trend = _index_trend("QQQ")

    vix_level: Optional[float] = None
    try:
        vix_tk = yf.Ticker("^VIX")
        fast_info = vix_tk.fast_info
        vix_level = float(fast_info.get("lastPrice")) if fast_info.get("lastPrice") else None
        if vix_level is None:
            hist = vix_tk.history(period="1d")
            if hist is not None and not hist.empty:
                vix_level = float(hist["Close"].iloc[-1])
    except Exception:
        vix_level = None

    vix_classification = None
    if vix_level is not None:
        if vix_level < 15:
            vix_classification = "Low"
        elif vix_level < 25:
            vix_classification = "Normal"
        else:
            vix_classification = "Elevated"

    return MarketContext(
        spy_trend=spy_trend,
        qqq_trend=qqq_trend,
        vix_level=vix_level,
        vix_classification=vix_classification,
    )


def _score_headline(title: str) -> int:
    words = {w.strip(".,!?:;'\"").lower() for w in title.split()}
    score = 0
    if words & POSITIVE_WORDS:
        score += 1
    if words & NEGATIVE_WORDS:
        score -= 1
    return score


def get_ticker_context(symbol: str) -> TickerContext:
    tk = yf.Ticker(symbol)

    earnings_date: Optional[date] = None
    try:
        calendar = tk.calendar
        raw_dates = calendar.get("Earnings Date") if calendar else None
        if raw_dates:
            earnings_date = raw_dates[0]
    except Exception:
        earnings_date = None

    days_to_earnings = None
    if earnings_date is not None:
        days_to_earnings = (earnings_date - datetime.now(timezone.utc).date()).days

    headlines: list[str] = []
    sentiment_score = 0
    try:
        news_items = tk.news or []
        for item in news_items[:8]:
            title = (item.get("content") or {}).get("title") or item.get("title")
            if not title:
                continue
            headlines.append(title)
            sentiment_score += _score_headline(title)
    except Exception:
        pass

    news_sentiment = None
    if headlines:
        if sentiment_score > 0:
            news_sentiment = "Positive"
        elif sentiment_score < 0:
            news_sentiment = "Negative"
        else:
            news_sentiment = "Neutral"

    analyst_action = None
    analyst_firm = None
    try:
        upgrades = tk.upgrades_downgrades
        if upgrades is not None and not upgrades.empty:
            recent = upgrades.sort_index(ascending=False).iloc[0]
            action = str(recent.get("Action", "")).lower()
            if action == "up":
                analyst_action = "Upgrade"
            elif action == "down":
                analyst_action = "Downgrade"
            analyst_firm = str(recent.get("Firm")) if recent.get("Firm") else None
    except Exception:
        pass

    return TickerContext(
        earnings_date=earnings_date,
        days_to_earnings=days_to_earnings,
        news_sentiment=news_sentiment,
        news_headlines=headlines[:3],
        analyst_action=analyst_action,
        analyst_firm=analyst_firm,
    )
