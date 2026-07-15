"""Position sizing and risk/reward math -- pure calculation, no data fetch."""

from dataclasses import dataclass

ACCOUNT_BALANCE_DEFAULT = 10_000.0
MAX_ACCOUNT_RISK_PCT = 0.02  # Risk at most 2% of account per trade.
MIN_RISK_REWARD_RATIO = 2.0


@dataclass
class TradePlanRisk:
    entry: float
    take_profit_1: float
    take_profit_2: float
    stop_loss: float
    risk_reward_ratio: float
    dollar_risk_per_contract: float
    max_risk_dollars: float
    position_size_contracts: int
    meets_min_risk_reward: bool


def build_trade_plan_risk(*, entry: float, account_balance: float = ACCOUNT_BALANCE_DEFAULT) -> TradePlanRisk:
    # Stop at -50% (typical max loss guideline for a long option swing trade),
    # TP1/TP2 sized to clear the 2:1 minimum risk/reward with room to spare.
    take_profit_1 = round(entry * 2.20, 2)
    take_profit_2 = round(entry * 3.50, 2)
    stop_loss = round(entry * 0.50, 2)

    reward = take_profit_1 - entry
    risk = entry - stop_loss
    risk_reward_ratio = round(reward / risk, 2) if risk > 0 else 0.0

    dollar_risk_per_contract = round(risk * 100, 2)  # 1 contract = 100 shares
    max_risk_dollars = round(account_balance * MAX_ACCOUNT_RISK_PCT, 2)
    position_size_contracts = (
        max(1, int(max_risk_dollars // dollar_risk_per_contract)) if dollar_risk_per_contract > 0 else 1
    )

    return TradePlanRisk(
        entry=entry,
        take_profit_1=take_profit_1,
        take_profit_2=take_profit_2,
        stop_loss=stop_loss,
        risk_reward_ratio=risk_reward_ratio,
        dollar_risk_per_contract=dollar_risk_per_contract,
        max_risk_dollars=max_risk_dollars,
        position_size_contracts=position_size_contracts,
        meets_min_risk_reward=risk_reward_ratio >= MIN_RISK_REWARD_RATIO,
    )
