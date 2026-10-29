"""The judgement layer.

`build_analyst()` returns a real LLM analyst when OPENAI_API_KEY is set (any
OpenAI-compatible endpoint works via OPENAI_BASE_URL / OPENAI_MODEL), otherwise a
deterministic `MockAnalyst` so the whole pipeline stays runnable offline and the
sample outputs in this repo can be regenerated without keys.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

import requests

from ..models import AgentJudgement, AnomalySignal, MarketSnapshot, ProbabilityMove
from .prompts import JUDGEMENT_SCHEMA_HINT, SYSTEM_PROMPT, build_user_prompt

log = logging.getLogger("predmarket.agent")


def _build_brief(
    m: MarketSnapshot,
    moves: list[ProbabilityMove],
    anomalies: list[AnomalySignal],
) -> dict[str, Any]:
    rel_moves = [mv.model_dump(mode="json") for mv in moves if mv.market_id == m.market_id]
    rel_anom = [a.model_dump(mode="json") for a in anomalies if a.market_id == m.market_id]
    return {
        "market_id": m.market_id,
        "venue": m.venue.value,
        "question": m.question,
        "yes_prob": m.yes_prob,
        "yes_bid": m.yes_bid,
        "yes_ask": m.yes_ask,
        "spread": m.spread,
        "volume": m.volume,
        "volume_24h": m.volume_24h,
        "liquidity": m.liquidity,
        "end_date": m.end_date.isoformat() if m.end_date else None,
        "recent_moves": rel_moves,
        "anomalies": rel_anom,
    }


class MarketAnalyst:
    """Calls an OpenAI-compatible chat model and parses structured JSON output."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.base_url = (base_url or os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
        self.model = model or os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY not set; use MockAnalyst for offline runs.")

    def judge_one(self, brief: dict[str, Any]) -> AgentJudgement:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT + "\n\n" + JUDGEMENT_SCHEMA_HINT},
                {"role": "user", "content": build_user_prompt(brief)},
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }
        resp = requests.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=60,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        data = json.loads(content)
        return AgentJudgement.model_validate(data)

    def judge(
        self,
        markets: list[MarketSnapshot],
        moves: list[ProbabilityMove],
        anomalies: list[AnomalySignal],
        limit: int = 5,
    ) -> list[AgentJudgement]:
        out: list[AgentJudgement] = []
        for m in markets[:limit]:
            brief = _build_brief(m, moves, anomalies)
            try:
                out.append(self.judge_one(brief))
            except Exception as exc:  # noqa: BLE001
                log.warning("LLM judgement failed for %s: %s", m.market_id, exc)
        return out


class MockAnalyst:
    """Deterministic offline analyst — turns the feed into a structured judgement
    using simple rules. Used for the bundled samples and CI; mimics the schema."""

    def judge(
        self,
        markets: list[MarketSnapshot],
        moves: list[ProbabilityMove],
        anomalies: list[AnomalySignal],
        limit: int = 5,
    ) -> list[AgentJudgement]:
        out: list[AgentJudgement] = []
        for m in markets[:limit]:
            brief = _build_brief(m, moves, anomalies)
            spread = m.spread or 0.0
            # Direction: if there's a large recent move in the last frame, follow it cautiously.
            move_delta = (brief["recent_moves"][0]["delta"] if brief["recent_moves"] else 0.0)
            if spread > 0.04:
                direction, conviction, action = "NEUTRAL", 1, "avoid — spread too wide to trade"
                thesis = (
                    f"Market asks '{m.question}'. It is priced at {m.yes_prob:.0%} YES but the "
                    f"{spread*100:.1f}pp bid/ask spread means the quote is noisy and not a reliable edge."
                )
            elif abs(move_delta) >= 0.05:
                direction = "YES" if move_delta > 0 else "NO"
                conviction = 3
                action = "wait for confirmation before sizing up"
                thesis = (
                    f"'{m.question}' has moved {move_delta*100:+.0f}pp recently to {m.yes_prob:.0%} YES. "
                    f"The move looks like fresh information being priced in; direction follows the tape."
                )
            elif 0.35 <= m.yes_prob <= 0.65:
                direction, conviction, action = "NEUTRAL", 2, "monitor — two-sided, fairly priced"
                thesis = (
                    f"'{m.question}' sits near {m.yes_prob:.0%} YES with meaningful two-sided activity "
                    f"($ {m.volume_24h:,.0f} 24h). No obvious mispricing from the feed alone."
                )
            else:
                direction = "NO" if m.yes_prob > 0.7 else "YES"
                conviction = 2
                action = "small contrarian position only if supported by outside evidence"
                thesis = (
                    f"'{m.question}' is heavily skewed at {m.yes_prob:.0%} YES. The market is expressing "
                    f"high confidence; a contrarian read needs a concrete catalyst, not just the price."
                )

            factors = [
                f"current YES probability {m.yes_prob:.0%}",
                f"24h volume ${m.volume_24h:,.0f}",
            ]
            if brief["recent_moves"]:
                factors.append(f"recent move {move_delta*100:+.0f}pp")
            risks = ["thin book / wide spread", "late-breaking news not yet in price"]
            if brief["anomalies"]:
                risks.append(f"{len(brief['anomalies'])} anomaly flag(s) on this market")

            out.append(AgentJudgement(
                market_id=m.market_id,
                venue=m.venue,
                question=m.question,
                thesis=thesis,
                direction=direction,
                conviction=conviction,
                key_factors=factors,
                risks=risks,
                suggested_action=action,
                confidence_in_market=round(max(0.1, 1 - spread * 10), 2),
                reasoning_trace="mock-rule-based judgement (offline demo)",
            ))
        return out


def build_analyst() -> MarketAnalyst | MockAnalyst:
    if os.environ.get("OPENAI_API_KEY"):
        try:
            return MarketAnalyst()
        except Exception as exc:  # noqa: BLE001
            log.warning("Falling back to MockAnalyst: %s", exc)
    return MockAnalyst()
