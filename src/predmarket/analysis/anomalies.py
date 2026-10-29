"""Single-snapshot anomaly / signal detection.

Signals raised per market:
* wide_spread        — bid/ask too wide -> thin book, price is noisy
* low_liquidity      — trivial depth even though the market is quoted
* extreme_longshot   — priced <=5% or >=95% yet moving / traded
* high_velocity      — huge 24h volume relative to lifetime volume (attention spike)
"""
from __future__ import annotations

from ..models import AnomalySignal, MarketSnapshot

_WIDE_SPREAD_PP = 4.0          # YES spread >= 4pp
_MIN_LIQUIDITY = 10_000.0      # below this USD depth -> thin
_LONGSHOT_BOUND = 0.05
_VELOCITY_RATIO = 0.30         # 24h vol >= 30% of lifetime volume


def detect_anomalies(markets: list[MarketSnapshot]) -> list[AnomalySignal]:
    signals: list[AnomalySignal] = []
    for m in markets:
        if not m.active or m.closed:
            continue

        spread = m.spread
        if spread is not None and spread * 100 >= _WIDE_SPREAD_PP:
            signals.append(AnomalySignal(
                type="wide_spread",
                severity="warning",
                market_id=m.market_id,
                venue=m.venue,
                detail=f"YES bid/ask spread is {spread*100:.1f}pp -> thin book / noisy price",
                metric=spread,
            ))

        # Only flag thin depth when the venue actually reported a liquidity number.
        if 0 < m.liquidity < _MIN_LIQUIDITY and m.volume_24h > 5_000:
            signals.append(AnomalySignal(
                type="low_liquidity",
                severity="info",
                market_id=m.market_id,
                venue=m.venue,
                detail=f"$ {m.liquidity:,.0f} depth but {m.volume_24h:,.0f} {m.volume_unit} 24h volume",
                metric=m.liquidity,
            ))

        if (m.yes_prob <= _LONGSHOT_BOUND or m.yes_prob >= 1 - _LONGSHOT_BOUND) and m.volume_24h > 20_000:
            side = "longshot (NO favourite)" if m.yes_prob <= _LONGSHOT_BOUND else "near-certain (YES favourite)"
            signals.append(AnomalySignal(
                type="extreme_longshot",
                severity="info",
                market_id=m.market_id,
                venue=m.venue,
                detail=f"priced {m.yes_prob:.0%} ({side}) with {m.volume_24h:,.0f} {m.volume_unit} 24h volume",
                metric=m.yes_prob,
            ))

        if m.volume > 0 and m.volume_24h / m.volume >= _VELOCITY_RATIO:
            signals.append(AnomalySignal(
                type="high_velocity",
                severity="warning",
                market_id=m.market_id,
                venue=m.venue,
                detail=f"24h volume is {m.volume_24h/m.volume:.0%} of lifetime volume — attention spike",
                metric=round(m.volume_24h / m.volume, 3),
            ))

    return signals
