"""Historical strategy backtesting.

Real historical OPTIONS quotes are not available from Yahoo Finance (or
any free source), so this backtester works on real historical STOCK price
data (up to Yahoo's max history, commonly 5-10+ years for large caps) and
prices the hypothetical option trade with the same Black-Scholes model
used live, seeded with realized volatility from the historical window.

This is a transparent, standard practice for retail backtesting without a
paid historical-options feed -- and it is always labeled as such in the
output. It is never presented as real historical option fills.
"""

import math
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from apis import router
from core import database, technicals as technicals_module

METHODOLOGY_NOTE = (
    "Backtest option premiums are modeled with Black-Scholes using each period's "
    "trailing realized volatility -- real historical options quotes are not "
    "available without a premium data feed (Polygon/Tradier). Stock price "
    "history is real, sourced live from Yahoo Finance."
)

MIN_TRADES_FOR_PRODUCTION = 20
RISK_FREE_RATE = 0.05


@dataclass
class BacktestResult:
    ticker: str
    strategy_tag: str
    period: str
    total_trades: int
    win_rate: Optional[float]
    avg_return_pct: Optional[float]
    avg_hold_days: Optional[float]
    max_drawdown_pct: Optional[float]
    max_gain_pct: Optional[float]
    sharpe_ratio: Optional[float]
    sortino_ratio: Optional[float]
    profit_factor: Optional[float]
    expectancy: Optional[float]
    production_ready: bool
    methodology_note: str


def _theoretical_call_price(spot: float, strike: float, t_years: float, sigma: float) -> float:
    if t_years <= 0 or sigma <= 0:
        return max(spot - strike, 0.0)
    sqrt_t = math.sqrt(t_years)
    d1 = (math.log(spot / strike) + (RISK_FREE_RATE + sigma * sigma / 2) * t_years) / (sigma * sqrt_t)
    d2 = d1 - sigma * sqrt_t
    n = lambda x: 0.5 * (1 + math.erf(x / math.sqrt(2)))
    return spot * n(d1) - strike * math.exp(-RISK_FREE_RATE * t_years) * n(d2)


def _theoretical_put_price(spot: float, strike: float, t_years: float, sigma: float) -> float:
    call = _theoretical_call_price(spot, strike, t_years, sigma)
    return call - spot + strike * math.exp(-RISK_FREE_RATE * t_years)


def run_backtest(symbol: str, period: str = "5y", hold_days: int = 10, direction: str = "long_bias") -> Optional[BacktestResult]:
    """Simple, transparent EMA20/50 trend-following strategy: enter a
    call when EMA20 crosses above EMA50 (put on the inverse crossover),
    hold for `hold_days` trading days or exit at +30%/-45% on the modeled
    premium, whichever comes first."""
    history_result = router.get_history(symbol, period=period, interval="1d")
    if not history_result.available:
        return None
    hist = history_result.value.df
    closes = hist["Close"].dropna()
    if len(closes) < 120:
        return None

    ema20 = closes.ewm(span=20, adjust=False).mean()
    ema50 = closes.ewm(span=50, adjust=False).mean()
    returns = closes.pct_change()
    realized_vol = returns.rolling(20).std() * math.sqrt(252)

    trades = []
    i = 50
    while i < len(closes) - hold_days:
        crossed_up = ema20.iloc[i - 1] <= ema50.iloc[i - 1] and ema20.iloc[i] > ema50.iloc[i]
        crossed_down = ema20.iloc[i - 1] >= ema50.iloc[i - 1] and ema20.iloc[i] < ema50.iloc[i]
        sigma = realized_vol.iloc[i]

        if pd.isna(sigma) or sigma <= 0:
            i += 1
            continue

        if crossed_up or crossed_down:
            is_call = crossed_up
            spot_entry = float(closes.iloc[i])
            strike = round(spot_entry / 5) * 5  # nearest $5 strike, at/near the money
            t_years_entry = 30 / 365  # model a ~30 DTE contract at entry
            entry_price = (
                _theoretical_call_price(spot_entry, strike, t_years_entry, sigma)
                if is_call else _theoretical_put_price(spot_entry, strike, t_years_entry, sigma)
            )
            if entry_price <= 0.01:
                i += 1
                continue

            exit_idx = min(i + hold_days, len(closes) - 1)
            best_return, worst_return, final_return = None, None, None
            for j in range(i + 1, exit_idx + 1):
                spot_j = float(closes.iloc[j])
                t_years_j = max(t_years_entry - (j - i) / 365, 1 / 365)
                price_j = (
                    _theoretical_call_price(spot_j, strike, t_years_j, sigma)
                    if is_call else _theoretical_put_price(spot_j, strike, t_years_j, sigma)
                )
                ret = (price_j - entry_price) / entry_price
                best_return = ret if best_return is None else max(best_return, ret)
                worst_return = ret if worst_return is None else min(worst_return, ret)
                final_return = ret
                if ret >= 0.30 or ret <= -0.45:
                    break

            trades.append(
                {
                    "return_pct": final_return * 100,
                    "max_gain_pct": best_return * 100,
                    "max_drawdown_pct": worst_return * 100,
                    "hold_days": (j - i),
                }
            )
            i = j + 1
        else:
            i += 1

    if not trades:
        return None

    total = len(trades)
    wins = sum(1 for t in trades if t["return_pct"] > 0)
    win_rate = round(wins / total * 100, 1)
    avg_return = round(sum(t["return_pct"] for t in trades) / total, 2)
    avg_hold = round(sum(t["hold_days"] for t in trades) / total, 1)
    max_drawdown = round(min(t["max_drawdown_pct"] for t in trades), 2)
    max_gain = round(max(t["max_gain_pct"] for t in trades), 2)

    trade_returns = np.array([t["return_pct"] for t in trades])
    mean_ret, std_ret = trade_returns.mean(), trade_returns.std()
    sharpe = round(float(mean_ret / std_ret), 2) if std_ret > 0 else None
    downside = trade_returns[trade_returns < 0]
    downside_std = downside.std() if len(downside) > 1 else None
    sortino = round(float(mean_ret / downside_std), 2) if downside_std else None

    gross_gain = sum(t["return_pct"] for t in trades if t["return_pct"] > 0)
    gross_loss = -sum(t["return_pct"] for t in trades if t["return_pct"] < 0)
    profit_factor = round(gross_gain / gross_loss, 2) if gross_loss > 0 else None
    expectancy = round((win_rate / 100) * avg_return - (1 - win_rate / 100) * abs(avg_return), 2) if total else None

    result = BacktestResult(
        ticker=symbol, strategy_tag="ema20_50_crossover", period=period, total_trades=total,
        win_rate=win_rate, avg_return_pct=avg_return, avg_hold_days=avg_hold,
        max_drawdown_pct=max_drawdown, max_gain_pct=max_gain, sharpe_ratio=sharpe,
        sortino_ratio=sortino, profit_factor=profit_factor, expectancy=expectancy,
        production_ready=total >= MIN_TRADES_FOR_PRODUCTION, methodology_note=METHODOLOGY_NOTE,
    )

    database.record_backtest(
        ticker=symbol, strategy_tag=result.strategy_tag, period=period, total_trades=total,
        win_rate=win_rate, avg_return_pct=avg_return, avg_hold_days=avg_hold,
        max_drawdown_pct=max_drawdown, max_gain_pct=max_gain, sharpe_ratio=sharpe,
        sortino_ratio=sortino, profit_factor=profit_factor, expectancy=expectancy,
        methodology_note=METHODOLOGY_NOTE,
    )
    return result
