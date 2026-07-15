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
from core import database, earnings as earnings_module, market as market_module, market_data as market_data_module, news as news_module, options as options_module, risk as risk_module, technicals as technicals_module

CONFIDENCE_TRADE_THRESHOLD = 70.0
SECTOR_ETF_HINTS = market_module.SECTOR_ETFS

MarketDataUnavailableError = market_data_module.MarketDataUnavailableError


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

    if news_ctx.news_sentiment == "Positive":
        tags.append("positive_news_sentiment" if bullish else "negative_news_sentiment" if False else "positive_news_sentiment")
    if news_ctx.news_sentiment == "Negative":
        tags.append("negative_news_sentiment")

    if news_ctx.analyst_action and news_ctx.analyst_action.action == "Upgrade":
        tags.append("analyst_upgrade")
    if news_ctx.analyst_action and news_ctx.analyst_action.action == "Downgrade":
        tags.append("analyst_downgrade")

    buys = sum(1 for t in news_ctx.insider_transactions if "buy" in t.transaction_type.lower())
    sells = sum(1 for t in news_ctx.insider_transactions if "sale" in t.transaction_type.lower() or "sell" in t.transaction_type.lower())
    if buys > sells and buys > 0:
        tags.append("insider_buying")
    if sells > buys and sells > 0:
        tags.append("insider_selling")

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


async def analyze_ticker(raw_ticker: str, account_balance: float = risk_module.ACCOUNT_BALANCE_DEFAULT) -> TradeDecision:
    return await asyncio.to_thread(_analyze_ticker_sync, raw_ticker, account_balance)


def _analyze_ticker_sync(raw_ticker: str, account_balance: float) -> TradeDecision:
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
        )

    best_call = max(chain_analysis.calls, key=lambda c: c.liquidity_score)
    best_put = max(chain_analysis.puts, key=lambda p: p.liquidity_score)

    call_confidence = round((best_call.liquidity_score + call_conviction) / 2, 1)
    put_confidence = round((best_put.liquidity_score + put_conviction) / 2, 1)

    if earnings_ctx.days_to_earnings is not None and 0 <= earnings_ctx.days_to_earnings <= 7:
        call_confidence = max(0.0, call_confidence - 8)
        put_confidence = max(0.0, put_confidence - 8)

    if call_confidence >= put_confidence:
        side, scored, tags, confidence = "call", best_call, call_tags, call_confidence
    else:
        side, scored, tags, confidence = "put", best_put, put_tags, put_confidence

    if scored.unusual_activity:
        tags = tags + ["unusual_options_activity"]

    reasoning = _build_reasoning(tags, news_ctx)

    if confidence < CONFIDENCE_TRADE_THRESHOLD:
        return TradeDecision(
            ticker=symbol, price=current_price, recommendation="NO TRADE", confidence=confidence,
            reasoning=reasoning + ["Confidence below the 70% action threshold -- waiting for confirmation"],
            contract=None, entry=None, take_profit_1=None, take_profit_2=None, stop_loss=None,
            risk_reward_ratio=None, dollar_risk_per_contract=None, max_risk_dollars=None,
            position_size_contracts=None, risk_rating=None, tags=tags, account_balance=account_balance,
            snapshot=snapshot, market=market, news_context=news_ctx, earnings_context=earnings_ctx,
            chain_analysis=chain_analysis, missing_data=missing_data, price_source=price_source, price_as_of=price_as_of,
        )

    contract = scored.contract
    premium = (contract.bid + contract.ask) / 2 if contract.bid > 0 and contract.ask > 0 else contract.last_price
    plan = risk_module.build_trade_plan_risk(entry=round(premium, 2), account_balance=account_balance)

    if not plan.meets_min_risk_reward:
        reasoning.append(f"Note: risk/reward of {plan.risk_reward_ratio}:1 is below the 2:1 minimum guideline")

    if contract.implied_vol > 0.75 or scored.dte <= 7 or "earnings_event_risk" in tags:
        risk_rating = "High"
    elif contract.implied_vol > 0.45 or scored.dte <= 21:
        risk_rating = "Medium"
    else:
        risk_rating = "Low"

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
    }

    return TradeDecision(
        ticker=symbol, price=current_price, recommendation=f"BUY {side.upper()}", confidence=confidence,
        reasoning=reasoning, contract=contract_dict, entry=plan.entry, take_profit_1=plan.take_profit_1,
        take_profit_2=plan.take_profit_2, stop_loss=plan.stop_loss, risk_reward_ratio=plan.risk_reward_ratio,
        dollar_risk_per_contract=plan.dollar_risk_per_contract, max_risk_dollars=plan.max_risk_dollars,
        position_size_contracts=plan.position_size_contracts, risk_rating=risk_rating, tags=tags,
        account_balance=account_balance, snapshot=snapshot, market=market, news_context=news_ctx,
        earnings_context=earnings_ctx, chain_analysis=chain_analysis, missing_data=missing_data,
        price_source=price_source, price_as_of=price_as_of,
    )
