"""Collection orchestration: fetch -> normalise -> screen -> detect -> assemble report.

Each venue is fetched independently and wrapped in try/except so a network block (e.g.
Polymarket unreachable from a restricted region) degrades gracefully instead of
crashing the whole radar.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from ..analysis import detect_anomalies, detect_moves, find_cross_venue_dislocations, screen_markets
from ..clients import KalshiClient, PolymarketClient
from ..models import MarketSnapshot
from .storage import SnapshotStore

log = logging.getLogger("predmarket.collector")


@dataclass
class RadarReport:
    generated_at: str
    totals: dict = field(default_factory=dict)
    top_markets: list = field(default_factory=list)
    probability_moves: list = field(default_factory=list)
    anomalies: list = field(default_factory=list)
    cross_venue_pairs: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    data_warnings: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


class Collector:
    def __init__(self, store: SnapshotStore | None = None):
        self.poly = PolymarketClient()
        self.kalshi = KalshiClient()
        self.store = store or SnapshotStore()

    def collect(self, limit_per_venue: int = 100, top_n: int = 25,
                kalshi_series: list[str] | None = None) -> RadarReport:
        prev = self.store.latest()
        errors: list[str] = []
        markets: list[MarketSnapshot] = []

        try:
            markets += self.poly.list_active_markets(limit=limit_per_venue)
        except Exception as exc:  # noqa: BLE001 - graceful degradation
            log.warning("Polymarket fetch failed: %s", exc)
            errors.append(f"polymarket: {exc}")

        try:
            if kalshi_series:
                # Apply the per-venue cap across explicitly selected series.
                found = {}
                for series in dict.fromkeys(kalshi_series):
                    if len(found) >= limit_per_venue:
                        break
                    try:
                        for m in self.kalshi.list_active_markets(
                            limit=limit_per_venue - len(found), series_ticker=series,
                        ):
                            found[m.market_id] = m
                    except Exception as exc:
                        errors.append(f"kalshi:{series}: {type(exc).__name__}")
                markets += list(found.values())
            else:
                markets += self.kalshi.list_active_markets(limit=limit_per_venue)
        except Exception as exc:  # noqa: BLE001
            log.warning("Kalshi fetch failed: %s", exc)
            errors.append(f"kalshi: {exc}")

        if markets:
            self.store.write(markets)

        self.current_markets = markets
        screened = screen_markets(markets, top_n=top_n)
        moves = detect_moves(prev, markets) if prev else []
        anomalies = detect_anomalies(markets)
        pairs = find_cross_venue_dislocations(markets)

        return RadarReport(
            generated_at=datetime.now(timezone.utc).isoformat(),
            totals={
                "markets_fetched": len(markets),
                "polymarket": sum(1 for m in markets if m.venue.value == "polymarket"),
                "kalshi": sum(1 for m in markets if m.venue.value == "kalshi"),
            },
            top_markets=[
                {
                    "score": s.score,
                    "venue": s.market.venue.value,
                    "question": s.market.question,
                    "yes_prob": s.market.yes_prob,
                    "volume_24h": s.market.volume_24h,
                    "reasons": s.reasons,
                    "url": s.market.url,
                }
                for s in screened
            ],
            probability_moves=[m.model_dump(mode="json") for m in moves],
            anomalies=[a.model_dump(mode="json") for a in anomalies],
            cross_venue_pairs=[p.as_dict() for p in pairs],
            errors=errors,
            data_warnings=[
                {"venue": m.venue.value, "market_id": m.market_id,
                 "stage": "series_evidence", "error_type": m.raw["series_evidence_error"]}
                for m in markets if m.raw.get("series_evidence_error")
            ],
        )
