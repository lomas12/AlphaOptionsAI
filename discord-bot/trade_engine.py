"""AlphaOptionsAI V2 decision engine.

Pulls live price history, options chain, market context (SPY/QQQ/VIX),
earnings/news/analyst context, scores every call and put contract across the
nearest 3 expirations, and picks exactly ONE trade (or NO TRADE) using
self-learning strategy weights stored in SQLite.
"""

import asyncio
import math
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

import pandas as pd
import yfinance as yf

import database
from context import MarketContext, TickerContext, get_market_context, get_ticker_context
from indicators import TechnicalSnapshot, compute_snapshot
from market_data import TickerNotFoundError, _get_price_fields, clean_ticker

RISK_FREE_RATE = 0.05
NUM_EXPIRATIONS = 3
CONFIDENCE_TRADE_THRESHOLD = 70.0
ACCOUNT_BALANCE_DEFAULT = 10_000.0
MAX_ACCOUNT_RISK_PCT = 0.02  # Risk at most 2% of account per trade.


class NoOptionsAvailableError(Exception):
    pass


@dataclass
class ContractCandidate:
    option_type: str
    strike: float
    expiration: str
    dte: int
    premium: float
    open_interest: int
    volume: int
    implied_vol: float
    delta: float
    gamma: float
    theta: float
    liquidity_score: float
    conviction_score: float
    confidence: float
    tags: list[str]


@dataclass
class TradeDecision:
    ticker: str
    recommendation: str  # "BUY CALL" | "BUY PUT" | "NO TRADE"
    confidence: float
    reasoning: list[str]
    contract: Optional[ContractCandidate]
    entry: Optional[float]
    take_profit_1: Optional[float]
    take_profit_2: Optional[float]
    stop_loss: Optional[float]
    max_risk_dollars: Optional[float]
    prob_tp1: Optional[float]
    prob_tp2: Optional[float]
    risk_rating: Optional[str]
    position_size_contracts: Optional[int]
    account_balance: float
    market: MarketContext
    ticker_context: TickerContext
    snapshot: TechnicalSnapshot


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    return math.exp(-x * x / 2.0) / math.sqrt(2.0 * math.pi)


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(value, high))


def _soft_peak_score(value: float, peak: float, width: float) -> float:
    return _clamp(1.0 - abs(value - peak) / width)


def _black_scholes(
    *, spot: float, strike: float, t_years: float, sigma: float, option_type: str
) -> tuple[float, float, float, float]:
    """Returns (delta, gamma, theta_per_day, d2)."""
    sqrt_t = math.sqrt(t_years)
    d1 = (math.log(spot / strike) + (RISK_FREE_RATE + sigma * sigma / 2) * t_years) / (sigma * sqrt_t)
    d2 = d1 - sigma * sqrt_t
    discount = math.exp(-RISK_FREE_RATE * t_years)

    if option_type == "call":
        delta = _norm_cdf(d1)
        theta = (
            -spot * _norm_pdf(d1) * sigma / (2 * sqrt_t) - RISK_FREE_RATE * strike * discount * _norm_cdf(d2)
        ) / 365
    else:
        delta = _norm_cdf(d1) - 1.0
        theta = (
            -spot * _norm_pdf(d1) * sigma / (2 * sqrt_t) + RISK_FREE_RATE * strike * discount * _norm_cdf(-d2)
        ) / 365

    gamma = _norm_pdf(d1) / (spot * sigma * sqrt_t)
    return delta, gamma, theta, d2


def _liquidity_score(
    *, open_interest: int, volume: int, implied_vol: float, bid: float, ask: float, distance_pct: float, dte: int
) -> float:
    """Same 9-factor liquidity/greeks-adjacent scoring used in V1, kept as the
    'is this contract tradeable' half of the final confidence score."""
    oi_score = _clamp(open_interest / 3000)
    volume_score = _clamp(volume / 1000)
    vol_oi_ratio = (volume / open_interest) if open_interest > 0 else 0.0
    vol_oi_score = _clamp(vol_oi_ratio)
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


