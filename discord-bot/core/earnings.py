"""Earnings calendar lookups."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from apis import router


@dataclass
class EarningsContext:
    earnings_date: Optional[str]
    days_to_earnings: Optional[int]
    eps_estimate: Optional[float]
    revenue_estimate: Optional[float]
    source: Optional[str]


def get_earnings_context(symbol: str) -> EarningsContext:
    result = router.get_earnings_info(symbol)
    if not result.available:
        return EarningsContext(
            earnings_date=None, days_to_earnings=None, eps_estimate=None, revenue_estimate=None, source=None
        )

    info = result.value
    days_to_earnings = None
    if info.earnings_date is not None:
        days_to_earnings = (info.earnings_date - datetime.now(timezone.utc).date()).days

    return EarningsContext(
        earnings_date=info.earnings_date.isoformat() if info.earnings_date else None,
        days_to_earnings=days_to_earnings,
        eps_estimate=info.eps_estimate,
        revenue_estimate=info.revenue_estimate,
        source=result.source,
    )
