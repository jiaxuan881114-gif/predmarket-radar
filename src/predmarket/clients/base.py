"""Shared HTTP base client with timeouts, retries and polite rate-limiting.

Both exchanges are read-only for us. Polymarket throttles via Cloudflare (slow but
eventually 200, sometimes a bare 429 with no Retry-After); Kalshi returns standard
Retry-After on 429. We handle both.
"""
from __future__ import annotations

import logging
import random
import time
from typing import Any, Optional

import requests

log = logging.getLogger("predmarket.clients")


class BaseHttpClient:
    base_url: str = ""

    def __init__(
        self,
        timeout: float = 30.0,
        max_retries: int = 4,
        backoff: float = 1.5,
        session: Optional[requests.Session] = None,
    ) -> None:
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff = backoff
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": "predmarket-radar/0.1 (+research)"})

    def _get(self, path: str, params: Optional[dict[str, Any]] = None) -> Any:
        url = f"{self.base_url}{path}"
        last_exc: Optional[Exception] = None
        for attempt in range(self.max_retries):
            try:
                resp = self.session.get(url, params=params, timeout=self.timeout)
                if resp.status_code == 429 or 500 <= resp.status_code < 600:
                    last_exc = RuntimeError(f"HTTP {resp.status_code}")
                    if attempt + 1 < self.max_retries:
                        try:
                            wait = float(resp.headers.get("Retry-After", ""))
                        except (TypeError, ValueError):
                            wait = self.backoff ** attempt + random.uniform(0, 0.5)
                        time.sleep(min(30.0, max(0.0, wait)))
                    continue
                resp.raise_for_status()
                return resp.json()
            except (requests.Timeout, requests.ConnectionError) as exc:
                last_exc = exc
                wait = self.backoff ** attempt + random.uniform(0, 0.5)
                log.warning("network error on %s: %s; retrying in %.1fs", url, exc, wait)
                if attempt + 1 < self.max_retries:
                    time.sleep(wait)
        raise RuntimeError(f"GET {url} failed after {self.max_retries} retries: {last_exc}")
