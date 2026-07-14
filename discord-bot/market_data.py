"""Live market data + simple technical scoring for AlphaOptionsAI."""

from dataclasses import dataclass

import yfinance as yf


class TickerNotFoundError(Exception):
    pass


@dataclass
class ScanResult:
    ticker: str
    current_price: float
    previous_close: float
    daily_change_pct: float
    high_52w: float
    low_52w: float
    volume: int
    avg_volume: float
    ema20: float
    trend: str
    confidence: float


def _fetch_scan_result(ticker: str) -> ScanResult:
    symbol = ticker.upper()
    tk = yf.Ticker(symbol)

    # 6mo of daily history gives enough bars for a stable 20 EMA.
    hist = tk.history(period="6mo", interval="1d")
    if hist is None or hist.empty:
        raise TickerNotFoundError(f"No market data found for '{symbol}'.")

    closes = hist["Close"].dropna()
    if len(closes) < 2:
        raise TickerNotFoundError(f"Not enough price history for '{symbol}'.")

    current_price = float(closes.iloc[-1])
    previous_close = float(closes.iloc[-2])
    daily_change_pct = ((current_price - previous_close) / previous_close) * 100

    year_hist = tk.history(period="1y", interval="1d")
    if year_hist is None or year_hist.empty:
        year_hist = hist
    high_52w = float(year_hist["High"].max())
    low_52w = float(year_hist["Low"].min())

    volume = int(hist["Volume"].iloc[-1])
    avg_volume = float(hist["Volume"].mean())

    ema20_series = closes.ewm(span=20, adjust=False).mean()
    ema20 = float(ema20_series.iloc[-1])

    if current_price > ema20:
        trend = "Bullish"
    elif current_price < ema20:
        trend = "Bearish"
    else:
        trend = "Neutral"

    confidence = _score_confidence(
        trend=trend,
        current_price=current_price,
        ema20=ema20,
        daily_change_pct=daily_change_pct,
        volume=volume,
        avg_volume=avg_volume,
    )

    return ScanResult(
        ticker=symbol,
        current_price=current_price,
        previous_close=previous_close,
        daily_change_pct=daily_change_pct,
        high_52w=high_52w,
        low_52w=low_52w,
        volume=volume,
        avg_volume=avg_volume,
        ema20=ema20,
        trend=trend,
        confidence=confidence,
    )


def _score_confidence(
    *,
    trend: str,
    current_price: float,
    ema20: float,
    daily_change_pct: float,
    volume: int,
    avg_volume: float,
) -> float:
    """Blend trend strength, momentum, and volume into a 50-95 confidence score."""

    score = 50.0

    if trend == "Neutral":
        # Price is essentially at the EMA -- low conviction either way.
        return round(score + min(abs(daily_change_pct) * 1.5, 5.0), 1)

    # Trend strength: how far price has moved from its 20 EMA, as a %.
    ema_distance_pct = abs((current_price - ema20) / ema20) * 100
    score += min(ema_distance_pct * 4, 20)

    # Momentum: today's move in the direction of the trend adds confidence,
    # a move against the trend subtracts a little.
    directional_change = daily_change_pct if trend == "Bullish" else -daily_change_pct
    score += max(min(directional_change * 2, 12), -8)

    # Volume: trading above its recent average volume supports the move.
    if avg_volume > 0:
        volume_ratio = volume / avg_volume
        score += max(min((volume_ratio - 1) * 10, 13), -5)

    return round(max(50.0, min(score, 95.0)), 1)


async def get_scan_result(ticker: str) -> ScanResult:
    import asyncio

    return await asyncio.to_thread(_fetch_scan_result, ticker)