def _active_tags(*, side: str, snapshot: TechnicalSnapshot, market: MarketContext, ticker_ctx: TickerContext) -> list[str]:
    """Which strategy tags are 'active' for a bullish (call) or bearish (put)
    thesis, given real technical + context data. Missing data simply yields
    no tag rather than a fabricated one."""
    tags: list[str] = []
    price = snapshot.price

    if side == "call":
        if snapshot.ema20 and snapshot.ema50 and snapshot.ema200 and price > snapshot.ema20 > snapshot.ema50 > snapshot.ema200:
            tags.append("trend_stack_bullish")
        if snapshot.ema50 and price > snapshot.ema50:
            tags.append("above_ema50")
        if snapshot.rsi14 is not None:
            if 40 <= snapshot.rsi14 <= 65:
                tags.append("rsi_bullish")
            if snapshot.rsi14 < 35:
                tags.append("rsi_oversold")
            if snapshot.rsi14 > 75:
                tags.append("rsi_overbought")
        if snapshot.macd_line is not None and snapshot.macd_signal is not None and snapshot.macd_line > snapshot.macd_signal:
            tags.append("macd_bullish")
        if snapshot.volume and snapshot.avg_volume20 and snapshot.volume > snapshot.avg_volume20:
            tags.append("volume_confirmation")
        if snapshot.resistance and (snapshot.resistance - price) / price > 0.03:
            tags.append("room_to_resistance")
        if snapshot.resistance and (snapshot.resistance - price) / price < 0.015:
            tags.append("resistance_overhead")
        if market.spy_trend == "Bullish" or market.qqq_trend == "Bullish":
            tags.append("market_trend_aligned")
        if market.spy_trend == "Bearish" and market.qqq_trend == "Bearish":
            tags.append("market_trend_against")
        if market.vix_classification == "Low":
            tags.append("vix_supportive")
        if market.vix_classification == "Elevated":
            tags.append("vix_elevated")
        if ticker_ctx.news_sentiment == "Positive":
            tags.append("positive_news_sentiment")
        if ticker_ctx.news_sentiment == "Negative":
            tags.append("negative_news_sentiment")
        if ticker_ctx.analyst_action == "Upgrade":
            tags.append("analyst_upgrade")
        if ticker_ctx.analyst_action == "Downgrade":
            tags.append("analyst_downgrade")
    else:  # put
        if snapshot.ema20 and snapshot.ema50 and snapshot.ema200 and price < snapshot.ema20 < snapshot.ema50 < snapshot.ema200:
            tags.append("trend_stack_bearish")
        if snapshot.ema50 and price < snapshot.ema50:
            tags.append("below_ema50")
        if snapshot.rsi14 is not None:
            if 35 <= snapshot.rsi14 <= 60:
                tags.append("rsi_bearish")
            if snapshot.rsi14 > 65:
                tags.append("rsi_overbought")
            if snapshot.rsi14 < 25:
                tags.append("rsi_oversold")
        if snapshot.macd_line is not None and snapshot.macd_signal is not None and snapshot.macd_line < snapshot.macd_signal:
            tags.append("macd_bearish")
        if snapshot.volume and snapshot.avg_volume20 and snapshot.volume > snapshot.avg_volume20:
            tags.append("volume_confirmation")
        if snapshot.support and (price - snapshot.support) / price > 0.03:
            tags.append("room_to_support")
        if snapshot.support and (price - snapshot.support) / price < 0.015:
            tags.append("support_below")
        if market.spy_trend == "Bearish" or market.qqq_trend == "Bearish":
            tags.append("market_trend_aligned")
        if market.spy_trend == "Bullish" and market.qqq_trend == "Bullish":
            tags.append("market_trend_against")
        if market.vix_classification == "Low":
            tags.append("vix_supportive")
        if market.vix_classification == "Elevated":
            tags.append("vix_elevated")
        if ticker_ctx.news_sentiment == "Negative":
            tags.append("negative_news_sentiment")
        if ticker_ctx.news_sentiment == "Positive":
            tags.append("positive_news_sentiment")
        if ticker_ctx.analyst_action == "Downgrade":
            tags.append("analyst_downgrade")
        if ticker_ctx.analyst_action == "Upgrade":
            tags.append("analyst_upgrade")

    if ticker_ctx.days_to_earnings is not None and 0 <= ticker_ctx.days_to_earnings <= 30:
        tags.append("earnings_event_risk")

    return tags


# Tags that would count *against* the thesis if present (their weight is
# subtracted rather than added) -- these can appear in either tag list above
# but represent a headwind, not a tailwind.
_HEADWIND_TAGS = {
    "resistance_overhead",
    "support_below",
    "rsi_overbought",
    "rsi_oversold",
    "market_trend_against",
    "vix_elevated",
    "negative_news_sentiment",
    "analyst_downgrade",
    "earnings_event_risk",
}


def _conviction_score(tags: list[str], weights: dict[str, float]) -> float:
    """Weighted sum of active tags normalized to 0-100. Headwind tags subtract."""
    if not tags:
        return 40.0  # No signal either way -- mild default, not a fabricated edge.

    total = 0.0
    max_possible = 0.0
    for tag in tags:
        weight = weights.get(tag, 1.0)
        max_possible += weight
        total += -weight if tag in _HEADWIND_TAGS else weight

    if max_possible <= 0:
        return 40.0
    normalized = 0.5 + (total / max_possible) / 2  # map [-1, 1] -> [0, 1]
    return round(_clamp(normalized) * 100, 1)


