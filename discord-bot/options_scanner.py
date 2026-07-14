"""Live options-chain analysis for AlphaOptionsAI's /scan command.

Fetches the nearest expirations' call/put chains from Yahoo Finance, scores
every contract on nine factors, and recommends the single best call and put.
"""

import asyncio
import math
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

import pandas as pd
import yfinance as yf

RISK_FREE_RATE = 0.05  # Flat assumption used for Black-Scholes greeks.
NUM_EXPIRATIONS = 3


class NoOptionsAvailableError(Exception):
    pass


@dataclass
class ContractPick:
    strike: float
    expiration: str
    dte: int
    premium: float
    open_interest: int
    volume: int
    implied_vol: float
    delta: float
    gamma: float
    score: float
    win_probability: float


@dataclass
class OptionsScanResult:
    best_call: ContractPick
    best_put: ContractPick
    expected_move: float
    expected_move_pct: float
    risk: str
    win_probability: float
    entry: float
    exit_target: float
    stop_loss: float


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    return math.exp(-x * x / 2.0) / math.sqrt(2.0 * math.pi)


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(value, high))


def _soft_peak_score(value: float, peak: float, width: float) -> float:
    """1.0 at `peak`, decaying linearly to 0 as `value` moves `width` away."""
    return _clamp(1.0 - abs(value - peak) / width)


def _black_scholes_greeks(
    *, spot: float, strike: float, t_years: float, sigma: float, option_type: str
) -> tuple[float, float, float]:
    """Returns (delta, gamma, d2) using flat-rate Black-Scholes."""
    d1 = (
        math.log(spot / strike) + (RISK_FREE_RATE + sigma * sigma / 2) * t_years
    ) / (sigma * math.sqrt(t_years))
    d2 = d1 - sigma * math.sqrt(t_years)

    if option_type == "call":
        delta = _norm_cdf(d1)
    else:
        delta = _norm_cdf(d1) - 1.0

    gamma = _norm_pdf(d1) / (spot * sigma * math.sqrt(t_years))
    return delta, gamma, d2


def _score_contract(
    *,
    open_interest: int,
    volume: int,
    implied_vol: float,
    delta: float,
    gamma: float,
    bid: float,
    ask: float,
    distance_pct: float,
    dte: int,
) -> float:
    """Nine equally-weighted factors, each normalized to 0-1, averaged to 0-100."""
    oi_score = _clamp(open_interest / 3000)
    volume_score = _clamp(volume / 1000)
    vol_oi_ratio = (volume / open_interest) if open_interest > 0 else 0.0
    vol_oi_score = _clamp(vol_oi_ratio)
    iv_score = _soft_peak_score(implied_vol, peak=0.40, width=0.60)
    delta_score = _soft_peak_score(abs(delta), peak=0.45, width=0.35)
    gamma_score = _clamp(gamma * 25)

    if bid > 0 and ask > 0:
        mid = (bid + ask) / 2
        spread_pct = (ask - bid) / mid if mid > 0 else 1.0
        spread_score = _clamp(1.0 - min(spread_pct, 1.0))
    else:
        spread_score = 0.0

    distance_score = _soft_peak_score(distance_pct, peak=0.03, width=0.20)
    days_score = _soft_peak_score(dte, peak=30, width=40)

    factors = [
        oi_score,
        volume_score,
        vol_oi_score,
        iv_score,
        delta_score,
        gamma_score,
        spread_score,
        distance_score,
        days_score,
    ]
    return round(_clamp(sum(factors) / len(factors)) * 100, 1)


