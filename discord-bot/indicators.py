"""Technical indicator calculations shared by the trade engine.

All functions operate on real price history pulled from yfinance -- no
values are fabricated. If there isn't enough history for an indicator, the
caller gets `None` back and treats that factor as unavailable rather than
inventing a number.
"""

from dataclasses import dataclass
from typing import Optional

import pandas as pd


@dataclass
class TechnicalSnapshot:
    price: float
    ema20: Optional[float]
    ema50: Optional[float]
    ema200: Optional[float]
    rsi14: Optional[float]
    macd_line: Optional[float]
    macd_signal: Optional[float]
    atr14: Optional[float]
    volume: Optional[float]
    avg_volume20: Optional[float]
    support: Optional[float]
    resistance: Optional[float]


def _ema(series: pd.Series, span: int) -> Optional[float]:
    if len(series) < span:
        return None
    return float(series.ewm(span=span, adjust=False).mean().iloc[-1])


def _rsi(series: pd.Series, period: int = 14) -> Optional[float]:
    if len(series) < period + 1:
        return None
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    last_avg_loss = avg_loss.iloc[-1]
    if last_avg_loss == 0:
        return 100.0
    rs = avg_gain.iloc[-1] / last_avg_loss
    return float(100 - (100 / (1 + rs)))


def _macd(series: pd.Series) -> tuple[Optional[float], Optional[float]]:
    if len(series) < 26:
        return None, None
    ema12 = series.ewm(span=12, adjust=False).mean()
    ema26 = series.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    return float(macd_line.iloc[-1]), float(signal_line.iloc[-1])


def _atr(hist: pd.DataFrame, period: int = 14) -> Optional[float]:
    if len(hist) < period + 1:
        return None
    high = hist["High"]
    low = hist["Low"]
    close = hist["Close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    atr_series = tr.ewm(alpha=1 / period, adjust=False).mean()
    return float(atr_series.iloc[-1])


def _support_resistance(hist: pd.DataFrame, price: float, lookback: int = 20) -> tuple[Optional[float], Optional[float]]:
    if len(hist) < 5:
        return None, None
    window = hist.tail(lookback)
    resistance_candidates = window["High"][window["High"] > price]
    support_candidates = window["Low"][window["Low"] < price]
    resistance = float(resistance_candidates.min()) if not resistance_candidates.empty else None
    support = float(support_candidates.max()) if not support_candidates.empty else None
    return support, resistance


def compute_snapshot(hist: pd.DataFrame, current_price: float) -> TechnicalSnapshot:
    closes = hist["Close"].dropna()
    macd_line, macd_signal = _macd(closes)
    support, resistance = _support_resistance(hist, current_price)

    volume = float(hist["Volume"].iloc[-1]) if "Volume" in hist and not hist["Volume"].empty else None
    avg_volume20 = (
        float(hist["Volume"].tail(20).mean()) if "Volume" in hist and len(hist) >= 20 else None
    )

    return TechnicalSnapshot(
        price=current_price,
        ema20=_ema(closes, 20),
        ema50=_ema(closes, 50),
        ema200=_ema(closes, 200),
        rsi14=_rsi(closes, 14),
        macd_line=macd_line,
        macd_signal=macd_signal,
        atr14=_atr(hist, 14),
        volume=volume,
        avg_volume20=avg_volume20,
        support=support,
        resistance=resistance,
    )
