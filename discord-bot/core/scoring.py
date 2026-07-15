"""V4 Trade Scoring Engine.

Turns the tag-based conviction signal (technicals, volume, market, news --
already computed by `ai_engine._active_tags` using the self-learning
strategy weights in SQLite) plus the chosen option contract's own data
(IV rank/percentile, put/call ratio, max pain, liquidity, greeks) and the
side-matched historical backtest into ONE weighted 0-100 score, broken down
by category so every point is explainable.

Every number here is derived from data already fetched and verified
elsewhere (technicals.py, market.py, news.py, earnings.py, options.py,
backtester.py) -- nothing here fabricates a price or statistic. If an
input is missing, its category simply scores 0 (no signal) rather than a
guessed value.
"""

from dataclasses import dataclass, field
from typing import Optional

from core import backtester as backtester_module, earnings as earnings_module, options as options_module

# Point budget per category. Trend/Momentum/Volume/Market/News/Options Data
# sum to 100 at their max; Risk is a penalty-only-by-default bucket that can
# also award a small bonus for a strong side-matched historical edge.
CATEGORY_MAX = {
    "trend": 20.0,
    "momentum": 20.0,
    "volume": 15.0,
    "market": 15.0,
    "news": 10.0,
    "options_data": 20.0,
}
RISK_MIN, RISK_MAX = -15.0, 5.0

def _trend_sets(side: str) -> tuple[set[str], set[str]]:
    # Bullish/bearish tag variants are mutually exclusive per side (a call's
    # tag list can only ever contain the bullish variant of each slot, never
    # both) -- so the favorable/headwind sets must be resolved per side.
    # Counting both variants in one shared set would double the theoretical
    # ceiling and make every score artificially small.
    if side == "call":
        return (
            {"trend_stack_bullish", "above_ema50", "bullish_breakout", "room_to_resistance"},
            {"resistance_overhead"},
        )
    return (
        {"trend_stack_bearish", "below_ema50", "bearish_breakdown", "room_to_support"},
        {"support_below"},
    )


def _momentum_sets(side: str) -> tuple[set[str], set[str]]:
    if side == "call":
        return {"rsi_bullish", "macd_bullish", "adx_strong_trend", "supertrend_bullish"}, {"rsi_overbought", "rsi_oversold"}
    return {"rsi_bearish", "macd_bearish", "adx_strong_trend", "supertrend_bearish"}, {"rsi_overbought", "rsi_oversold"}


# Volume/market/news tags are already side-resolved to a single shared tag
# name by `_active_tags` (e.g. "positive_news_sentiment" means "favorable for
# whichever side is being scored"), so these sets are safe to use as-is.
_VOLUME_FAVORABLE = {"volume_confirmation", "high_relative_volume"}
_MARKET_FAVORABLE = {"market_trend_aligned", "vix_supportive", "relative_strength_positive"}
_MARKET_HEADWIND = {"market_trend_against", "vix_elevated", "relative_strength_negative"}
_NEWS_FAVORABLE = {"positive_news_sentiment", "analyst_upgrade", "insider_buying"}
_NEWS_HEADWIND = {"negative_news_sentiment", "analyst_downgrade", "insider_selling"}


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(value, high))


def _bucket_points(tags: list[str], weights: dict[str, float], favorable: set[str], headwind: set[str], budget: float) -> float:
    """Sums weighted signed contributions for tags in this bucket, scaled to
    the bucket's point budget.

    The denominator is the LARGER of the favorable-side and headwind-side
    weight totals, not their sum: for every signal modeled here, favorable
    and headwind are opposite outcomes of the same underlying check (e.g.
    "market trend aligned" vs "market trend against"), so only one side can
    ever be active at once. Summing both into one denominator would make the
    full budget mathematically unreachable even in a textbook-perfect setup.
    """
    active_favorable = [t for t in tags if t in favorable]
    active_headwind = [t for t in tags if t in headwind]
    if not active_favorable and not active_headwind:
        return 0.0
    raw = sum(weights.get(t, 1.0) for t in active_favorable) - sum(weights.get(t, 1.0) for t in active_headwind)
    max_possible = max(
        sum(weights.get(t, 1.0) for t in favorable),
        sum(weights.get(t, 1.0) for t in headwind),
    ) or 1.0
    return round(_clamp(raw / max_possible, -1.0, 1.0) * budget, 1)


@dataclass
class ScoreBreakdown:
    side: str  # "call" | "put"
    trend: float
    momentum: float
    volume: float
    market: float
    news: float
    options_data: float
    risk: float
    final_score: float
    notes: list[str] = field(default_factory=list)


