"""Full technical-analysis suite, computed from real OHLCV history only.
Every value that can't be computed (not enough bars) is `None` -- never a
guess.
"""

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


@dataclass
class TechnicalSnapshot:
    price: float
    ema9: Optional[float]
    ema20: Optional[float]
    ema50: Optional[float]
    ema100: Optional[float]
    ema200: Optional[float]
    vwap: Optional[float]
    macd_line: Optional[float]
    macd_signal: Optional[float]
    macd_hist: Optional[float]
    rsi14: Optional[float]
    stoch_rsi: Optional[float]
    adx14: Optional[float]
    atr14: Optional[float]
    bb_upper: Optional[float]
    bb_lower: Optional[float]
    bb_mid: Optional[float]
    bb_width_pct: Optional[float]
    supertrend: Optional[float]
    supertrend_direction: Optional[str]
    ichimoku_conversion: Optional[float]
    ichimoku_base: Optional[float]
    ichimoku_span_a: Optional[float]
    ichimoku_span_b: Optional[float]
    volume: Optional[float]
    avg_volume20: Optional[float]
    relative_volume: Optional[float]
    support: Optional[float]
    resistance: Optional[float]
    trend_strength: Optional[str]
    gap_pct: Optional[float]
    breakout: Optional[str]
    momentum_score: Optional[float]
    volatility_score: Optional[float]
    poc_price: Optional[float]  # Volume Profile point of control


def _ema(series: pd.Series, span: int) -> Optional[float]:
    if len(series) < span:
        return None
    return float(series.ewm(span=span, adjust=False).mean().iloc[-1])


def _rsi(series: pd.Series, period: int = 14) -> Optional[pd.Series]:
    if len(series) < period + 1:
        return None
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(100)


def _stoch_rsi(rsi_series: Optional[pd.Series], period: int = 14) -> Optional[float]:
    if rsi_series is None or len(rsi_series) < period:
        return None
    window = rsi_series.tail(period)
    lo, hi = window.min(), window.max()
    if hi == lo:
        return None
    return float((rsi_series.iloc[-1] - lo) / (hi - lo) * 100)


def _macd(series: pd.Series) -> tuple[Optional[float], Optional[float], Optional[float]]:
    if len(series) < 26:
        return None, None, None
    ema12 = series.ewm(span=12, adjust=False).mean()
    ema26 = series.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    hist = macd_line - signal_line
    return float(macd_line.iloc[-1]), float(signal_line.iloc[-1]), float(hist.iloc[-1])


def _true_range(hist: pd.DataFrame) -> pd.Series:
    high, low, close = hist["High"], hist["Low"], hist["Close"]
    prev_close = close.shift(1)
    return pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)


def _atr(hist: pd.DataFrame, period: int = 14) -> Optional[float]:
    if len(hist) < period + 1:
        return None
    tr = _true_range(hist)
    return float(tr.ewm(alpha=1 / period, adjust=False).mean().iloc[-1])


def _adx(hist: pd.DataFrame, period: int = 14) -> Optional[float]:
    if len(hist) < period * 2:
        return None
    high, low = hist["High"], hist["Low"]
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    tr = _true_range(hist)
    atr = tr.ewm(alpha=1 / period, adjust=False).mean()
    plus_di = 100 * pd.Series(plus_dm, index=hist.index).ewm(alpha=1 / period, adjust=False).mean() / atr.replace(0, np.nan)
    minus_di = 100 * pd.Series(minus_dm, index=hist.index).ewm(alpha=1 / period, adjust=False).mean() / atr.replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = dx.ewm(alpha=1 / period, adjust=False).mean()
    value = adx.iloc[-1]
    return float(value) if pd.notna(value) else None


def _bollinger(series: pd.Series, period: int = 20, num_std: float = 2.0):
    if len(series) < period:
        return None, None, None, None
    window = series.tail(period)
    mid = float(window.mean())
    std = float(window.std())
    upper = mid + num_std * std
    lower = mid - num_std * std
    width_pct = ((upper - lower) / mid * 100) if mid else None
    return upper, lower, mid, width_pct


def _supertrend(hist: pd.DataFrame, period: int = 10, multiplier: float = 3.0):
    if len(hist) < period + 1:
        return None, None
    tr = _true_range(hist)
    atr = tr.ewm(alpha=1 / period, adjust=False).mean()
    hl2 = (hist["High"] + hist["Low"]) / 2
    upper_band = hl2 + multiplier * atr
    lower_band = hl2 - multiplier * atr

    direction = "Bullish"
    supertrend_value = float(lower_band.iloc[0])
    for i in range(1, len(hist)):
        close = hist["Close"].iloc[i]
        if direction == "Bullish":
            supertrend_value = max(lower_band.iloc[i], supertrend_value) if close > supertrend_value else float(upper_band.iloc[i])
            direction = "Bullish" if close > supertrend_value else "Bearish"
        else:
            supertrend_value = min(upper_band.iloc[i], supertrend_value) if close < supertrend_value else float(lower_band.iloc[i])
            direction = "Bearish" if close < supertrend_value else "Bullish"

    return float(supertrend_value), direction


def _ichimoku(hist: pd.DataFrame):
    if len(hist) < 52:
        return None, None, None, None
    high, low = hist["High"], hist["Low"]
    conversion = (high.tail(9).max() + low.tail(9).min()) / 2
    base = (high.tail(26).max() + low.tail(26).min()) / 2
    span_a = (conversion + base) / 2
    span_b = (high.tail(52).max() + low.tail(52).min()) / 2
    return float(conversion), float(base), float(span_a), float(span_b)


