"""Multi-Timeframe Analysis: evaluates trend agreement across 5m, 15m,
1h, 4h (resampled from 1h), daily, and weekly bars and produces an
Alignment Score (0-100).

Each timeframe votes bullish/bearish/neutral from three real checks
(EMA20 vs EMA50, MACD histogram, RSI zone). Unavailable timeframes are
reported as such and excluded from the score — never guessed.
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("alphaoptionsai.timeframes")

# (label, yfinance interval, period, weight). Higher timeframes weigh more.
TIMEFRAME_SPECS = [
    ("5m", "5m", "5d", 0.5),
    ("15m", "15m", "5d", 0.75),
    ("1h", "1h", "1mo", 1.0),
    ("4h", None, "3mo", 1.25),   # resampled from 1h
    ("1D", "1d", "1y", 1.5),
    ("1W", "1wk", "5y", 1.5),
]

MIN_BARS = 60


@dataclass
class TimeframeVote:
    timeframe: str
    direction: int                # +1 bullish, -1 bearish, 0 neutral
    ema_state: Optional[str]      # "EMA20>EMA50" etc.
    macd_state: Optional[str]
    rsi: Optional[float]


@dataclass
class TimeframeAlignment:
    score: float                  # 0-100 strength of agreement in the dominant direction
    direction: str                # "BULLISH" | "BEARISH" | "MIXED" | "UNAVAILABLE"
    votes: list[TimeframeVote] = field(default_factory=list)
    unavailable: list[str] = field(default_factory=list)


def _vote_from_closes(label: str, closes) -> Optional[TimeframeVote]:
    closes = closes.dropna()
    if len(closes) < MIN_BARS:
        return None
    ema20 = closes.ewm(span=20, adjust=False).mean()
    ema50 = closes.ewm(span=50, adjust=False).mean()
    ema12 = closes.ewm(span=12, adjust=False).mean()
    ema26 = closes.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    macd_hist = macd_line - macd_line.ewm(span=9, adjust=False).mean()

    delta = closes.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rs = gain / loss.replace(0, float("nan"))
    rsi = float((100 - 100 / (1 + rs)).iloc[-1])

    checks = 0
    ema_bull = float(ema20.iloc[-1]) > float(ema50.iloc[-1])
    checks += 1 if ema_bull else -1
    macd_bull = float(macd_hist.iloc[-1]) > 0
    checks += 1 if macd_bull else -1
    if rsi > 55:
        checks += 1
    elif rsi < 45:
        checks -= 1

    direction = 1 if checks >= 2 else (-1 if checks <= -2 else 0)
    return TimeframeVote(
        timeframe=label, direction=direction,
        ema_state="EMA20>EMA50" if ema_bull else "EMA20<EMA50",
        macd_state="MACD+" if macd_bull else "MACD-",
        rsi=round(rsi, 1),
    )


def analyze_timeframes(symbol: str) -> TimeframeAlignment:
    """Synchronous (call from a worker thread). ~5 real downloads."""
    import yfinance as yf

    votes: list[TimeframeVote] = []
    unavailable: list[str] = []
    weights_used: list[float] = []
    weighted_sum = 0.0
    hourly_3mo = None

    for label, interval, period, weight in TIMEFRAME_SPECS:
        try:
            if label == "4h":
                if hourly_3mo is None:
                    raise ValueError("no hourly data to resample")
                closes = hourly_3mo.resample("4h").last()
            else:
                df = yf.download(symbol, period=period, interval=interval, progress=False, auto_adjust=True)
                if df is None or df.empty:
                    raise ValueError("empty response")
                closes = df["Close"] if not hasattr(df["Close"], "columns") else df["Close"][symbol]
                if label == "1h":
                    hourly_3mo_df = yf.download(symbol, period="3mo", interval="1h", progress=False, auto_adjust=True)
                    if hourly_3mo_df is not None and not hourly_3mo_df.empty:
                        hourly_3mo = hourly_3mo_df["Close"] if not hasattr(hourly_3mo_df["Close"], "columns") else hourly_3mo_df["Close"][symbol]
                    else:
                        hourly_3mo = None
            vote = _vote_from_closes(label, closes)
            if vote is None:
                unavailable.append(label)
                continue
            votes.append(vote)
            weighted_sum += vote.direction * weight
            weights_used.append(weight)
        except Exception as exc:
            logger.debug("Timeframe %s unavailable for %s: %s", label, symbol, exc)
            unavailable.append(label)

    if not votes:
        return TimeframeAlignment(score=0.0, direction="UNAVAILABLE", votes=[], unavailable=unavailable)

    total_weight = sum(weights_used) or 1.0
    strength = abs(weighted_sum) / total_weight * 100
    if strength < 40:
        direction = "MIXED"
    else:
        direction = "BULLISH" if weighted_sum > 0 else "BEARISH"
    return TimeframeAlignment(score=round(strength, 1), direction=direction, votes=votes, unavailable=unavailable)


def adjustment_for_side(alignment: TimeframeAlignment, side: str) -> tuple[float, Optional[str]]:
    """Bounded (±6) confidence adjustment: reward multi-timeframe agreement
    with the trade side, penalize trading against it or into a mixed tape."""
    if alignment.direction == "UNAVAILABLE":
        return 0.0, None
    wants = "BULLISH" if side == "call" else "BEARISH"
    agreeing = sum(1 for v in alignment.votes if (v.direction > 0) == (side == "call") and v.direction != 0)
    if alignment.direction == wants and alignment.score >= 70:
        return 4.0, f"Timeframe alignment {alignment.score:.0f}% {wants} ({agreeing}/{len(alignment.votes)} TFs agree): +4"
    if alignment.direction == wants and alignment.score >= 40:
        return 2.0, f"Timeframe alignment {alignment.score:.0f}% {wants}: +2"
    if alignment.direction == "MIXED":
        return -2.0, f"Timeframes are mixed (alignment {alignment.score:.0f}%): -2"
    return -6.0, f"Higher timeframes are {alignment.direction} against this {side.upper()} (alignment {alignment.score:.0f}%): -6"
