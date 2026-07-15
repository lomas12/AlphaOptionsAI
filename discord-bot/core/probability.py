"""Probability Engine: option outcome probabilities under the standard
lognormal (Black-Scholes) model, computed from REAL inputs only — spot
price, the contract's own implied volatility, days to expiration, and the
trade plan's actual levels.

All outputs are model estimates and are labeled as such: the lognormal
assumption is stated, inputs are never invented, and anything that cannot
be computed from available data is None.
"""

import logging
import math
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("alphaoptionsai.probability")


@dataclass
class ProbabilityProfile:
    prob_itm_pct: Optional[float]          # P(S_T beyond strike)
    prob_touch_pct: Optional[float]        # P(price touches strike before expiry) ~ 2x ITM prob (OTM side)
    prob_profit_pct: Optional[float]       # P(S_T beyond breakeven)
    breakeven_price: Optional[float]
    expected_move_dollars: Optional[float] # from chain straddle if provided, else sigma*sqrt(T) model
    expected_move_source: Optional[str]    # "options chain straddle" | "IV model"
    expected_value_dollars: Optional[float]  # per contract, using the plan's TP1/stop and model probabilities
    vol_crush_risk: Optional[str]          # "HIGH" | "MODERATE" | "LOW" | None
    assumptions: str = (
        "Model estimates under a lognormal price distribution using the contract's "
        "implied volatility. Not a guarantee — real distributions have fat tails."
    )


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _prob_above(spot: float, level: float, iv: float, dte_days: float, drift: float = 0.0) -> Optional[float]:
    """P(S_T > level) under lognormal with sigma=iv, T in years. Drift 0 =
    risk-neutral-ish, conservative for short-dated options."""
    if spot <= 0 or level <= 0 or iv <= 0 or dte_days <= 0:
        return None
    t = dte_days / 365.0
    denom = iv * math.sqrt(t)
    if denom <= 0:
        return None
    d = (math.log(spot / level) + (drift - 0.5 * iv * iv) * t) / denom
    return _norm_cdf(d)


def build_probability_profile(
    *, spot: float, strike: float, option_type: str, premium: float, implied_vol: float,
    dte: int, take_profit_1: Optional[float], stop_loss: Optional[float],
    chain_expected_move: Optional[float] = None,
    iv_rank: Optional[float] = None, days_to_earnings: Optional[int] = None,
) -> ProbabilityProfile:
    is_call = option_type.upper() == "CALL"

    prob_itm = None
    p_above_strike = _prob_above(spot, strike, implied_vol, dte)
    if p_above_strike is not None:
        prob_itm = p_above_strike if is_call else 1.0 - p_above_strike

    # Touch approximation: for an OTM level, P(touch before expiry) ~= 2 x P(beyond at expiry).
    prob_touch = None
    if prob_itm is not None:
        otm = (is_call and spot < strike) or (not is_call and spot > strike)
        prob_touch = min(2.0 * prob_itm, 0.99) if otm else None  # already beyond -> touch is trivially ~certain
        if not otm:
            prob_touch = 0.99

    breakeven = round(strike + premium, 2) if is_call else round(strike - premium, 2)
    p_above_be = _prob_above(spot, breakeven, implied_vol, dte) if premium > 0 else None
    prob_profit = None
    if p_above_be is not None:
        prob_profit = p_above_be if is_call else 1.0 - p_above_be

    expected_move = None
    expected_move_source = None
    if chain_expected_move is not None:
        expected_move = chain_expected_move
        expected_move_source = "options chain straddle"
    elif implied_vol > 0 and dte > 0:
        expected_move = round(spot * implied_vol * math.sqrt(dte / 365.0), 2)
        expected_move_source = "IV model"

    # Expected value per contract using the plan's own exits: win = TP1 hit
    # (approximated by prob_profit), loss = stop (premium -> stop_loss).
    expected_value = None
    if prob_profit is not None and take_profit_1 is not None and stop_loss is not None and premium > 0:
        win_amount = (take_profit_1 - premium) * 100
        loss_amount = (premium - stop_loss) * 100
        expected_value = round(prob_profit * win_amount - (1.0 - prob_profit) * loss_amount, 2)

    vol_crush = None
    if days_to_earnings is not None and 0 <= days_to_earnings <= dte:
        if iv_rank is not None and iv_rank >= 70:
            vol_crush = "HIGH"
        else:
            vol_crush = "MODERATE"
    elif iv_rank is not None:
        vol_crush = "LOW" if iv_rank < 60 else "MODERATE"

    return ProbabilityProfile(
        prob_itm_pct=round(prob_itm * 100, 1) if prob_itm is not None else None,
        prob_touch_pct=round(prob_touch * 100, 1) if prob_touch is not None else None,
        prob_profit_pct=round(prob_profit * 100, 1) if prob_profit is not None else None,
        breakeven_price=breakeven if premium > 0 else None,
        expected_move_dollars=expected_move,
        expected_move_source=expected_move_source,
        expected_value_dollars=expected_value,
        vol_crush_risk=vol_crush,
    )


