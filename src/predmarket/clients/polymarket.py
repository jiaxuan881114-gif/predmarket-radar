"""Polymarket data client.

Read-only. Uses the Gamma discovery API for the market catalogue and the CLOB API
for live midpoints / price history. No API key required for reads.

Base URLs:
    Gamma: https://gamma-api.polymarket.com
    CLOB:  https://clob.polymarket.com
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Optional

from ..models import MarketSnapshot, Venue
from .base import BaseHttpClient

log = logging.getLogger("predmarket.polymarket")


def _f(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, "", "null"):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _loads(value: Any) -> Any:
    """Some Gamma fields come back as JSON-encoded strings."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


class PolymarketClient(BaseHttpClient):
    base_url = "https://gamma-api.polymarket.com"
    clob_url = "https://clob.polymarket.com"

    def list_active_markets(
        self,
        limit: int = 100,
        min_volume: float = 0.0,
        order: str = "volume24hr",
    ) -> list[MarketSnapshot]:
        """Fetch active, open markets sorted by 24h volume (descending)."""
        out: list[MarketSnapshot] = []
        seen: set[str] = set()
        offset = 0
        # Bound raw rows visited even when some markets fail the activity filter.
        while offset < limit:
            page_size = min(limit - offset, 100)
            data = self._get("/markets", params={
                "limit": page_size, "offset": offset, "active": "true",
                "closed": "false", "order": order, "ascending": "false",
            })
            items = data.get("markets", []) if isinstance(data, dict) else data
            if not items:
                break
            added = 0
            for m in items:
                snap = self._normalize(m)
                if snap is None or snap.market_id in seen:
                    continue
                seen.add(snap.market_id)
                added += 1
                if snap.volume >= min_volume:
                    out.append(snap)
            offset += len(items)
            if len(items) < page_size or not added:
                break
        log.info("Polymarket: %d active markets", len(out))
        return out

    def get_event(self, slug: str) -> dict[str, Any]:
        return self._get(f"/events/slug/{slug}")

    def midpoint(self, token_id: str) -> Optional[float]:
        """Live YES midpoint (0..1) from CLOB for a given token id."""
        data = self._get_raw(self.clob_url, "/midpoint", params={"token_id": token_id})
        price = _f(data.get("mid")) if isinstance(data, dict) else None
        return price

    def price_history(self, token_id: str, interval: str = "1d") -> list[dict[str, Any]]:
        data = self._get_raw(
            self.clob_url,
            "/prices-history",
            params={"market": token_id, "interval": interval, "fidelity": 60},
        )
        return data.get("history", []) if isinstance(data, dict) else []

    # ------------------------------------------------------------------ #
    def _get_raw(self, base: str, path: str, params: Optional[dict[str, Any]] = None) -> Any:
        old = self.base_url
        self.base_url = base
        try:
            return self._get(path, params=params)
        finally:
            self.base_url = old

    def _normalize(self, m: dict[str, Any]) -> Optional[MarketSnapshot]:
        question = m.get("question") or m.get("title")
        if not question:
            return None

        outcome_prices = _loads(m.get("outcomePrices")) or []
        outcomes = _loads(m.get("outcomes")) or []
        clob_tokens = _loads(m.get("clobTokenIds")) or []

        # The YES outcome is conventionally index 0; confirm by label when present.
        yes_idx = 0
        for i, label in enumerate(outcomes):
            if str(label).strip().lower() in ("yes", "ya", "si"):
                yes_idx = i
                break

        yes_price: Optional[float] = None
        if outcome_prices and yes_idx < len(outcome_prices):
            yes_price = _f(outcome_prices[yes_idx], None)  # type: ignore[arg-type]
        if yes_price is None:
            yes_price = _f(m.get("lastTradePrice"), None)
        if yes_price is None:
            return None  # unpriceable market

        # YES-side top of book. Gamma surfaces bestBid/bestAsk as 0..1 decimals.
        # They key the wide-spread detector; without them every Polymarket market
        # looks like it has no spread.
        yes_bid = _f(m.get("bestBid"), None) if m.get("bestBid") not in (None, "") else None
        yes_ask = _f(m.get("bestAsk"), None) if m.get("bestAsk") not in (None, "") else None
        if yes_bid is not None and yes_ask is not None and yes_ask < yes_bid:
            yes_bid = yes_ask = None  # malformed quote

        slug = m.get("slug", "")
        end_date = None
        for key in ("endDate", "end_date_iso", "gameStartTime", "closeTime"):
            if m.get(key):
                try:
                    end_date = datetime.fromisoformat(str(m[key]).replace("Z", "+00:00"))
                    break
                except ValueError:
                    pass

        event = m.get("event") or {}
        event_id = str(m.get("eventId") or event.get("id") or "") or None

        return MarketSnapshot(
            venue=Venue.POLYMARKET,
            market_id=str(m.get("conditionId") or m.get("id")),
            event_id=event_id,
            question=question,
            url=f"https://polymarket.com/market/{slug}" if slug else None,
            yes_prob=round(yes_price, 4),
            yes_bid=round(yes_bid, 4) if yes_bid is not None else None,
            yes_ask=round(yes_ask, 4) if yes_ask is not None else None,
            last_price=round(_f(m.get("lastTradePrice"), yes_price), 4),
            volume=_f(m.get("volume")),
            volume_24h=_f(m.get("volume24hr")),
            liquidity=_f(m.get("liquidity")),
            open_interest=0.0,  # Rewards are not open interest.
            active=bool(m.get("active", True)),
            closed=bool(m.get("closed", False)),
            end_date=end_date,
            raw={
                "description": m.get("description"),
                "resolution_source": m.get("resolutionSource"),
                "slug": slug,
                "outcomes": outcomes,
                "clobTokenIds": clob_tokens,
                "bestBid": _f(m.get("bestBid"), None) if m.get("bestBid") else None,
                "bestAsk": _f(m.get("bestAsk"), None) if m.get("bestAsk") else None,
            },
        )
