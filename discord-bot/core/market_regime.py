"""Market Regime Engine: classifies the current market environment from
real index/volatility/rate/dollar data and returns a Market Confidence
Score plus per-side confidence adjustments.

Inputs (one batched download, all real):
- SPY, QQQ  — trend structure (EMA50/200 stack, drawdown from 52w high)
- ^VIX      — volatility level + 1-year percentile
- ^TNX      — 10y Treasury yield trend (3-month change)
- DX-Y.NYB  — Dollar Index trend (3-month % change)

Regimes: BULL, BEAR, CORRECTION, RECOVERY, SIDEWAYS
Volatility overlay: HIGH / NORMAL / LOW

Anything unavailable is reported in `unavailable` and simply contributes
no signal — never a guessed value.
"""

import logging
import threading
import time as time_module
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("alphaoptionsai.market_regime")

REGIME_SYMBOLS = ["SPY", "QQQ", "^VIX", "^TNX", "DX-Y.NYB"]
CACHE_TTL_SECONDS = 15 * 60

BULL, BEAR, CORRECTION, RECOVERY, SIDEWAYS = "BULL", "BEAR", "CORRECTION", "RECOVERY", "SIDEWAYS"
VOL_HIGH, VOL_NORMAL, VOL_LOW = "HIGH", "NORMAL", "LOW"


@dataclass
class MarketRegime:
    regime: str                      # BULL | BEAR | CORRECTION | RECOVERY | SIDEWAYS | UNKNOWN
    vol_state: Optional[str]         # HIGH | NORMAL | LOW | None if VIX unavailable
    bias: str                        # plain-language strategy bias
    market_confidence: float         # 0-100: clarity/strength of the regime signal
    components: dict = field(default_factory=dict)   # real readings that produced the call
    unavailable: list = field(default_factory=list)
    as_of: Optional[str] = None


_cache_lock = threading.Lock()
_cached: Optional[MarketRegime] = None
_cached_at: float = 0.0


def _classify_index(closes) -> Optional[dict]:
    """Classify one index's structure from real daily closes."""
    closes = closes.dropna()
    if len(closes) < 210:
        return None
    price = float(closes.iloc[-1])
    ema50 = float(closes.ewm(span=50, adjust=False).mean().iloc[-1])
    ema200 = float(closes.ewm(span=200, adjust=False).mean().iloc[-1])
    high_52w = float(closes.max())
    drawdown_pct = (high_52w - price) / high_52w * 100
    ret_20d = (price / float(closes.iloc[-21]) - 1) * 100 if len(closes) >= 21 else 0.0

    # Was the index in a >8% drawdown at any point in the last 60 sessions?
    recent = closes.iloc[-60:]
    rolling_high = closes.cummax().iloc[-60:]
    was_in_drawdown = bool(((rolling_high - recent) / rolling_high * 100 > 8).any())

    if price > ema50 > ema200 and drawdown_pct < 5:
        regime = BULL
    elif price < ema50 and ema50 < ema200 and drawdown_pct > 15:
        regime = BEAR
    elif was_in_drawdown and price > ema50 and ret_20d > 2:
        regime = RECOVERY
    elif 5 <= drawdown_pct <= 20 and price < ema50:
        regime = CORRECTION
    else:
        regime = SIDEWAYS

    return {
        "regime": regime, "price": round(price, 2), "ema50": round(ema50, 2),
        "ema200": round(ema200, 2), "drawdown_from_52w_high_pct": round(drawdown_pct, 1),
        "return_20d_pct": round(ret_20d, 1),
    }


_REGIME_AXIS = {BULL: 2, RECOVERY: 1, SIDEWAYS: 0, CORRECTION: -1, BEAR: -2}


def _combine(spy: Optional[dict], qqq: Optional[dict]) -> str:
    if spy is None and qqq is None:
        return "UNKNOWN"
    if spy is None:
        return qqq["regime"]
    if qqq is None:
        return spy["regime"]
    if spy["regime"] == qqq["regime"]:
        return spy["regime"]
    # Disagreement: SPY leads (broader market), unless QQQ is materially more
    # bearish — risk-off in the larger index wins on the downside.
    axis = 0.6 * _REGIME_AXIS[spy["regime"]] + 0.4 * _REGIME_AXIS[qqq["regime"]]
    if axis >= 1.5:
        return BULL
    if axis >= 0.5:
        return RECOVERY
    if axis <= -1.5:
        return BEAR
    if axis <= -0.5:
        return CORRECTION
    return SIDEWAYS


def _bias_for(regime: str, vol_state: Optional[str]) -> str:
    base = {
        BULL: "Prefer CALLS on strong setups",
        RECOVERY: "Cautiously prefer CALLS — early-trend risk",
        BEAR: "Prefer PUTS on weak setups",
        CORRECTION: "Prefer PUTS / defensive — counter-trend calls need extra confirmation",
        SIDEWAYS: "Prefer credit spreads or NO TRADE — no directional edge",
        "UNKNOWN": "Regime data unavailable — no directional bias applied",
    }[regime]
    if vol_state == VOL_HIGH:
        base += "; HIGH volatility: smaller size, spreads over naked long options"
    elif vol_state == VOL_LOW:
        base += "; LOW volatility: long premium is cheap but moves may be slow"
    return base


