"""Screen a raw market list down to the ones worth paying attention to.

The score blends attention (24h volume), staying power (lifetime volume), depth
(liquidity / open interest) and information content (avoid 99/1 trivial markets).
All components are bounded 0..1 and weighted; final score is 0..100.
"""
from __future__ import annotations

import math

from ..models import MarketSnapshot, ScreenedMarket

# Reference scales (USD). A market at this scale scores ~1.0 on that component.
_REF_VOL24H = 500_000.0
_REF_VOLUME = 5_000_000.0
_REF_LIQUIDITY = 200_000.0

_W_VOL24H = 0.40
_W_VOLUME = 0.20
_W_LIQUIDITY = 0.20
_W_INFORMATION = 0.15
_W_OPEN_INTEREST = 0.05


def _log_scale(value: float, ref: float) -> float:
    if value <= 0:
        return 0.0
    return min(1.0, math.log10(1 + value) / math.log10(1 + ref))


def _information_content(p: float) -> float:
    """Markets near 0 or 1 have little ex-ante uncertainty; 0.5 is most informative."""
    return 1.0 - abs(2 * p - 1)


def score_market(m: MarketSnapshot) -> ScreenedMarket:
    c_vol24h = _log_scale(m.volume_24h, _REF_VOL24H)
    c_volume = _log_scale(m.volume, _REF_VOLUME)
    c_liq = _log_scale(max(m.liquidity, m.open_interest), _REF_LIQUIDITY)
    c_info = _information_content(m.yes_prob)
    c_oi = _log_scale(m.open_interest, _REF_LIQUIDITY)

    score = 100 * (
        _W_VOL24H * c_vol24h
        + _W_VOLUME * c_volume
        + _W_LIQUIDITY * c_liq
        + _W_INFORMATION * c_info
        + _W_OPEN_INTEREST * c_oi
    )

    reasons: list[str] = []
    if c_vol24h >= 0.6:
        reasons.append(f"high 24h volume ({m.volume_24h:,.0f} {m.volume_unit})")
    if m.liquidity >= _REF_LIQUIDITY * 0.5:
        reasons.append(f"deep liquidity (${m.liquidity:,.0f})")
    if c_info >= 0.7:
        reasons.append(f"open/uncertain outcome ({m.yes_prob:.0%})")
    if not reasons:
        reasons.append("moderate activity")

    return ScreenedMarket(
        market=m,
        score=round(score, 1),
        score_breakdown={
            "volume_24h": round(c_vol24h, 3),
            "lifetime_volume": round(c_volume, 3),
            "liquidity": round(c_liq, 3),
            "information": round(c_info, 3),
            "open_interest": round(c_oi, 3),
        },
        reasons=reasons,
    )


def screen_markets(markets: list[MarketSnapshot], top_n: int = 25, min_score: float = 10.0) -> list[ScreenedMarket]:
    scored = [score_market(m) for m in markets if m.active and not m.closed]
    scored = [s for s in scored if s.score >= min_score]
    scored.sort(key=lambda s: s.score, reverse=True)
    return scored[:top_n]
