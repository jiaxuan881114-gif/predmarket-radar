"""Track probability changes between consecutive snapshots.

Given a `previous` snapshot frame and a `current` frame for the same market universe,
compute per-market deltas and flag moves that exceed a threshold (in probability
points). This is the "what just moved" feed the agent reads.
"""
from __future__ import annotations

from ..models import MarketSnapshot, ProbabilityMove


def _index(markets: list[MarketSnapshot]) -> dict[str, MarketSnapshot]:
    return {f"{m.venue.value}:{m.market_id}": m for m in markets}


def detect_moves(
    previous: list[MarketSnapshot],
    current: list[MarketSnapshot],
    min_delta_pp: float = 5.0,
) -> list[ProbabilityMove]:
    """Return markets whose YES probability moved by >= min_delta_pp (percent points)."""
    prev_idx = _index(previous)
    moves: list[ProbabilityMove] = []
    for cur in current:
        key = f"{cur.venue.value}:{cur.market_id}"
        prev = prev_idx.get(key)
        if prev is None:
            continue
        delta = cur.yes_prob - prev.yes_prob
        if abs(delta) * 100 >= min_delta_pp:
            moves.append(
                ProbabilityMove(
                    market_id=cur.market_id,
                    venue=cur.venue,
                    question=cur.question,
                    prev_prob=prev.yes_prob,
                    new_prob=cur.yes_prob,
                    delta=round(delta, 4),
                    prev_fetched_at=prev.fetched_at,
                    new_fetched_at=cur.fetched_at,
                )
            )
    moves.sort(key=lambda m: abs(m.delta), reverse=True)
    return moves
