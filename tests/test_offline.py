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


if __name__ == "__main__":
    test_screening_ranks_high_volume_first()
    test_cross_venue_finds_fed_dislocation()
    test_wide_spread_flagged()
    test_mock_agent_emits_structured_judgement()
    print("all offline tests passed")
