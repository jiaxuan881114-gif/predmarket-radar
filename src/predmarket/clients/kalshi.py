"""Kalshi data client (read-only).

Base URL: https://api.elections.kalshi.com/trade-api/v2

Kalshi prices are integer **cents** (1..99), which are already the implied probability
percent (a YES bid of 62 == 62%). Volume is reported in number of contracts; we treat
it as USD notional for cross-venue comparison (each contract settles at $1).

Public market listing does not require a key. Private/trading endpoints require an
RSA-signed KALSHI-ACCESS-* header set — out of scope for this read-only radar.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from ..models import MarketSnapshot, Venue
from .base import BaseHttpClient

log = logging.getLogger("predmarket.kalshi")


def _f(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, "", "null"):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


class KalshiClient(BaseHttpClient):
    base_url = "https://api.elections.kalshi.com/trade-api/v2"

    def list_active_markets(self, limit: int = 100, status: str = "open") -> list[MarketSnapshot]:
        """Fetch open markets, paginating via cursor up to `limit` total."""
        out: list[MarketSnapshot] = []
        cursor: Optional[str] = None
        while len(out) < limit:
            params: dict[str, Any] = {"status": status, "limit": min(limit - len(out), 200)}
            if cursor:
                params["cursor"] = cursor
            data = self._get("/markets", params=params)
            items = data.get("markets", []) if isinstance(data, dict) else []
            for m in items:
                snap = self._normalize(m)
                if snap is not None:
                    out.append(snap)
            cursor = data.get("cursor") if isinstance(data, dict) else None
            if not cursor:
                break
        log.info("Kalshi: %d open markets", len(out))
        return out[:limit]

    def list_events(self, limit: int = 50) -> list[dict[str, Any]]:
        data = self._get("/events", params={"limit": limit, "status": "open"})
        return data.get("events", []) if isinstance(data, dict) else []

    def _normalize(self, m: dict[str, Any]) -> Optional[MarketSnapshot]:
        title = m.get("title") or m.get("subtitle")
        ticker = m.get("ticker")
        if not title or not ticker:
            return None

        # Cents -> probability (0..1). last_price may be None pre-first-trade.
        last_cents = m.get("last_price")
        yes_bid_c = m.get("yes_bid")
        yes_ask_c = m.get("yes_ask")

        yes_bid = _f(yes_bid_c, None) / 100.0 if yes_bid_c is not None else None
        yes_ask = _f(yes_ask_c, None) / 100.0 if yes_ask_c is not None else None
        last_price = _f(last_cents, None) / 100.0 if last_cents is not None else None

        if last_price is None:
            if yes_bid is not None and yes_ask is not None:
                yes_prob = (yes_bid + yes_ask) / 2
            else:
                return None
        else:
            yes_prob = last_price

        close_time = m.get("close_time") or m.get("expected_expiration_time")
        end_date = None
        if close_time:
            try:
                # Kalshi sends unix seconds (string or int)
                end_date = datetime.fromtimestamp(int(close_time), tz=timezone.utc)
            except (ValueError, TypeError):
                pass

        return MarketSnapshot(
            venue=Venue.KALSHI,
            market_id=str(ticker),
            event_id=str(m.get("event_ticker", "")) or None,
            question=title,
            url=f"https://kalshi.com/markets/{ticker}",
            yes_prob=round(yes_prob, 4),
            yes_bid=round(yes_bid, 4) if yes_bid is not None else None,
            yes_ask=round(yes_ask, 4) if yes_ask is not None else None,
            last_price=round(last_price, 4) if last_price is not None else None,
            # Kalshi reports contracts (each settles at $1) -> treat as USD notional.
            # `/markets` does not expose a dedicated order-book depth field; we leave
            # `liquidity` as 0 (unknown) and use open_interest as the depth proxy.
            volume=_f(m.get("volume")),
            volume_24h=_f(m.get("volume_24h")),
            liquidity=0.0,
            open_interest=_f(m.get("open_interest")),
            active=bool(m.get("status") == "open"),
            closed=bool(m.get("status") in ("closed", "settled")),
            end_date=end_date,
            raw={
                "event_ticker": m.get("event_ticker"),
                "sub_title": m.get("subtitle"),
                "yes_bid_cents": yes_bid_c,
                "yes_ask_cents": yes_ask_c,
            },
        )
