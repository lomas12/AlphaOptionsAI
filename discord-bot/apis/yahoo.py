"""Yahoo Finance provider (via yfinance). This is the only fully live,
unauthenticated provider today -- always available as the final fallback.
"""

import re
from datetime import datetime, timezone

import pandas as pd
import yfinance as yf

from apis.base import (
    AnalystAction,
    EarningsInfo,
    HistoryResult,
    InsiderTransaction,
    NewsItem,
    OptionChainResult,
    OptionContract,
    Quote,
    SecFiling,
)

NAME = "yahoo"


def is_configured() -> bool:
    return True  # No API key required.


def clean_ticker(raw: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", raw).upper()


def get_quote(symbol: str) -> Quote | None:
    """Fetch the current quote. A price is never trusted from a single
    unverified snapshot: we always also pull the latest 1-minute intraday
    bar (a second, independently-timestamped reading) so the caller can
    cross-check the two and know exactly when the price was observed.
    """
    tk = yf.Ticker(symbol)

    snapshot_price = None
    previous_close = None
    day_high = day_low = volume = avg_volume = None

    try:
        fast_info = tk.fast_info
        snapshot_price = fast_info.get("lastPrice") or fast_info.get("last_price")
        previous_close = fast_info.get("previousClose") or fast_info.get("previous_close")
        day_high = fast_info.get("dayHigh")
        day_low = fast_info.get("dayLow")
        volume = fast_info.get("lastVolume")
        avg_volume = fast_info.get("threeMonthAverageVolume")
    except Exception:
        pass

    if snapshot_price is None:
        try:
            info = tk.info
            snapshot_price = info.get("currentPrice") or info.get("regularMarketPrice")
            previous_close = previous_close or info.get("previousClose")
        except Exception:
            pass

    # Independent, timestamped reading -- the source of truth for "as_of"
    # and the cross-check for the snapshot price above.
    intraday_price = None
    intraday_as_of = None
    try:
        intraday = tk.history(period="2d", interval="1m")
        if intraday is not None and not intraday.empty:
            intraday_price = float(intraday["Close"].iloc[-1])
            ts = intraday.index[-1].to_pydatetime()
            intraday_as_of = ts.astimezone(timezone.utc) if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    except Exception:
        pass

    price = snapshot_price if snapshot_price is not None else intraday_price
    as_of = intraday_as_of
    cross_check_price = intraday_price if (snapshot_price is not None and intraday_price is not None) else None

    if price is None:
        try:
            daily = tk.history(period="5d", interval="1d")
            if daily is not None and not daily.empty:
                price = float(daily["Close"].iloc[-1])
                ts = daily.index[-1].to_pydatetime()
                as_of = ts.astimezone(timezone.utc) if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
        except Exception:
            pass

    if price is None:
        return None

    return Quote(
        symbol=symbol,
        price=float(price),
        previous_close=float(previous_close) if previous_close else None,
        day_high=float(day_high) if day_high else None,
        day_low=float(day_low) if day_low else None,
        volume=float(volume) if volume else None,
        avg_volume=float(avg_volume) if avg_volume else None,
        source=NAME,
        as_of=as_of,
        cross_check_price=cross_check_price,
    )


def get_history(symbol: str, period: str = "1y", interval: str = "1d") -> HistoryResult | None:
    tk = yf.Ticker(symbol)
    try:
        df = tk.history(period=period, interval=interval, auto_adjust=False)
    except Exception:
        return None
    if df is None or df.empty:
        return None
    return HistoryResult(df=df, source=NAME)


def get_option_expirations(symbol: str) -> list[str] | None:
    try:
        tk = yf.Ticker(symbol)
        expirations = tk.options
        return list(expirations) if expirations else None
    except Exception:
        return None


def get_option_chain(symbol: str, expiration: str) -> OptionChainResult | None:
    try:
        tk = yf.Ticker(symbol)
        chain = tk.option_chain(expiration)
    except Exception:
        return None

    def _rows(df: pd.DataFrame, option_type: str) -> list[OptionContract]:
        contracts = []
        for row in df.itertuples():
            try:
                contracts.append(
                    OptionContract(
                        option_type=option_type,
                        strike=float(row.strike),
                        expiration=expiration,
                        bid=float(row.bid) if not pd.isna(row.bid) else 0.0,
                        ask=float(row.ask) if not pd.isna(row.ask) else 0.0,
                        last_price=float(row.lastPrice) if not pd.isna(row.lastPrice) else 0.0,
                        volume=int(row.volume) if not pd.isna(row.volume) else 0,
                        open_interest=int(row.openInterest) if not pd.isna(row.openInterest) else 0,
                        implied_vol=float(row.impliedVolatility) if not pd.isna(row.impliedVolatility) else 0.0,
                        source=NAME,
                    )
                )
            except Exception:
                continue
        return contracts

    return OptionChainResult(
        expirations=[expiration],
        calls=_rows(chain.calls, "call"),
        puts=_rows(chain.puts, "put"),
        source=NAME,
    )


def get_news(symbol: str, limit: int = 8) -> list[NewsItem] | None:
    try:
        tk = yf.Ticker(symbol)
        items = tk.news or []
    except Exception:
        return None
    if not items:
        return None

    news: list[NewsItem] = []
    for item in items[:limit]:
        content = item.get("content") or {}
        title = content.get("title") or item.get("title")
        if not title:
            continue
        pub_raw = content.get("pubDate") or item.get("pubDate")
        published_at = None
        if pub_raw:
            try:
                published_at = datetime.fromisoformat(pub_raw.replace("Z", "+00:00"))
            except ValueError:
                published_at = None
        url = ((content.get("canonicalUrl") or {}).get("url")) or item.get("link")
        news.append(NewsItem(title=title, published_at=published_at, url=url, source=NAME))
    return news or None


def get_analyst_action(symbol: str) -> AnalystAction | None:
    try:
        tk = yf.Ticker(symbol)
        upgrades = tk.upgrades_downgrades
    except Exception:
        return None
    if upgrades is None or upgrades.empty:
        return None

    recent = upgrades.sort_index(ascending=False).iloc[0]
    action_raw = str(recent.get("Action", "")).lower()
    action = {"up": "Upgrade", "down": "Downgrade", "init": "Initiated"}.get(action_raw)
    action_date = None
    try:
        action_date = upgrades.sort_index(ascending=False).index[0].date()
    except Exception:
        pass

    return AnalystAction(
        firm=str(recent.get("Firm")) if recent.get("Firm") else None,
        action=action,
        to_grade=str(recent.get("ToGrade")) if recent.get("ToGrade") else None,
        from_grade=str(recent.get("FromGrade")) if recent.get("FromGrade") else None,
        action_date=action_date,
        source=NAME,
    )


def get_earnings_info(symbol: str) -> EarningsInfo | None:
    try:
        tk = yf.Ticker(symbol)
        calendar = tk.calendar
    except Exception:
        return None
    if not calendar:
        return None

    raw_dates = calendar.get("Earnings Date")
    earnings_date = raw_dates[0] if raw_dates else None

    return EarningsInfo(
        earnings_date=earnings_date,
        eps_estimate=calendar.get("Earnings Average"),
        revenue_estimate=calendar.get("Revenue Average"),
        source=NAME,
    )


def get_insider_transactions(symbol: str, limit: int = 10) -> list[InsiderTransaction] | None:
    try:
        tk = yf.Ticker(symbol)
        df = tk.insider_transactions
    except Exception:
        return None
    if df is None or df.empty:
        return None

    transactions = []
    for row in df.head(limit).itertuples():
        try:
            tx_date = None
            raw_date = getattr(row, "Start_Date", None) or getattr(row, "startDate", None)
            if raw_date is not None:
                tx_date = pd.to_datetime(raw_date).date()
            transactions.append(
                InsiderTransaction(
                    insider=str(getattr(row, "Insider", "Unknown")),
                    transaction_type=str(getattr(row, "Transaction", "Unknown")),
                    shares=float(getattr(row, "Shares", 0) or 0),
                    value=float(getattr(row, "Value", 0) or 0),
                    transaction_date=tx_date,
                    source=NAME,
                )
            )
        except Exception:
            continue
    return transactions or None


def get_sec_filings(symbol: str, limit: int = 5) -> list[SecFiling] | None:
    try:
        tk = yf.Ticker(symbol)
        filings = tk.sec_filings
    except Exception:
        return None
    if not filings:
        return None

    results = []
    for item in filings[:limit]:
        try:
            filing_date = None
            raw_date = item.get("date")
            if raw_date:
                filing_date = pd.to_datetime(raw_date).date()
            results.append(
                SecFiling(
                    filing_type=item.get("type", "Unknown"),
                    filing_date=filing_date,
                    url=item.get("edgarUrl") or item.get("exhibits", [{}])[0].get("url") if item.get("exhibits") else item.get("edgarUrl"),
                    source=NAME,
                )
            )
        except Exception:
            continue
    return results or None
