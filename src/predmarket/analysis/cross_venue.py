"""Cross-venue comparison: match the same real-world question on Polymarket and Kalshi.

When two markets price the *same* event materially differently, that is either an
arbitrage opportunity, a stale quote on one venue, or new information not yet priced on
the other. We fuzzy-match normalised titles and report dislocations.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..models import MarketSnapshot, Venue

_STOPWORDS = {
    "will", "the", "a", "an", "be", "by", "to", "of", "in", "on", "for", "at",
    "vs", "or", "and", "with", "before", "after", "this", "next", "year",
    "market", "prediction", "odds", "2024", "2025", "2026", "2027", "2028",
    "meeting", "basis", "points", "point", "bp", "pp",
}

# Light synonym / normalisation map so "the Fed cut" and "Federal Reserve cut" match.
_SYNONYMS = {
    "fed": "fed", "federal": "fed", "reserve": "fed", "fomc": "fed",
    "rates": "rate", "rate": "rate",
    "cuts": "cut", "cut": "cut",
    "funds": "fund",
    "president": "potus", "potus": "potus", "election": "election",
    "bitcoin": "btc", "btc": "btc",
}

# |poly_price - kalshi_price| above this (pp) is a dislocation worth surfacing.
_DISLOCATION_PP = 8.0
_MIN_JACCARD = 0.45


def _normalize(title: str) -> set[str]:
    title = title.lower()
    title = re.sub(r"[^a-z0-9\s]", " ", title)
    tokens: set[str] = set()
    for tok in title.split():
        if tok in _STOPWORDS or len(tok) <= 2:
            continue
        # Crude singularisation: rates -> rate, points -> point
        stem = tok[:-1] if tok.endswith("s") and len(tok) > 4 else tok
        tok = _SYNONYMS.get(tok, _SYNONYMS.get(stem, stem))
        if tok and tok not in _STOPWORDS:
            tokens.add(tok)
    return tokens


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


@dataclass
class CrossVenuePair:
    polymarket: MarketSnapshot
    kalshi: MarketSnapshot
    similarity: float
    dislocation_pp: float

    def as_dict(self) -> dict:
        return {
            "similarity": round(self.similarity, 2),
            "dislocation_pp": round(self.dislocation_pp, 1),
            "polymarket": {
                "question": self.polymarket.question,
                "yes_prob": self.polymarket.yes_prob,
                "market_id": self.polymarket.market_id,
            },
            "kalshi": {
                "question": self.kalshi.question,
                "yes_prob": self.kalshi.yes_prob,
                "market_id": self.kalshi.market_id,
            },
        }


def find_cross_venue_dislocations(
    markets: list[MarketSnapshot],
    min_jaccard: float = _MIN_JACCARD,
    dislocation_pp: float = _DISLOCATION_PP,
) -> list[CrossVenuePair]:
    poly = [m for m in markets if m.venue == Venue.POLYMARKET and m.active]
    kalshi = [m for m in markets if m.venue == Venue.KALSHI and m.active]
    kal_norms = [(k, _normalize(k.question)) for k in kalshi]

    pairs: list[CrossVenuePair] = []
    for p in poly:
        pn = _normalize(p.question)
        best_k = None
        best_sim = 0.0
        for k, kn in kal_norms:
            sim = _jaccard(pn, kn)
            if sim > best_sim:
                best_sim, best_k = sim, k
        if best_k is None or best_sim < min_jaccard:
            continue
        dislocation = abs(p.yes_prob - best_k.yes_prob) * 100
        if dislocation >= dislocation_pp:
            pairs.append(CrossVenuePair(
                polymarket=p,
                kalshi=best_k,
                similarity=best_sim,
                dislocation_pp=dislocation,
            ))
    pairs.sort(key=lambda x: x.dislocation_pp, reverse=True)
    return pairs