def _support_resistance(hist: pd.DataFrame, price: float, lookback: int = 20):
    if len(hist) < 5:
        return None, None
    window = hist.tail(lookback)
    resistance_candidates = window["High"][window["High"] > price]
    support_candidates = window["Low"][window["Low"] < price]
    resistance = float(resistance_candidates.min()) if not resistance_candidates.empty else None
    support = float(support_candidates.max()) if not support_candidates.empty else None
    return support, resistance


def _volume_profile_poc(hist: pd.DataFrame, bins: int = 20) -> Optional[float]:
    """Approximate point-of-control: the price bin with the most traded
    volume over the lookback window (typical-price * volume per bar)."""
    if len(hist) < 10 or "Volume" not in hist:
        return None
    typical_price = (hist["High"] + hist["Low"] + hist["Close"]) / 3
    try:
        price_bins = pd.cut(typical_price, bins=bins)
    except ValueError:
        return None
    volume_by_bin = hist["Volume"].groupby(price_bins).sum()
    if volume_by_bin.empty or volume_by_bin.max() == 0:
        return None
    top_bin = volume_by_bin.idxmax()
    return float(top_bin.mid)


def _vwap(hist: pd.DataFrame, lookback: int = 20) -> Optional[float]:
    if len(hist) < 1 or "Volume" not in hist:
        return None
    window = hist.tail(lookback)
    typical_price = (window["High"] + window["Low"] + window["Close"]) / 3
    total_volume = window["Volume"].sum()
    if total_volume == 0:
        return None
    return float((typical_price * window["Volume"]).sum() / total_volume)


def compute_snapshot(hist: pd.DataFrame, current_price: float) -> TechnicalSnapshot:
    closes = hist["Close"].dropna()

    macd_line, macd_signal, macd_hist = _macd(closes)
    rsi_series = _rsi(closes, 14)
    rsi14 = float(rsi_series.iloc[-1]) if rsi_series is not None else None
    stoch_rsi = _stoch_rsi(rsi_series)
    bb_upper, bb_lower, bb_mid, bb_width_pct = _bollinger(closes)
    supertrend_value, supertrend_direction = _supertrend(hist)
    ichi_conv, ichi_base, ichi_span_a, ichi_span_b = _ichimoku(hist)
    support, resistance = _support_resistance(hist, current_price)
    poc_price = _volume_profile_poc(hist)
    vwap = _vwap(hist)

    volume = float(hist["Volume"].iloc[-1]) if "Volume" in hist and not hist["Volume"].empty else None
    avg_volume20 = float(hist["Volume"].tail(20).mean()) if "Volume" in hist and len(hist) >= 20 else None
    relative_volume = (volume / avg_volume20) if (volume and avg_volume20) else None

    ema20 = _ema(closes, 20)
    ema50 = _ema(closes, 50)
    ema200 = _ema(closes, 200)

    trend_strength = None
    if ema20 and ema50 and ema200:
        if current_price > ema20 > ema50 > ema200:
            trend_strength = "Strong Bullish"
        elif current_price < ema20 < ema50 < ema200:
            trend_strength = "Strong Bearish"
        elif current_price > ema50:
            trend_strength = "Weak Bullish"
        elif current_price < ema50:
            trend_strength = "Weak Bearish"
        else:
            trend_strength = "Neutral"

    gap_pct = None
    if len(hist) >= 2:
        prev_close = float(closes.iloc[-2])
        today_open = float(hist["Open"].iloc[-1])
        if prev_close:
            gap_pct = round((today_open - prev_close) / prev_close * 100, 2)

    breakout = None
    if resistance and current_price > resistance:
        breakout = "Bullish Breakout"
    elif support and current_price < support:
        breakout = "Bearish Breakdown"

    momentum_score = None
    if rsi14 is not None and macd_hist is not None:
        momentum_score = round(_clamp((rsi14 - 50) / 50 * 50 + macd_hist * 5, -100, 100), 1)

    atr14 = _atr(hist, 14)
    volatility_score = None
    if atr14 is not None and current_price:
        volatility_score = round((atr14 / current_price) * 100, 2)

    return TechnicalSnapshot(
        price=current_price,
        ema9=_ema(closes, 9),
        ema20=ema20,
        ema50=ema50,
        ema100=_ema(closes, 100),
        ema200=ema200,
        vwap=vwap,
        macd_line=macd_line,
        macd_signal=macd_signal,
        macd_hist=macd_hist,
        rsi14=rsi14,
        stoch_rsi=stoch_rsi,
        adx14=_adx(hist, 14),
        atr14=atr14,
        bb_upper=bb_upper,
        bb_lower=bb_lower,
        bb_mid=bb_mid,
        bb_width_pct=bb_width_pct,
        supertrend=supertrend_value,
        supertrend_direction=supertrend_direction,
        ichimoku_conversion=ichi_conv,
        ichimoku_base=ichi_base,
        ichimoku_span_a=ichi_span_a,
        ichimoku_span_b=ichi_span_b,
        volume=volume,
        avg_volume20=avg_volume20,
        relative_volume=relative_volume,
        support=support,
        resistance=resistance,
        trend_strength=trend_strength,
        gap_pct=gap_pct,
        breakout=breakout,
        momentum_score=momentum_score,
        volatility_score=volatility_score,
        poc_price=poc_price,
    )


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(value, high))