def render_probability_chart(
    *, symbol: str, spot: float, strike: float, option_type: str, breakeven: Optional[float],
    implied_vol: float, dte: int, expected_move: Optional[float],
) -> Optional[str]:
    """Render the model price distribution at expiry with strike/breakeven
    markers to a PNG; returns the file path, or None if charting is
    unavailable. Never raises."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
    except Exception:
        logger.info("matplotlib not available — skipping probability chart")
        return None

    try:
        if spot <= 0 or implied_vol <= 0 or dte <= 0:
            return None
        t = dte / 365.0
        sigma = implied_vol * math.sqrt(t)
        mu = math.log(spot) - 0.5 * sigma * sigma
        xs = np.linspace(spot * max(0.05, 1 - 4 * sigma), spot * (1 + 4 * sigma), 400)
        pdf = (1.0 / (xs * sigma * math.sqrt(2 * math.pi))) * np.exp(-((np.log(xs) - mu) ** 2) / (2 * sigma * sigma))

        is_call = option_type.upper() == "CALL"
        fig, ax = plt.subplots(figsize=(8, 4.2), dpi=110)
        ax.plot(xs, pdf, color="#5865F2", linewidth=2, label=f"Model distribution at expiry ({dte} DTE)")
        if breakeven:
            mask = xs >= breakeven if is_call else xs <= breakeven
            ax.fill_between(xs[mask], pdf[mask], alpha=0.30, color="#57F287", label="Profit zone (past breakeven)")
            ax.axvline(breakeven, color="#57F287", linestyle="--", linewidth=1.4, label=f"Breakeven ${breakeven:,.2f}")
        ax.axvline(spot, color="#FFFFFF", linestyle="-", linewidth=1.2, label=f"Spot ${spot:,.2f}")
        ax.axvline(strike, color="#FEE75C", linestyle=":", linewidth=1.6, label=f"Strike ${strike:,.2f}")
        if expected_move:
            ax.axvspan(spot - expected_move, spot + expected_move, alpha=0.10, color="#EB459E", label=f"Expected move ±${expected_move:,.2f}")
        ax.set_title(f"{symbol} {option_type.upper()} — probability profile (lognormal model, IV {implied_vol:.0%})", color="white", fontsize=11)
        ax.set_xlabel("Price at expiration")
        ax.set_yticks([])
        ax.legend(loc="upper right", fontsize=7.5, framealpha=0.25)
        fig.patch.set_facecolor("#2B2D31")
        ax.set_facecolor("#2B2D31")
        for spine in ax.spines.values():
            spine.set_color("#4E5058")
        ax.xaxis.label.set_color("#B5BAC1")
        ax.tick_params(colors="#B5BAC1")

        path = f"/tmp/prob_{symbol}_{option_type.lower()}.png"
        fig.tight_layout()
        fig.savefig(path, facecolor=fig.get_facecolor())
        plt.close(fig)
        return path
    except Exception as exc:
        logger.warning("Probability chart failed for %s: %s", symbol, exc)
        try:
            plt.close("all")
        except Exception:
            pass
        return None
