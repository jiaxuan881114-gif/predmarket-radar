"""Offline tests: run the analysis layer on bundled fixtures (no network, no LLM)."""
from __future__ import annotations

import json
from pathlib import Path

from predmarket.analysis import (
    detect_anomalies,
    find_cross_venue_dislocations,
    screen_markets,
)
from predmarket.agent import MockAnalyst
from predmarket.models import MarketSnapshot

SAMPLES = Path(__file__).resolve().parents[1] / "samples"


def _load() -> list[MarketSnapshot]:
    snaps: list[MarketSnapshot] = []
    for f in sorted(SAMPLES.glob("fixture_*.json")):
        for m in json.loads(f.read_text())["markets"]:
            snaps.append(MarketSnapshot.model_validate(m))
    return snaps


def test_screening_ranks_high_volume_first():
    markets = _load()
    top = screen_markets(markets, top_n=3)
    assert top, "expected screened markets"
    # Highest 24h volume should be near the top
    assert top[0].score >= 80


def test_cross_venue_finds_fed_dislocation():
    markets = _load()
    pairs = find_cross_venue_dislocations(markets)
    assert pairs, "expected at least one cross-venue pair"
    p = pairs[0]
    assert p.dislocation_pp >= 8
    assert "fed" in p.polymarket.question.lower() or "fed" in p.kalshi.question.lower()


def test_wide_spread_flagged():
    markets = _load()
    anomalies = detect_anomalies(markets)
    types = {a.type for a in anomalies}
    assert "wide_spread" in types


def test_mock_agent_emits_structured_judgement():
    markets = _load()
    screened = screen_markets(markets, top_n=2)
    judgements = MockAnalyst().judge([s.market for s in screened], moves=[], anomalies=[])
    assert len(judgements) == 2
    for j in judgements:
        assert j.direction in ("YES", "NO", "NEUTRAL")
        assert 1 <= j.conviction <= 5


def test_direction_enum_rejects_invalid_value():
    from pydantic import ValidationError
    from predmarket.models import AgentJudgement
    try:
        AgentJudgement(
            market_id="x", venue="polymarket", question="q", thesis="t",
            direction="MAYBE", conviction=3, key_factors=[], risks=[],
            suggested_action="s", confidence_in_market=0.5,
        )
    except ValidationError:
        return
    raise AssertionError("invalid direction=MAYBE was accepted")


def test_polymarket_bid_ask_mapped_to_unified_model():
    from predmarket.clients.polymarket import PolymarketClient
    snap = PolymarketClient()._normalize({
        "question": "Will X happen?",
        "outcomePrices": "[0.58, 0.42]",
        "outcomes": "[Yes, No]",
        "bestBid": "0.57",
        "bestAsk": "0.59",
        "volume": "1000", "volume24hr": "500", "liquidity": "100",
    })
    assert snap.yes_bid == 0.57
    assert snap.yes_ask == 0.59
    assert snap.spread == 0.02


def test_cross_venue_does_not_pair_across_years():
    from predmarket.analysis.cross_venue import _years_compatible
    assert _years_compatible("Will Fed cut in Dec 2026?", "Fed cut December 2026?") is True
    assert _years_compatible("Will Fed cut in Dec 2026?", "Fed cut December 2027?") is False


if __name__ == "__main__":
    test_screening_ranks_high_volume_first()
    test_cross_venue_finds_fed_dislocation()
    test_wide_spread_flagged()
    test_mock_agent_emits_structured_judgement()
    test_direction_enum_rejects_invalid_value()
    test_polymarket_bid_ask_mapped_to_unified_model()
    test_cross_venue_does_not_pair_across_years()
    print("all offline tests passed")