def compute_market_regime() -> MarketRegime:
    """Fetch fresh data and classify. Use get_market_regime() for the cached path."""
    import pandas as pd
    import yfinance as yf

    components: dict = {}
    unavailable: list[str] = []
    frames: dict = {}
    try:
        df = yf.download(REGIME_SYMBOLS, period="1y", interval="1d", group_by="ticker", progress=False, threads=True, auto_adjust=True)
        for sym in REGIME_SYMBOLS:
            try:
                sub = df[sym] if isinstance(df.columns, pd.MultiIndex) else df
                closes = sub["Close"].dropna()
                if len(closes) >= 30:
                    frames[sym] = closes
                else:
                    unavailable.append(sym)
            except Exception:
                unavailable.append(sym)
    except Exception as exc:
        logger.error("Regime data download failed: %s", exc)
        unavailable = list(REGIME_SYMBOLS)

    spy = _classify_index(frames["SPY"]) if "SPY" in frames else None
    qqq = _classify_index(frames["QQQ"]) if "QQQ" in frames else None
    if spy:
        components["SPY"] = spy
    if qqq:
        components["QQQ"] = qqq

    regime = _combine(spy, qqq)

    vol_state = None
    if "^VIX" in frames:
        vix = frames["^VIX"]
        vix_level = float(vix.iloc[-1])
        vix_pctile = float((vix <= vix_level).mean() * 100)
        if vix_level >= 25 or vix_pctile >= 85:
            vol_state = VOL_HIGH
        elif vix_level < 14 and vix_pctile <= 35:
            vol_state = VOL_LOW
        else:
            vol_state = VOL_NORMAL
        components["VIX"] = {"level": round(vix_level, 2), "percentile_1y": round(vix_pctile, 0), "state": vol_state}

    rates_headwind = None
    if "^TNX" in frames and len(frames["^TNX"]) > 63:
        tnx = frames["^TNX"]
        change_3m = float(tnx.iloc[-1] - tnx.iloc[-63])
        rates_headwind = change_3m > 0.40
        components["10Y_yield"] = {"level": round(float(tnx.iloc[-1]), 2), "change_3m_pts": round(change_3m, 2)}

    dollar_headwind = None
    if "DX-Y.NYB" in frames and len(frames["DX-Y.NYB"]) > 63:
        dxy = frames["DX-Y.NYB"]
        change_3m_pct = float((dxy.iloc[-1] / dxy.iloc[-63] - 1) * 100)
        dollar_headwind = change_3m_pct > 3.0
        components["dollar_index"] = {"level": round(float(dxy.iloc[-1]), 2), "change_3m_pct": round(change_3m_pct, 1)}

    # Market Confidence Score: how CLEAR the regime signal is (not how bullish).
    confidence = 0.0
    if spy and qqq:
        confidence += 25 if spy["regime"] == qqq["regime"] else 10
    elif spy or qqq:
        confidence += 12
    ref = spy or qqq
    if ref:
        # Trend decisiveness: EMA separation + 20d move magnitude
        separation = abs(ref["ema50"] - ref["ema200"]) / ref["ema200"] * 100
        confidence += min(separation * 4, 25)
        confidence += min(abs(ref["return_20d_pct"]) * 2, 15)
    if vol_state == VOL_HIGH:
        confidence += 5   # high vol IS a clear (risk-off) signal, but unstable
    elif vol_state is not None:
        confidence += 15
    if rates_headwind is not None:
        confidence += 10
    if dollar_headwind is not None:
        confidence += 10
    confidence = round(min(confidence, 100.0), 1)

    return MarketRegime(
        regime=regime, vol_state=vol_state, bias=_bias_for(regime, vol_state),
        market_confidence=confidence, components=components, unavailable=unavailable,
        as_of=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )


def get_market_regime(max_age_seconds: int = CACHE_TTL_SECONDS) -> MarketRegime:
    """Cached regime read (15-min TTL) — safe to call on every scan."""
    global _cached, _cached_at
    with _cache_lock:
        if _cached is not None and (time_module.monotonic() - _cached_at) < max_age_seconds:
            return _cached
    fresh = compute_market_regime()
    with _cache_lock:
        _cached, _cached_at = fresh, time_module.monotonic()
    return fresh


def adjustment_for_side(regime: MarketRegime, side: str) -> tuple[float, list[str]]:
    """Bounded confidence adjustment (±6) for a CALL/PUT given the regime.
    Applied AFTER the V4 category score so it augments (not replaces) the
    existing market bucket; every point is explained in the notes."""
    notes: list[str] = []
    delta = 0.0
    table = {
        (BULL, "call"): +4, (BULL, "put"): -4,
        (RECOVERY, "call"): +2, (RECOVERY, "put"): -2,
        (BEAR, "put"): +4, (BEAR, "call"): -6,
        (CORRECTION, "put"): +2, (CORRECTION, "call"): -4,
        (SIDEWAYS, "call"): -2, (SIDEWAYS, "put"): -2,
    }
    key = (regime.regime, side)
    if key in table:
        delta += table[key]
        notes.append(f"Market regime {regime.regime}: {table[key]:+d} for {side.upper()}s ({regime.bias})")
    if regime.vol_state == VOL_HIGH:
        delta -= 2
        notes.append("HIGH volatility regime: -2 (long-premium trades face vol-crush and whipsaw risk)")
    return max(-8.0, min(delta, 6.0)), notes