def _process_contract_row(row, *, spot: float, exp_str: str, dte: int, option_type: str) -> Optional[dict]:
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
        delta, gamma, theta, d2 = _black_scholes(
            spot=spot, strike=strike, t_years=t_years, sigma=implied_vol, option_type=option_type
        )
    except (ValueError, ZeroDivisionError):
        return None

    distance_pct = abs(strike - spot) / spot
    liquidity_score = _liquidity_score(
        open_interest=open_interest,
        volume=volume,
        implied_vol=implied_vol,
        bid=bid,
        ask=ask,
        distance_pct=distance_pct,
        dte=dte,
    )

    return dict(
        strike=strike,
        expiration=exp_str,
        dte=dte,
        premium=round(premium, 2),
        open_interest=open_interest,
        volume=volume,
        implied_vol=implied_vol,
        delta=delta,
        gamma=gamma,
        theta=theta,
        liquidity_score=liquidity_score,
    )


def _fetch_best_contracts(symbol: str, spot: float) -> tuple[dict, dict]:
    tk = yf.Ticker(symbol)
    expirations = tk.options
    if not expirations:
        raise NoOptionsAvailableError(f"No options chain is available for {symbol}.")

    today = date.today()
    calls: list[dict] = []
    puts: list[dict] = []

    for exp_str in expirations[:NUM_EXPIRATIONS]:
        exp_date = datetime.strptime(exp_str, "%Y-%m-%d").date()
        dte = max((exp_date - today).days, 1)
        chain = tk.option_chain(exp_str)

        for row in chain.calls.itertuples():
            pick = _process_contract_row(row, spot=spot, exp_str=exp_str, dte=dte, option_type="call")
            if pick:
                calls.append(pick)
        for row in chain.puts.itertuples():
            pick = _process_contract_row(row, spot=spot, exp_str=exp_str, dte=dte, option_type="put")
            if pick:
                puts.append(pick)

    if not calls or not puts:
        raise NoOptionsAvailableError(f"Not enough liquid options data for {symbol}.")

    best_call_raw = max(calls, key=lambda c: c["liquidity_score"])
    best_put_raw = max(puts, key=lambda c: c["liquidity_score"])
    return best_call_raw, best_put_raw


def _build_reasoning(side: str, tags: list[str], ticker_ctx: TickerContext) -> list[str]:
    labels = {
        "trend_stack_bullish": "Bullish trend stack: price above EMA20/50/200",
        "trend_stack_bearish": "Bearish trend stack: price below EMA20/50/200",
        "above_ema50": "Trading above EMA50",
        "below_ema50": "Trading below EMA50",
        "rsi_bullish": "RSI recovering / holding a healthy bullish range",
        "rsi_bearish": "RSI holding a bearish range",
        "rsi_overbought": "RSI overbought -- pullback risk",
        "rsi_oversold": "RSI oversold -- bounce risk",
        "macd_bullish": "MACD bullish crossover",
        "macd_bearish": "MACD bearish crossover",
        "volume_confirmation": "Volume confirming the move",
        "room_to_resistance": "Clear room to resistance overhead",
        "resistance_overhead": "Resistance sitting close overhead",
        "room_to_support": "Clear room down to support",
        "support_below": "Support sitting close below",
        "market_trend_aligned": "Broader market (SPY/QQQ) trend aligned",
        "market_trend_against": "Broader market trend working against this trade",
        "vix_supportive": "VIX calm, supportive of trend continuation",
        "vix_elevated": "VIX elevated -- higher volatility risk",
        "positive_news_sentiment": "Recent news sentiment positive",
        "negative_news_sentiment": "Recent news sentiment negative",
        "analyst_upgrade": "Recent analyst upgrade",
        "analyst_downgrade": "Recent analyst downgrade",
        "earnings_event_risk": "Earnings event inside the option's window",
    }
    reasoning = [labels[t] for t in tags if t in labels]
    if not reasoning:
        reasoning.append("No strong directional signal in current data")
    if ticker_ctx.news_headlines:
        reasoning.append(f"Headline: \"{ticker_ctx.news_headlines[0]}\"")
    return reasoning


async def analyze_ticker(raw_ticker: str, account_balance: float = ACCOUNT_BALANCE_DEFAULT) -> TradeDecision:
    return await asyncio.to_thread(_analyze_ticker_sync, raw_ticker, account_balance)


