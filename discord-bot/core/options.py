"""Options-chain analysis: greeks, IV rank/percentile, expected move,
probability ITM, max pain, put/call ratio, and unusual-activity heuristics.

Real per-trade tape data (true sweep/block detection) requires a premium
feed (Polygon/Tradier/Benzinga). Without one configured, unusual-activity
detection here is a transparent, clearly-labeled heuristic on volume vs.
open interest -- not a fabricated "sweep detected" claim.
"""

import math
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

import numpy as np
import pandas as pd

from apis import router
from apis.base import OptionContract

RISK_FREE_RATE = 0.05
NUM_EXPIRATIONS = 3


@dataclass
class ScoredContract:
    contract: OptionContract
    dte: int
    delta: float
    gamma: float
    theta: float
    vega: float
    probability_itm: float
    liquidity_score: float
    vol_oi_ratio: float
    unusual_activity: bool


@dataclass
class ChainAnalysis:
    calls: list[ScoredContract]
    puts: list[ScoredContract]
    iv_rank: Optional[float]
    iv_percentile: Optional[float]
    expected_move: Optional[float]
    expected_move_pct: Optional[float]
    max_pain: Optional[float]
    put_call_ratio: Optional[float]
    source: str


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    return math.exp(-x * x / 2.0) / math.sqrt(2.0 * math.pi)


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(value, high))


def _soft_peak_score(value: float, peak: float, width: float) -> float:
    return _clamp(1.0 - abs(value - peak) / width)


def _black_scholes(*, spot: float, strike: float, t_years: float, sigma: float, option_type: str):
    """Returns (delta, gamma, theta_per_day, vega_per_1pct_iv, d2)."""
    sqrt_t = math.sqrt(t_years)
    d1 = (math.log(spot / strike) + (RISK_FREE_RATE + sigma * sigma / 2) * t_years) / (sigma * sqrt_t)
    d2 = d1 - sigma * sqrt_t
    discount = math.exp(-RISK_FREE_RATE * t_years)

    if option_type == "call":
        delta = _norm_cdf(d1)
        theta = (-spot * _norm_pdf(d1) * sigma / (2 * sqrt_t) - RISK_FREE_RATE * strike * discount * _norm_cdf(d2)) / 365
    else:
        delta = _norm_cdf(d1) - 1.0
        theta = (-spot * _norm_pdf(d1) * sigma / (2 * sqrt_t) + RISK_FREE_RATE * strike * discount * _norm_cdf(-d2)) / 365

    gamma = _norm_pdf(d1) / (spot * sigma * sqrt_t)
    vega = spot * _norm_pdf(d1) * sqrt_t / 100  # per 1% change in IV
    return delta, gamma, theta, vega, d2


def _liquidity_score(*, open_interest, volume, implied_vol, bid, ask, distance_pct, dte) -> float:
    oi_score = _clamp(open_interest / 3000)
    volume_score = _clamp(volume / 1000)
    vol_oi_score = _clamp((volume / open_interest) if open_interest > 0 else 0.0)
    iv_score = _soft_peak_score(implied_vol, peak=0.40, width=0.60)
    if bid > 0 and ask > 0:
        mid = (bid + ask) / 2
        spread_pct = (ask - bid) / mid if mid > 0 else 1.0
        spread_score = _clamp(1.0 - min(spread_pct, 1.0))
    else:
        spread_score = 0.0
    distance_score = _soft_peak_score(distance_pct, peak=0.03, width=0.20)
    days_score = _soft_peak_score(dte, peak=30, width=40)
    factors = [oi_score, volume_score, vol_oi_score, iv_score, spread_score, distance_score, days_score]
    return _clamp(sum(factors) / len(factors)) * 100


def _score_contract(contract: OptionContract, spot: float, dte: int) -> Optional[ScoredContract]:
    if contract.implied_vol <= 0 or contract.strike <= 0:
        return None
    premium = (contract.bid + contract.ask) / 2 if contract.bid > 0 and contract.ask > 0 else contract.last_price
    if premium <= 0:
        return None

    t_years = max(dte, 1) / 365
    try:
        delta, gamma, theta, vega, d2 = _black_scholes(
            spot=spot, strike=contract.strike, t_years=t_years, sigma=contract.implied_vol, option_type=contract.option_type
        )
    except (ValueError, ZeroDivisionError):
        return None

    probability_itm = _norm_cdf(d2) if contract.option_type == "call" else _norm_cdf(-d2)
    distance_pct = abs(contract.strike - spot) / spot
    liquidity_score = _liquidity_score(
        open_interest=contract.open_interest,
        volume=contract.volume,
        implied_vol=contract.implied_vol,
        bid=contract.bid,
        ask=contract.ask,
        distance_pct=distance_pct,
        dte=dte,
    )
    vol_oi_ratio = (contract.volume / contract.open_interest) if contract.open_interest > 0 else 0.0
    # Heuristic only -- true sweep/block detection needs trade-level tape data
    # from a premium feed. Flag "unusual" when volume dwarfs open interest
    # AND the absolute volume is large enough to not just be a thin contract.
    unusual_activity = vol_oi_ratio > 3.0 and contract.volume > 500

    return ScoredContract(
        contract=contract,
        dte=dte,
        delta=delta,
        gamma=gamma,
        theta=theta,
        vega=vega,
        probability_itm=round(probability_itm * 100, 1),
        liquidity_score=round(liquidity_score, 1),
        vol_oi_ratio=round(vol_oi_ratio, 2),
        unusual_activity=unusual_activity,
    )


