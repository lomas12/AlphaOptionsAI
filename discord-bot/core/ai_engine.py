"""AlphaOptionsAI V3 decision engine.

Combines technicals, options chain analysis, market context, news/analyst/
insider context, and earnings proximity into tagged bullish/bearish
conviction scores, blends them with contract liquidity, and picks exactly
ONE trade (or NO TRADE) using self-learning strategy weights from SQLite.

No field is ever fabricated: if a data source is unavailable, the
corresponding tag simply doesn't fire and the missing fields are surfaced
in `TradeDecision.missing_data` so the embed can say "Data unavailable
from API" instead of a silent gap.
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from apis import router
from apis.yahoo import clean_ticker
from core import (
    backtester as backtester_module, database, earnings as earnings_module, market as market_module,
    market_data as market_data_module, news as news_module, options as options_module, risk as risk_module,
    scoring as scoring_module, technicals as technicals_module,
)

CONFIDENCE_TRADE_THRESHOLD = 70.0
MIN_HISTORICAL_WIN_RATE = 60.0
SECTOR_ETF_HINTS = market_module.SECTOR_ETFS

MarketDataUnavailableError = market_data_module.MarketDataUnavailableError

VERIFIED_DATA_UNAVAILABLE_MESSAGE = "Verified market data unavailable. No recommendation generated."


class TickerNotFoundError(Exception):
    pass


@dataclass
class TradeDecision:
    ticker: str
    price: float
    recommendation: str  # "BUY CALL" | "BUY PUT" | "NO TRADE"
    confidence: float
    reasoning: list[str]
    contract: Optional[dict]
    entry: Optional[float]
    take_profit_1: Optional[float]
    take_profit_2: Optional[float]
    stop_loss: Optional[float]
    risk_reward_ratio: Optional[float]
    dollar_risk_per_contract: Optional[float]
    max_risk_dollars: Optional[float]
    position_size_contracts: Optional[int]
    risk_rating: Optional[str]
    tags: list[str]
    account_balance: float
    snapshot: technicals_module.TechnicalSnapshot
    market: market_module.MarketContext
    news_context: news_module.TickerNewsContext
    earnings_context: earnings_module.EarningsContext
    chain_analysis: Optional[options_module.ChainAnalysis]
    missing_data: list[str]
    price_source: str
    price_as_of: datetime
    score_breakdown: Optional[scoring_module.ScoreBreakdown] = None
    trade_grade: Optional[str] = None
    backtest: Optional[backtester_module.BacktestResult] = None
    ai_summary: Optional[str] = None
    risk_pct_used: Optional[float] = None
    expected_reward_dollars: Optional[float] = None
    rejected_contracts: list[str] = field(default_factory=list)


_HEADWIND_TAGS = {
    "resistance_overhead", "support_below", "rsi_overbought", "rsi_oversold",
    "market_trend_against", "vix_elevated", "negative_news_sentiment",
    "analyst_downgrade", "insider_selling", "earnings_event_risk", "relative_strength_negative",
}


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(value, high))


def _active_tags(
    *, side: str, snapshot: technicals_module.TechnicalSnapshot, market: market_module.MarketContext,
    news_ctx: news_module.TickerNewsContext, earnings_ctx: earnings_module.EarningsContext,
    relative_strength: Optional[float],
) -> list[str]:
    tags: list[str] = []
    price = snapshot.price

    bullish = side == "call"
    if snapshot.trend_strength == ("Strong Bullish" if bullish else "Strong Bearish"):
        tags.append("trend_stack_bullish" if bullish else "trend_stack_bearish")
    if snapshot.ema50:
        if bullish and price > snapshot.ema50:
            tags.append("above_ema50")
        if not bullish and price < snapshot.ema50:
            tags.append("below_ema50")

    if snapshot.rsi14 is not None:
        if bullish and 40 <= snapshot.rsi14 <= 65:
            tags.append("rsi_bullish")
        if not bullish and 35 <= snapshot.rsi14 <= 60:
            tags.append("rsi_bearish")
        if snapshot.rsi14 > 75:
            tags.append("rsi_overbought")
        if snapshot.rsi14 < 25:
            tags.append("rsi_oversold")

    if snapshot.macd_line is not None and snapshot.macd_signal is not None:
        if bullish and snapshot.macd_line > snapshot.macd_signal:
            tags.append("macd_bullish")
        if not bullish and snapshot.macd_line < snapshot.macd_signal:
            tags.append("macd_bearish")

    if snapshot.adx14 is not None and snapshot.adx14 > 25:
        tags.append("adx_strong_trend")

    if snapshot.supertrend_direction:
        if bullish and snapshot.supertrend_direction == "Bullish":
            tags.append("supertrend_bullish")
        if not bullish and snapshot.supertrend_direction == "Bearish":
            tags.append("supertrend_bearish")

    if snapshot.volume and snapshot.avg_volume20 and snapshot.volume > snapshot.avg_volume20:
        tags.append("volume_confirmation")
    if snapshot.relative_volume and snapshot.relative_volume > 1.5:
        tags.append("high_relative_volume")

    if bullish and snapshot.resistance and (snapshot.resistance - price) / price > 0.03:
        tags.append("room_to_resistance")
    if bullish and snapshot.resistance and (snapshot.resistance - price) / price < 0.015:
        tags.append("resistance_overhead")
    if not bullish and snapshot.support and (price - snapshot.support) / price > 0.03:
        tags.append("room_to_support")
    if not bullish and snapshot.support and (price - snapshot.support) / price < 0.015:
        tags.append("support_below")

    if bullish and snapshot.breakout == "Bullish Breakout":
        tags.append("bullish_breakout")
    if not bullish and snapshot.breakout == "Bearish Breakdown":
        tags.append("bearish_breakdown")

    if bullish and (market.spy_trend == "Bullish" or market.qqq_trend == "Bullish"):
        tags.append("market_trend_aligned")
    if not bullish and (market.spy_trend == "Bearish" or market.qqq_trend == "Bearish"):
        tags.append("market_trend_aligned")
    if bullish and market.spy_trend == "Bearish" and market.qqq_trend == "Bearish":
        tags.append("market_trend_against")
    if not bullish and market.spy_trend == "Bullish" and market.qqq_trend == "Bullish":
        tags.append("market_trend_against")

    if market.vix_classification == "Low":
        tags.append("vix_supportive")
    if market.vix_classification == "Elevated":
        tags.append("vix_elevated")

    # News/analyst/insider signals are side-aware: good news supports calls
    # and is a headwind for puts, and vice versa -- a signal should never
    # inflate both directions at once.
    if news_ctx.news_sentiment == "Positive":
        tags.append("positive_news_sentiment" if bullish else "negative_news_sentiment")
    if news_ctx.news_sentiment == "Negative":
        tags.append("negative_news_sentiment" if bullish else "positive_news_sentiment")

    if news_ctx.analyst_action and news_ctx.analyst_action.action == "Upgrade":
        tags.append("analyst_upgrade" if bullish else "analyst_downgrade")
    if news_ctx.analyst_action and news_ctx.analyst_action.action == "Downgrade":
        tags.append("analyst_downgrade" if bullish else "analyst_upgrade")

    buys = sum(1 for t in news_ctx.insider_transactions if "buy" in t.transaction_type.lower())
    sells = sum(1 for t in news_ctx.insider_transactions if "sale" in t.transaction_type.lower() or "sell" in t.transaction_type.lower())
    if buys > sells and buys > 0:
        tags.append("insider_buying" if bullish else "insider_selling")
    if sells > buys and sells > 0:
        tags.append("insider_selling" if bullish else "insider_buying")

    if earnings_ctx.days_to_earnings is not None and 0 <= earnings_ctx.days_to_earnings <= 30:
        tags.append("earnings_event_risk")

    if relative_strength is not None:
        if bullish and relative_strength > 0:
            tags.append("relative_strength_positive")
        if not bullish and relative_strength < 0:
            tags.append("relative_strength_negative")

    return list(dict.fromkeys(tags))  # de-dupe, preserve order


def _conviction_score(tags: list[str], weights: dict[str, float]) -> float:
    if not tags:
        return 40.0
    total = 0.0
    max_possible = 0.0
    for tag in tags:
        weight = weights.get(tag, 1.0)
        max_possible += weight
        total += -weight if tag in _HEADWIND_TAGS else weight
    if max_possible <= 0:
        return 40.0
    normalized = 0.5 + (total / max_possible) / 2
    return round(_clamp(normalized * 100), 1)


_REASONING_LABELS = {
    "trend_stack_bullish": "Bullish trend stack across EMA20/50/200",
    "trend_stack_bearish": "Bearish trend stack across EMA20/50/200",
    "above_ema50": "Trading above EMA50",
    "below_ema50": "Trading below EMA50",
    "rsi_bullish": "RSI holding a healthy bullish range",
    "rsi_bearish": "RSI holding a bearish range",
    "rsi_overbought": "RSI overbought -- pullback risk",
    "rsi_oversold": "RSI oversold -- bounce risk",
    "macd_bullish": "MACD bullish crossover",
    "macd_bearish": "MACD bearish crossover",
    "adx_strong_trend": "ADX confirms a strong trend",
    "supertrend_bullish": "SuperTrend flipped bullish",
    "supertrend_bearish": "SuperTrend flipped bearish",
    "volume_confirmation": "Volume confirming the move",
    "high_relative_volume": "Relative volume well above normal",
    "room_to_resistance": "Clear room to resistance overhead",
    "resistance_overhead": "Resistance sitting close overhead",
    "room_to_support": "Clear room down to support",
    "support_below": "Support sitting close below",
    "bullish_breakout": "Price broke out above resistance",
    "bearish_breakdown": "Price broke down below support",
    "market_trend_aligned": "Broader market (SPY/QQQ) trend aligned",
    "market_trend_against": "Broader market trend working against this trade",
    "vix_supportive": "VIX calm, supportive of trend continuation",
    "vix_elevated": "VIX elevated -- higher volatility risk",
    "positive_news_sentiment": "Recent news sentiment positive",
    "negative_news_sentiment": "Recent news sentiment negative",
    "analyst_upgrade": "Recent analyst upgrade",
    "analyst_downgrade": "Recent analyst downgrade",
    "insider_buying": "Recent insider buying",
    "insider_selling": "Recent insider selling",
    "earnings_event_risk": "Earnings event inside the option's window",
    "relative_strength_positive": "Outperforming SPY (relative strength)",
    "relative_strength_negative": "Underperforming SPY (relative strength)",
}


def _build_reasoning(tags: list[str], news_ctx: news_module.TickerNewsContext) -> list[str]:
    reasoning = [_REASONING_LABELS[t] for t in tags if t in _REASONING_LABELS]
    if not reasoning:
        reasoning.append("No strong directional signal in current data")
    if news_ctx.news_items:
        reasoning.append(f"Headline: \"{news_ctx.news_items[0].title}\"")
    return reasoning


def _resolve_account_settings(account_balance: Optional[float], risk_pct: Optional[float]) -> tuple[float, float]:
    if account_balance is None:
        saved_balance = database.get_account_balance()
        account_balance = saved_balance if saved_balance is not None else risk_module.ACCOUNT_BALANCE_DEFAULT
    if risk_pct is None:
        saved_risk_pct = database.get_risk_pct()
        risk_pct = saved_risk_pct if saved_risk_pct is not None else risk_module.MAX_ACCOUNT_RISK_PCT
    return account_balance, risk_pct


async def analyze_ticker(
    raw_ticker: str, account_balance: Optional[float] = None, risk_pct: Optional[float] = None,
) -> TradeDecision:
    return await asyncio.to_thread(_analyze_ticker_sync, raw_ticker, account_balance, risk_pct)


def _analyze_ticker_sync(
    raw_ticker: str, account_balance: Optional[float] = None, risk_pct: Optional[float] = None,
) -> TradeDecision:
    account_balance, risk_pct = _resolve_account_settings(account_balance, risk_pct)
    symbol = clean_ticker(raw_ticker)
    if not symbol:
        raise TickerNotFoundError(f"❌ Could not find ticker {raw_ticker!r}")

    missing_data: list[str] = []

    # Verify the current price before doing anything else: fresh, matches
    # the latest market quote, and never estimated/hardcoded. Every
    # downstream calculation (technicals, expected move, support/
    # resistance, strike selection, greeks, probability) uses this same
    # verified price.
    verified_quote = market_data_module.get_verified_quote(symbol)
    current_price = verified_quote.price
    price_source = verified_quote.source
    price_as_of = verified_quote.as_of

    history_result = router.get_history(symbol, period="1y", interval="1d")
    if not history_result.available:
        raise TickerNotFoundError(f"❌ Could not find ticker {symbol}")
    hist = history_result.value.df

    snapshot = technicals_module.compute_snapshot(hist, current_price)
    market = market_module.get_market_context()
    news_ctx = news_module.get_ticker_news_context(symbol)
    earnings_ctx = earnings_module.get_earnings_context(symbol)
    relative_strength = market_module.get_relative_strength(symbol)

    if market.vix_level is None:
        missing_data.append("VIX level")
    if market.treasury_10y_yield is None:
        missing_data.append("10-Year Treasury yield")
    if market.dollar_index is None:
        missing_data.append("Dollar Index")
    if not news_ctx.news_items:
        missing_data.append("Recent news")
    if earnings_ctx.earnings_date is None:
        missing_data.append("Earnings date")

    weights = database.get_weights()
    call_tags = _active_tags(side="call", snapshot=snapshot, market=market, news_ctx=news_ctx, earnings_ctx=earnings_ctx, relative_strength=relative_strength)
    put_tags = _active_tags(side="put", snapshot=snapshot, market=market, news_ctx=news_ctx, earnings_ctx=earnings_ctx, relative_strength=relative_strength)
    call_conviction = _conviction_score(call_tags, weights)
    put_conviction = _conviction_score(put_tags, weights)

    chain_analysis = options_module.analyze_chain(symbol, current_price, hist["Close"].dropna())
    if chain_analysis is None:
        missing_data.append("Options chain")
        return TradeDecision(
            ticker=symbol, price=current_price, recommendation="NO TRADE", confidence=0.0,
            reasoning=["No options chain available for this ticker -- Data unavailable from API"],
            contract=None, entry=None, take_profit_1=None, take_profit_2=None, stop_loss=None,
            risk_reward_ratio=None, dollar_risk_per_contract=None, max_risk_dollars=None,
            position_size_contracts=None, risk_rating=None, tags=[], account_balance=account_balance,
            snapshot=snapshot, market=market, news_context=news_ctx, earnings_context=earnings_ctx,
            chain_analysis=None, missing_data=missing_data, price_source=price_source, price_as_of=price_as_of,
            risk_pct_used=risk_pct,
        )

    # Smart Contract Filter + composite ranking: pick the single best
    # qualifying contract on each side (never both), auto-falling through
    # to the next-best candidate when one is rejected for liquidity/spread/
    # theta-decay/pre-earnings-IV reasons.
    best_call, call_rejected = options_module.select_best_contract(
        chain_analysis.calls, days_to_earnings=earnings_ctx.days_to_earnings
    )
    best_put, put_rejected = options_module.select_best_contract(
        chain_analysis.puts, days_to_earnings=earnings_ctx.days_to_earnings
    )

    side_candidates: dict[str, tuple[options_module.ScoredContract, list[str]]] = {}
    if best_call is not None:
        side_candidates["call"] = (best_call, call_tags)
    if best_put is not None:
        side_candidates["put"] = (best_put, put_tags)

    if not side_candidates:
        return TradeDecision(
            ticker=symbol, price=current_price, recommendation="NO TRADE", confidence=0.0,
            reasoning=["No contract on either side survived the Smart Contract Filter "
                       "(open interest, volume, spread, liquidity, or theta-decay thresholds)"],
            contract=None, entry=None, take_profit_1=None, take_profit_2=None, stop_loss=None,
            risk_reward_ratio=None, dollar_risk_per_contract=None, max_risk_dollars=None,
            position_size_contracts=None, risk_rating=None, tags=[], account_balance=account_balance,
            snapshot=snapshot, market=market, news_context=news_ctx, earnings_context=earnings_ctx,
            chain_analysis=chain_analysis, missing_data=missing_data, price_source=price_source, price_as_of=price_as_of,
            risk_pct_used=risk_pct, rejected_contracts=call_rejected + put_rejected,
        )

    # Backtest Engine: side-matched historical stats, folded into scoring
    # and the NO-TRADE gate below. Best-effort -- if there isn't enough
    # history, backtest stays None and simply contributes no signal.
    backtests: dict[str, Optional[backtester_module.BacktestResult]] = {}
    breakdowns: dict[str, scoring_module.ScoreBreakdown] = {}
    for candidate_side, (scored, side_tags) in side_candidates.items():
        bt = backtester_module.run_backtest(symbol, side=candidate_side)
        backtests[candidate_side] = bt
        breakdowns[candidate_side] = scoring_module.compute_score(
            side=candidate_side, tags=side_tags, weights=weights, chain=chain_analysis,
            candidate=scored, earnings_ctx=earnings_ctx, backtest=bt,
        )

    side = max(breakdowns, key=lambda s: breakdowns[s].final_score)
    scored, tags = side_candidates[side]
    breakdown = breakdowns[side]
    backtest = backtests[side]
    confidence = breakdown.final_score
    rejected_contracts = call_rejected + put_rejected

    if scored.unusual_activity:
        tags = tags + ["unusual_options_activity"]

    reasoning = _build_reasoning(tags, news_ctx)
    reasoning.extend(breakdown.notes)

    other_side = "put" if side == "call" else "call"
    other_score = breakdowns[other_side].final_score if other_side in breakdowns else 0.0

    no_trade_reasons = _evaluate_no_trade(
        confidence=confidence, backtest=backtest, side_score=confidence, other_score=other_score,
        news_ctx=news_ctx, chain=chain_analysis, candidate=scored,
    )

    contract = scored.contract
    premium = scored.premium if scored.premium > 0 else (
        (contract.bid + contract.ask) / 2 if contract.bid > 0 and contract.ask > 0 else contract.last_price
    )
    plan = risk_module.build_trade_plan_risk(entry=round(premium, 2), account_balance=account_balance, risk_pct=risk_pct)
    if not plan.meets_min_risk_reward:
        no_trade_reasons.append(f"Risk/reward of {plan.risk_reward_ratio}:1 is below the 2:1 minimum")

    grade = scoring_module.trade_grade(confidence)

    if contract.implied_vol > 0.75 or scored.dte <= 7 or "earnings_event_risk" in tags:
        risk_rating = "High"
    elif contract.implied_vol > 0.45 or scored.dte <= 21:
        risk_rating = "Medium"
    else:
        risk_rating = "Low"

    ai_summary = _build_ai_summary(
        symbol=symbol, side=side, confidence=confidence, grade=grade, reasoning=reasoning,
        backtest=backtest, plan=plan, no_trade=bool(no_trade_reasons),
    )

    contract_dict = {
        "option_type": side.upper(),
        "strike": contract.strike,
        "expiration": contract.expiration,
        "dte": scored.dte,
        "premium": plan.entry,
        "open_interest": contract.open_interest,
        "volume": contract.volume,
        "implied_vol": contract.implied_vol,
        "delta": scored.delta,
        "gamma": scored.gamma,
        "theta": scored.theta,
        "vega": scored.vega,
        "probability_itm": scored.probability_itm,
        "liquidity_score": scored.liquidity_score,
        "unusual_activity": scored.unusual_activity,
        "spread_pct": round(scored.spread_pct * 100, 2),
        "bid": contract.bid,
        "ask": contract.ask,
        "iv_rank": chain_analysis.iv_rank,
        "iv_percentile": chain_analysis.iv_percentile,
        "expected_move": chain_analysis.expected_move,
        "expected_move_pct": chain_analysis.expected_move_pct,
        "composite_score": scored.composite_score,
    }

    if no_trade_reasons:
        return TradeDecision(
            ticker=symbol, price=current_price, recommendation="NO TRADE", confidence=confidence,
            reasoning=reasoning + [f"NO TRADE: {reason}" for reason in no_trade_reasons],
            contract=contract_dict, entry=plan.entry, take_profit_1=plan.take_profit_1,
            take_profit_2=plan.take_profit_2, stop_loss=plan.stop_loss, risk_reward_ratio=plan.risk_reward_ratio,
            dollar_risk_per_contract=plan.dollar_risk_per_contract, max_risk_dollars=plan.max_risk_dollars,
            position_size_contracts=plan.position_size_contracts, risk_rating=risk_rating, tags=tags,
            account_balance=account_balance, snapshot=snapshot, market=market, news_context=news_ctx,
            earnings_context=earnings_ctx, chain_analysis=chain_analysis, missing_data=missing_data,
            price_source=price_source, price_as_of=price_as_of, score_breakdown=breakdown, trade_grade=grade,
            backtest=backtest, ai_summary=ai_summary, risk_pct_used=risk_pct,
            expected_reward_dollars=plan.expected_reward_dollars, rejected_contracts=rejected_contracts,
        )

    return TradeDecision(
        ticker=symbol, price=current_price, recommendation=f"BUY {side.upper()}", confidence=confidence,
        reasoning=reasoning, contract=contract_dict, entry=plan.entry, take_profit_1=plan.take_profit_1,
        take_profit_2=plan.take_profit_2, stop_loss=plan.stop_loss, risk_reward_ratio=plan.risk_reward_ratio,
        dollar_risk_per_contract=plan.dollar_risk_per_contract, max_risk_dollars=plan.max_risk_dollars,
        position_size_contracts=plan.position_size_contracts, risk_rating=risk_rating, tags=tags,
        account_balance=account_balance, snapshot=snapshot, market=market, news_context=news_ctx,
        earnings_context=earnings_ctx, chain_analysis=chain_analysis, missing_data=missing_data,
        price_source=price_source, price_as_of=price_as_of, score_breakdown=breakdown, trade_grade=grade,
        backtest=backtest, ai_summary=ai_summary, risk_pct_used=risk_pct,
        expected_reward_dollars=plan.expected_reward_dollars, rejected_contracts=rejected_contracts,
    )


def _evaluate_no_trade(
    *, confidence: float, backtest: Optional[backtester_module.BacktestResult], side_score: float,
    other_score: float, news_ctx: news_module.TickerNewsContext,
    chain: options_module.ChainAnalysis, candidate: options_module.ScoredContract,
) -> list[str]:
    """Every trigger is explained -- NO TRADE never fires silently."""
    reasons: list[str] = []

    if confidence < CONFIDENCE_TRADE_THRESHOLD:
        reasons.append(f"Confidence {confidence}% is below the {CONFIDENCE_TRADE_THRESHOLD}% action threshold")

    if backtest is not None and backtest.win_rate is not None and backtest.win_rate < MIN_HISTORICAL_WIN_RATE:
        reasons.append(
            f"Historical win rate for this setup is only {backtest.win_rate}% "
            f"(below the {MIN_HISTORICAL_WIN_RATE}% minimum, {backtest.total_trades} occurrences)"
        )

    if abs(side_score - other_score) < 8 and side_score < 75 and other_score < 75:
        reasons.append(
            f"Conflicting indicators -- call and put setups score within {round(abs(side_score - other_score), 1)} "
            "points of each other with no clear edge"
        )

    if not news_ctx.news_items and news_ctx.news_sentiment is None:
        reasons.append("No recent news available -- elevated uncertainty with no sentiment confirmation")

    if chain.iv_rank is not None and chain.iv_rank > 85 and candidate.expected_return_score < 40:
        reasons.append(
            f"IV rank {chain.iv_rank}% is extreme relative to this contract's modest expected-return profile"
        )

    return reasons


def _build_ai_summary(
    *, symbol: str, side: str, confidence: float, grade: str, reasoning: list[str],
    backtest: Optional[backtester_module.BacktestResult], plan: risk_module.TradePlanRisk, no_trade: bool,
) -> str:
    sentences: list[str] = []
    direction = "bullish" if side == "call" else "bearish"

    if no_trade:
        sentences.append(
            f"{symbol} scored {confidence}% ({grade}) on the {direction} side, but one or more risk gates blocked a trade."
        )
    else:
        sentences.append(
            f"{symbol} scores {confidence}% ({grade}) confidence for a {direction} setup, "
            f"anchored by: {', '.join(reasoning[:2]) if reasoning else 'baseline technicals'}."
        )

    if backtest is not None and backtest.win_rate is not None:
        sentences.append(
            f"Historically, this side-matched setup won {backtest.win_rate}% of "
            f"{backtest.total_trades} occurrences over the {backtest.period} lookback "
            f"(avg hold {backtest.avg_hold_days} days)."
        )
    else:
        sentences.append("Not enough historical occurrences of this exact setup to compute a reliable backtest.")

    sentences.append(
        f"Risk plan: {plan.risk_reward_ratio}:1 reward-to-risk, "
        f"{plan.position_size_contracts} contract(s) risking ${plan.max_risk_dollars} "
        f"({round(plan.risk_pct_used * 100, 1)}% of the ${plan.account_balance:,.0f} account)."
    )

    if len(reasoning) > 2:
        sentences.append(f"Additional context: {'; '.join(reasoning[2:5])}.")

    return " ".join(sentences)
