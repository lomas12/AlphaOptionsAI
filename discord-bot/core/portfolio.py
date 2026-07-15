"""Portfolio view: assembles live P/L for every open recommendation by
re-pricing its specific contract against the current option chain.
"""

from dataclasses import dataclass
from typing import Optional

from apis import router
from core import database


@dataclass
class PortfolioPosition:
    rec_id: int
    ticker: str
    option_type: str
    strike: float
    expiration: str
    entry_premium: float
    current_premium: Optional[float]
    unrealized_pct: Optional[float]
    confidence: float
    status: str


def get_open_portfolio() -> list[PortfolioPosition]:
    positions = []
    for rec in database.get_open_recommendations():
        current_premium = None
        chain_result = router.get_option_chain(rec["ticker"], rec["expiration"])
        if chain_result.available:
            chain = chain_result.value
            contracts = chain.calls if rec["option_type"] == "CALL" else chain.puts
            match = next((c for c in contracts if abs(c.strike - rec["strike"]) < 0.01), None)
            if match:
                current_premium = (match.bid + match.ask) / 2 if match.bid > 0 and match.ask > 0 else match.last_price

        unrealized_pct = None
        if current_premium is not None and rec["entry_premium"]:
            unrealized_pct = round((current_premium - rec["entry_premium"]) / rec["entry_premium"] * 100, 2)

        positions.append(
            PortfolioPosition(
                rec_id=rec["id"], ticker=rec["ticker"], option_type=rec["option_type"],
                strike=rec["strike"], expiration=rec["expiration"], entry_premium=rec["entry_premium"],
                current_premium=round(current_premium, 2) if current_premium is not None else None,
                unrealized_pct=unrealized_pct, confidence=rec["confidence"], status=rec["status"],
            )
        )
    return positions