def _analyze_ticker_sync(raw_ticker: str, account_balance: float) -> TradeDecision:
    symbol = clean_ticker(raw_ticker)
    print(f"[AlphaOptionsAI] Analyzing ticker: {symbol}")

    if not symbol:
        raise TickerNotFoundError(f"❌ Could not find ticker {raw_ticker!r}")

    tk = yf.Ticker(symbol)
    current_price, _ = _get_price_fields(tk)
    if current_price is None:
        raise TickerNotFoundError(f"❌ Could not find ticker {symbol}")

    hist = tk.history(period="1y", interval="1d", auto_adjust=False)
    if hist is None or hist.empty:
        raise TickerNotFoundError(f"❌ Could not find ticker {symbol}")

    snapshot = compute_snapshot(hist, current_price)
    market = get_market_context()
    ticker_ctx = get_ticker_context(symbol)
    weights = database.get_weights()

    call_tags = _active_tags(side="call", snapshot=snapshot, market=market, ticker_ctx=ticker_ctx)
    put_tags = _active_tags(side="put", snapshot=snapshot, market=market, ticker_ctx=ticker_ctx)
    call_conviction = _conviction_score(call_tags, weights)
    put_conviction = _conviction_score(put_tags, weights)

    best_call_raw, best_put_raw = _fetch_best_contracts(symbol, current_price)

    call_confidence = round((best_call_raw["liquidity_score"] + call_conviction) / 2, 1)
    put_confidence = round((best_put_raw["liquidity_score"] + put_conviction) / 2, 1)

    # Earnings inside the option's window is a real, data-backed risk -- shave
    # a bit off confidence on both sides rather than guessing a bigger number.
    if ticker_ctx.days_to_earnings is not None and 0 <= ticker_ctx.days_to_earnings <= 7:
        call_confidence = max(0.0, call_confidence - 8)
        put_confidence = max(0.0, put_confidence - 8)

    if call_confidence >= put_confidence:
        side, raw, tags, confidence = "call", best_call_raw, call_tags, call_confidence
    else:
        side, raw, tags, confidence = "put", best_put_raw, put_tags, put_confidence

    reasoning = _build_reasoning(side, tags, ticker_ctx)

    if confidence < CONFIDENCE_TRADE_THRESHOLD:
        return TradeDecision(
            ticker=symbol,
            recommendation="NO TRADE",
            confidence=confidence,
            reasoning=reasoning + ["Confidence below the 70% action threshold -- waiting for confirmation"],
            contract=None,
            entry=None,
            take_profit_1=None,
            take_profit_2=None,
            stop_loss=None,
            max_risk_dollars=None,
            prob_tp1=None,
            prob_tp2=None,
            risk_rating=None,
            position_size_contracts=None,
            account_balance=account_balance,
            market=market,
            ticker_context=ticker_ctx,
            snapshot=snapshot,
        )

    entry = raw["premium"]
    take_profit_1 = round(entry * 1.30, 2)
    take_profit_2 = round(entry * 1.75, 2)
    stop_loss = round(entry * 0.55, 2)

    contract = ContractCandidate(
        option_type=side.upper(),
        strike=raw["strike"],
        expiration=raw["expiration"],
        dte=raw["dte"],
        premium=entry,
        open_interest=raw["open_interest"],
        volume=raw["volume"],
        implied_vol=raw["implied_vol"],
        delta=raw["delta"],
        gamma=raw["gamma"],
        theta=raw["theta"],
        liquidity_score=raw["liquidity_score"],
        conviction_score=call_conviction if side == "call" else put_conviction,
        confidence=confidence,
        tags=tags,
    )

    # Probability of hitting TP1/TP2 modeled from the contract's own delta as
    # a rough proxy for "probability the underlying keeps moving our way",
    # scaled down as the target gets further from entry.
    directional_strength = abs(contract.delta)
    prob_tp1 = round(_clamp(directional_strength * 1.1) * 100, 1)
    prob_tp2 = round(_clamp(directional_strength * 0.75) * 100, 1)

    if raw["implied_vol"] > 0.75 or raw["dte"] <= 7 or "earnings_event_risk" in tags:
        risk_rating = "High"
    elif raw["implied_vol"] > 0.45 or raw["dte"] <= 21:
        risk_rating = "Medium"
    else:
        risk_rating = "Low"

    max_risk_dollars = round(account_balance * MAX_ACCOUNT_RISK_PCT, 2)
    per_contract_risk = (entry - stop_loss) * 100  # options are quoted per-share, contract = 100 shares
    position_size_contracts = max(1, int(max_risk_dollars // per_contract_risk)) if per_contract_risk > 0 else 1

    return TradeDecision(
        ticker=symbol,
        recommendation=f"BUY {side.upper()}",
        confidence=confidence,
        reasoning=reasoning,
        contract=contract,
        entry=entry,
        take_profit_1=take_profit_1,
        take_profit_2=take_profit_2,
        stop_loss=stop_loss,
        max_risk_dollars=max_risk_dollars,
        prob_tp1=prob_tp1,
        prob_tp2=prob_tp2,
        risk_rating=risk_rating,
        position_size_contracts=position_size_contracts,
        account_balance=account_balance,
        market=market,
        ticker_context=ticker_ctx,
        snapshot=snapshot,
    )
