"""Kalshi data client (read-only).

Base URL: https://external-api.kalshi.com/trade-api/v2

Kalshi prices are integer **cents** (1..99), which are already the implied probability
percent (a YES bid of 62 == 62%). Volume is reported in number of contracts; we treat
it as contract count, not traded USD. Current prices use dollar strings.

Public market listing does not require a key. Private/trading endpoints require an
RSA-signed KALSHI-ACCESS-* header set — out of scope for this read-only radar.
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Any, Optional

from ..models import MarketSnapshot, Venue
from .base import BaseHttpClient

log = logging.getLogger("predmarket.kalshi")


def _f(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, "", "null"):
            return default
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError):
        return default


class KalshiClient(BaseHttpClient):
    base_url = "https://external-api.kalshi.com/trade-api/v2"

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

        if m.get("market_type", "binary") != "binary":
            return None

        # Current API uses dollar strings; retain legacy cents compatibility.
        def price(name: str) -> Optional[float]:
            value = _f(m.get(f"{name}_dollars"), None)
            if value is None:
                cents = _f(m.get(name), None)
                value = cents / 100 if cents is not None else None
            return value if value is not None and 0 <= value <= 1 else None

        last_cents, yes_bid_c, yes_ask_c = (m.get(k) for k in ("last_price", "yes_bid", "yes_ask"))
        yes_bid, yes_ask, last_price = (price(k) for k in ("yes_bid", "yes_ask", "last_price"))
        if yes_bid is not None and yes_ask is not None and yes_bid <= yes_ask:
            yes_prob = (yes_bid + yes_ask) / 2
        elif last_price is not None:
            yes_prob = last_price
        else:
            return None

        close_time = m.get("close_time") or m.get("expected_expiration_time")
        end_date = None
        if close_time:
            try:
                end_date = datetime.fromisoformat(str(close_time).replace("Z", "+00:00"))
            except (ValueError, TypeError):
                try:
                    end_date = datetime.fromtimestamp(float(close_time), tz=timezone.utc)
                except (ValueError, TypeError, OverflowError, OSError):
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
            # Kalshi activity fields are contract counts, not USD turnover.
            # `/markets` does not expose a dedicated order-book depth field; we leave
            # `liquidity` as 0 (unknown) and use open_interest as the depth proxy.
            volume=_f(m.get("volume_fp"), _f(m.get("volume"))),
            volume_24h=_f(m.get("volume_24h_fp"), _f(m.get("volume_24h"))),
            liquidity=0.0,
            open_interest=_f(m.get("open_interest_fp"), _f(m.get("open_interest"))),
            active=bool(m.get("status") in ("open", "active")),
            closed=bool(m.get("status") in ("closed", "settled")),
            end_date=end_date,
            volume_unit="contracts",
            raw={
                "event_ticker": m.get("event_ticker"),
                "sub_title": m.get("subtitle"),
                "yes_bid_cents": yes_bid_c,
                "yes_ask_cents": yes_ask_c,
            },
        )