def _process_row(row, *, spot: float, exp_str: str, dte: int, option_type: str) -> Optional[ContractPick]:
    strike = float(row.strike)
    bid = float(row.bid) if not pd.isna(row.bid) else 0.0
    ask = float(row.ask) if not pd.isna(row.ask) else 0.0
    last_price = float(row.lastPrice) if not pd.isna(row.lastPrice) else 0.0
    implied_vol = float(row.impliedVolatility) if not pd.isna(row.impliedVolatility) else 0.0
    volume = int(row.volume) if not pd.isna(row.volume) else 0
    open_interest = int(row.openInterest) if not pd.isna(row.openInterest) else 0

    if implied_vol <= 0 or strike <= 0:
        return None

    premium = (bid + ask) / 2 if bid > 0 and ask > 0 else last_price
    if premium <= 0:
        return None

    t_years = max(dte, 1) / 365
    try:
        delta, gamma, d2 = _black_scholes_greeks(
            spot=spot, strike=strike, t_years=t_years, sigma=implied_vol, option_type=option_type
        )
    except (ValueError, ZeroDivisionError):
        return None

    win_probability = _norm_cdf(d2) if option_type == "call" else _norm_cdf(-d2)
    distance_pct = abs(strike - spot) / spot

    score = _score_contract(
        open_interest=open_interest,
        volume=volume,
        implied_vol=implied_vol,
        delta=delta,
        gamma=gamma,
        bid=bid,
        ask=ask,
        distance_pct=distance_pct,
        dte=dte,
    )

    return ContractPick(
        strike=strike,
        expiration=exp_str,
        dte=dte,
        premium=round(premium, 2),
        open_interest=open_interest,
        volume=volume,
        implied_vol=implied_vol,
        delta=delta,
        gamma=gamma,
        score=score,
        win_probability=win_probability,
    )


def _scan_options_sync(ticker: str, current_price: float) -> OptionsScanResult:
    tk = yf.Ticker(ticker)
    expirations = tk.options

    if not expirations:
        raise NoOptionsAvailableError(f"No options chain is available for '{ticker}'.")

    today = date.today()
    call_candidates: list[ContractPick] = []
    put_candidates: list[ContractPick] = []

    for exp_str in expirations[:NUM_EXPIRATIONS]:
        exp_date = datetime.strptime(exp_str, "%Y-%m-%d").date()
        dte = max((exp_date - today).days, 1)

        chain = tk.option_chain(exp_str)

        for row in chain.calls.itertuples():
            pick = _process_row(row, spot=current_price, exp_str=exp_str, dte=dte, option_type="call")
            if pick:
                call_candidates.append(pick)

        for row in chain.puts.itertuples():
            pick = _process_row(row, spot=current_price, exp_str=exp_str, dte=dte, option_type="put")
            if pick:
                put_candidates.append(pick)

    if not call_candidates or not put_candidates:
        raise NoOptionsAvailableError(f"Not enough liquid options data for '{ticker}'.")

    best_call = max(call_candidates, key=lambda c: c.score)
    best_put = max(put_candidates, key=lambda c: c.score)

    avg_iv = (best_call.implied_vol + best_put.implied_vol) / 2
    avg_t_years = ((best_call.dte + best_put.dte) / 2) / 365
    expected_move_pct = avg_iv * math.sqrt(avg_t_years)
    expected_move = current_price * expected_move_pct

    min_dte = min(best_call.dte, best_put.dte)
    if avg_iv > 0.75 or min_dte <= 7:
        risk = "High"
    elif avg_iv > 0.40 or min_dte <= 21:
        risk = "Medium"
    else:
        risk = "Low"

    win_probability = round(((best_call.win_probability + best_put.win_probability) / 2) * 100, 1)

    primary = best_call if best_call.score >= best_put.score else best_put
    entry = primary.premium
    exit_target = round(entry * 1.5, 2)
    stop_loss = round(entry * 0.5, 2)

    return OptionsScanResult(
        best_call=best_call,
        best_put=best_put,
        expected_move=round(expected_move, 2),
        expected_move_pct=round(expected_move_pct * 100, 2),
        risk=risk,
        win_probability=win_probability,
        entry=entry,
        exit_target=exit_target,
        stop_loss=stop_loss,
    )


async def scan_options(ticker: str, current_price: float) -> OptionsScanResult:
    return await asyncio.to_thread(_scan_options_sync, ticker, current_price)