def _max_pain(calls: list[OptionContract], puts: list[OptionContract]) -> Optional[float]:
    strikes = sorted({c.strike for c in calls} | {p.strike for p in puts})
    if not strikes:
        return None

    best_strike, min_pain = None, None
    for candidate in strikes:
        pain = 0.0
        for c in calls:
            if candidate > c.strike:
                pain += (candidate - c.strike) * c.open_interest
        for p in puts:
            if candidate < p.strike:
                pain += (p.strike - candidate) * p.open_interest
        if min_pain is None or pain < min_pain:
            min_pain, best_strike = pain, candidate
    return best_strike


def _iv_rank_percentile(current_iv: float, historical_close: pd.Series, current_price: float) -> tuple[Optional[float], Optional[float]]:
    """Approximate IV rank/percentile using realized volatility history as a
    proxy, since free sources don't provide historical IV series. Clearly a
    proxy -- not the option market's actual historical IV term structure."""
    if len(historical_close) < 30:
        return None, None
    returns = historical_close.pct_change().dropna()
    rolling_vol = returns.rolling(20).std() * math.sqrt(252)
    rolling_vol = rolling_vol.dropna()
    if rolling_vol.empty:
        return None, None
    lo, hi = rolling_vol.min(), rolling_vol.max()
    # Current IV can legitimately sit outside the trailing realized-vol range
    # (implied vol usually carries a premium over realized, and can spike
    # sharply ahead of catalysts like earnings) -- clamp to a valid 0-100%
    # rank/percentile so we never display an impossible value like "118%".
    iv_rank = _clamp((current_iv - lo) / (hi - lo) * 100, 0.0, 100.0) if hi > lo else None
    iv_percentile = _clamp((rolling_vol < current_iv).mean() * 100, 0.0, 100.0)
    return (round(float(iv_rank), 1) if iv_rank is not None else None), round(float(iv_percentile), 1)


def analyze_chain(symbol: str, spot: float, historical_close: Optional[pd.Series] = None) -> Optional[ChainAnalysis]:
    expirations_result = router.get_option_expirations(symbol)
    if not expirations_result.available:
        return None
    expirations = expirations_result.value
    source = expirations_result.source

    today = date.today()
    all_calls: list[ScoredContract] = []
    all_puts: list[ScoredContract] = []
    raw_calls: list[OptionContract] = []
    raw_puts: list[OptionContract] = []

    for exp_str in expirations[:NUM_EXPIRATIONS]:
        chain_result = router.get_option_chain(symbol, exp_str)
        if not chain_result.available:
            continue
        chain = chain_result.value
        try:
            exp_date = datetime.strptime(exp_str, "%Y-%m-%d").date()
            dte = max((exp_date - today).days, 1)
        except ValueError:
            continue

        for contract in chain.calls:
            raw_calls.append(contract)
            scored = _score_contract(contract, spot, dte)
            if scored:
                all_calls.append(scored)
        for contract in chain.puts:
            raw_puts.append(contract)
            scored = _score_contract(contract, spot, dte)
            if scored:
                all_puts.append(scored)

    if not all_calls or not all_puts:
        return None

    best_call_iv = max(all_calls, key=lambda c: c.liquidity_score).contract.implied_vol
    best_put_iv = max(all_puts, key=lambda c: c.liquidity_score).contract.implied_vol
    avg_iv = (best_call_iv + best_put_iv) / 2

    iv_rank = iv_percentile = None
    if historical_close is not None:
        iv_rank, iv_percentile = _iv_rank_percentile(avg_iv, historical_close, spot)

    nearest_dte = min(min(c.dte for c in all_calls), min(p.dte for p in all_puts))
    expected_move_pct = avg_iv * math.sqrt(max(nearest_dte, 1) / 365)
    expected_move = spot * expected_move_pct

    total_call_volume = sum(c.contract.volume for c in all_calls)
    total_put_volume = sum(p.contract.volume for p in all_puts)
    put_call_ratio = round(total_put_volume / total_call_volume, 2) if total_call_volume > 0 else None

    return ChainAnalysis(
        calls=all_calls,
        puts=all_puts,
        iv_rank=iv_rank,
        iv_percentile=iv_percentile,
        expected_move=round(expected_move, 2),
        expected_move_pct=round(expected_move_pct * 100, 2),
        max_pain=_max_pain(raw_calls, raw_puts),
        put_call_ratio=put_call_ratio,
        source=source,
    )