def _options_data_score(
    side: str, chain: options_module.ChainAnalysis, candidate: options_module.ScoredContract,
) -> tuple[float, list[str]]:
    notes: list[str] = []
    points = 0.0

    # Probability edge (0-6): how far the contract's probability ITM sits
    # above a coin-flip 50%.
    prob_edge = _clamp((candidate.probability_score - 50.0) / 50.0, -1.0, 1.0)
    points += prob_edge * 6

    # Liquidity (0-5)
    points += _clamp(candidate.liquidity_score / 100.0, 0.0, 1.0) * 5

    # IV rank sweet spot (0-3): too low = flat premium, too high = expensive/risky
    if chain.iv_rank is not None:
        iv_fit = 1.0 - abs(chain.iv_rank - 40.0) / 60.0
        points += _clamp(iv_fit, 0.0, 1.0) * 3

    # Put/call ratio skew supporting the chosen side (0/-2/+2)
    if chain.put_call_ratio is not None:
        if side == "call" and chain.put_call_ratio < 0.9:
            points += 2
            notes.append("Put/call ratio skewed toward calls")
        elif side == "put" and chain.put_call_ratio > 1.1:
            points += 2
            notes.append("Put/call ratio skewed toward puts")
        elif side == "call" and chain.put_call_ratio > 1.3:
            points -= 2
        elif side == "put" and chain.put_call_ratio < 0.7:
            points -= 2

    # Max pain pull (0/+2): spot being pulled toward max pain in the trade's direction
    spot = candidate.contract.strike  # fallback reference if needed
    if chain.max_pain is not None:
        notes.append(f"Max pain at ${chain.max_pain:.2f}")

    # Expected-return / greeks sub-scores already computed per contract
    points += _clamp(candidate.expected_return_score / 100.0, 0.0, 1.0) * 3
    points += _clamp(candidate.greeks_score / 100.0, 0.0, 1.0) * 1

    return round(_clamp(points, 0.0, CATEGORY_MAX["options_data"]), 1), notes


def _risk_score(
    side: str, candidate: options_module.ScoredContract, earnings_ctx: earnings_module.EarningsContext,
    backtest: Optional[backtester_module.BacktestResult],
) -> tuple[float, list[str]]:
    notes: list[str] = []
    points = 0.0

    if earnings_ctx.days_to_earnings is not None and 0 <= earnings_ctx.days_to_earnings <= 7:
        points -= 5
        notes.append(f"Earnings in {earnings_ctx.days_to_earnings}d -- event risk inside the option's window")
        if candidate.contract.implied_vol > 1.0:
            points -= 5
            notes.append("IV extremely elevated ahead of earnings")

    if candidate.risk_score < 50:
        points -= 3
        notes.append("Elevated theta decay / IV relative to premium")

    if candidate.liquidity_score < 70:
        points -= 4
        notes.append("Liquidity close to the filter threshold")

    if backtest is not None and backtest.win_rate is not None:
        if backtest.win_rate < 50:
            points -= 5
            notes.append(f"Historical win rate only {backtest.win_rate}% for this setup")
        elif backtest.win_rate >= 70:
            points += 5
            notes.append(f"Historical win rate {backtest.win_rate}% supports this setup")

    return round(_clamp(points, RISK_MIN, RISK_MAX), 1), notes


def compute_score(
    *, side: str, tags: list[str], weights: dict[str, float],
    chain: options_module.ChainAnalysis, candidate: options_module.ScoredContract,
    earnings_ctx: earnings_module.EarningsContext,
    backtest: Optional[backtester_module.BacktestResult],
) -> ScoreBreakdown:
    trend_favorable, trend_headwind = _trend_sets(side)
    momentum_favorable, momentum_headwind = _momentum_sets(side)
    trend = _bucket_points(tags, weights, trend_favorable, trend_headwind, CATEGORY_MAX["trend"])
    momentum = _bucket_points(tags, weights, momentum_favorable, momentum_headwind, CATEGORY_MAX["momentum"])
    volume = _bucket_points(tags, weights, _VOLUME_FAVORABLE, set(), CATEGORY_MAX["volume"])
    market = _bucket_points(tags, weights, _MARKET_FAVORABLE, _MARKET_HEADWIND, CATEGORY_MAX["market"])
    news = _bucket_points(tags, weights, _NEWS_FAVORABLE, _NEWS_HEADWIND, CATEGORY_MAX["news"])
    options_data, opt_notes = _options_data_score(side, chain, candidate)
    risk, risk_notes = _risk_score(side, candidate, earnings_ctx, backtest)

    # Baseline of 40 when a category has literally no signal either way is
    # deliberately NOT applied here -- an empty bucket scores 0, which is
    # honest (no evidence), not "neutral confidence."
    final = _clamp(trend + momentum + volume + market + news + options_data + risk, 0.0, 100.0)

    return ScoreBreakdown(
        side=side, trend=trend, momentum=momentum, volume=volume, market=market,
        news=news, options_data=options_data, risk=risk, final_score=round(final, 1),
        notes=opt_notes + risk_notes,
    )


_GRADE_THRESHOLDS = [
    (95, "A+"), (90, "A"), (85, "A-"), (80, "B+"), (75, "B"), (70, "B-"),
    (65, "C+"), (60, "C"), (55, "C-"), (50, "D+"), (45, "D"), (0, "F"),
]


def trade_grade(final_score: float) -> str:
    for threshold, grade in _GRADE_THRESHOLDS:
        if final_score >= threshold:
            return grade
    return "F"
