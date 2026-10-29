"""Unified data models.

Both exchanges speak different dialects:

* **Polymarket** (Gamma + CLOB): prices are 0..1 decimals, volume in USDC, markets
  hang under events, YES/NO are two separate ERC-1155 tokens.
* **Kalshi**: prices are integer cents (1..99) == implied probability percent, volume
  in contracts, markets hang under events/series.

We collapse everything into :class:`MarketSnapshot` so the analysis layer and the
agent layer never have to care which venue a market came from.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class Venue(str, Enum):
    POLYMARKET = "polymarket"
    KALSHI = "kalshi"


class Direction(str, Enum):
    YES = "YES"
    NO = "NO"
    NEUTRAL = "NEUTRAL"


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


def _now() -> datetime:
    return datetime.now(timezone.utc)


class MarketSnapshot(BaseModel):
    """One normalised, point-in-time view of a binary prediction market."""

    venue: Venue
    # Identifiers
    market_id: str = Field(description="Native market id: Polymarket condition_id or Kalshi ticker")
    event_id: Optional[str] = Field(default=None, description="Grouping id: Polymarket event id / Kalshi event_ticker")
    question: str = Field(description="The binary question, e.g. 'Will X win?'")
    url: Optional[str] = None

    # Core pricing (all probabilities in 0..1)
    yes_prob: float = Field(ge=0, le=1, description="YES probability estimate; source-specific quote or last trade")
    yes_bid: Optional[float] = Field(default=None, ge=0, le=1)
    yes_ask: Optional[float] = Field(default=None, ge=0, le=1)
    last_price: Optional[float] = Field(default=None, ge=0, le=1)

    # Liquidity / activity (USD where the venue reports USD; contracts otherwise)
    volume_unit: str = Field(default="USD", description="USD/USDC turnover or contracts")
    volume: float = Field(default=0.0, description="Lifetime volume in volume_unit")
    volume_24h: float = Field(default=0.0, description="Last-24h volume in volume_unit")
    liquidity: float = Field(default=0.0, description="Order-book liquidity / depth in USD")
    open_interest: float = Field(default=0.0, description="Open interest in venue units; Kalshi contracts")

    # Lifecycle
    active: bool = True
    closed: bool = False
    end_date: Optional[datetime] = None

    fetched_at: datetime = Field(default_factory=_now)

    # Original payload, kept for debugging / rich agent context
    raw: dict[str, Any] = Field(default_factory=dict, repr=False)

    @property
    def spread(self) -> Optional[float]:
        """Bid-ask spread on the YES side, in probability points."""
        if self.yes_bid is not None and self.yes_ask is not None:
            return round(self.yes_ask - self.yes_bid, 4)
        return None

    @property
    def no_prob(self) -> float:
        return round(1 - self.yes_prob, 4)


class ScreenedMarket(BaseModel):
    """A market that passed the screener, with its composite score."""

    market: MarketSnapshot
    score: float = Field(description="Composite attention/quality score 0..100")
    score_breakdown: dict[str, float] = Field(default_factory=dict)
    reasons: list[str] = Field(default_factory=list)


class ProbabilityMove(BaseModel):
    """A probability change between two snapshots of the same market."""

    market_id: str
    venue: Venue
    question: str
    prev_prob: float
    new_prob: float
    delta: float = Field(description="new - prev, in probability points (e.g. 0.12 == +12pp)")
    prev_fetched_at: datetime
    new_fetched_at: datetime


class AnomalySignal(BaseModel):
    type: str = Field(description="e.g. price_jump, volume_spike, wide_spread, cross_venue_dislocation")
    severity: Severity = Field(default=Severity.INFO, description="info | warning | critical")
    market_id: str
    venue: Venue
    detail: str
    metric: Optional[float] = None
    reference: Optional[str] = None


class AgentJudgement(BaseModel):
    """Structured LLM output for one market. Emitted as JSON."""

    market_id: str
    venue: Venue
    question: str
    thesis: str = Field(description="2-3 sentence plain-English thesis on what the market is pricing")
    direction: Direction = Field(description="YES | NO | NEUTRAL; anything else is rejected")
    conviction: int = Field(ge=1, le=5, description="1=very weak .. 5=very strong")
    key_factors: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    suggested_action: str = Field(description="e.g. 'monitor', 'small YES position', 'avoid', 'wait for confirmation'")
    confidence_in_market: float = Field(ge=0, le=1, description="Our confidence that the market price is efficient")
    reasoning_trace: Optional[str] = None
