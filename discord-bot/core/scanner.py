"""Automatic 5-minute watchlist scanner: only surfaces trades that clear
the confidence, liquidity, spread, and risk/reward bar for an auto-post.
"""

from dataclasses import dataclass

from core import ai_engine, database, risk as risk_module

AUTO_POST_CONFIDENCE_THRESHOLD = 85.0
MIN_LIQUIDITY_SCORE = 60.0
MAX_SPREAD_PCT = 0.15


@dataclass
class ScanResult:
    decision: ai_engine.TradeDecision
    qualifies: bool
    disqualify_reasons: list[str]


def evaluate_for_auto_post(decision: ai_engine.TradeDecision) -> ScanResult:
    reasons = []

    if decision.recommendation == "NO TRADE":
        reasons.append("No actionable trade")
    if decision.confidence < AUTO_POST_CONFIDENCE_THRESHOLD:
        reasons.append(f"Confidence {decision.confidence}% below {AUTO_POST_CONFIDENCE_THRESHOLD}% bar")
    if decision.contract:
        if decision.contract["liquidity_score"] < MIN_LIQUIDITY_SCORE:
            reasons.append(f"Liquidity score {decision.contract['liquidity_score']} too low")
    if decision.risk_reward_ratio is not None and decision.risk_reward_ratio < risk_module.MIN_RISK_REWARD_RATIO:
        reasons.append(f"Risk/reward {decision.risk_reward_ratio}:1 below {risk_module.MIN_RISK_REWARD_RATIO}:1 minimum")

    return ScanResult(decision=decision, qualifies=not reasons, disqualify_reasons=reasons)
