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
                if resp.status_code == 429:
                    retry_after = resp.headers.get("Retry-After")
                    wait = float(retry_after) if retry_after else self.backoff ** attempt + random.uniform(0, 0.5)
                    log.warning("429 on %s; sleeping %.1fs (attempt %d)", url, wait, attempt + 1)
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                return resp.json()
            except (requests.Timeout, requests.ConnectionError) as exc:
                last_exc = exc
                wait = self.backoff ** attempt + random.uniform(0, 0.5)
                log.warning("network error on %s: %s; retrying in %.1fs", url, exc, wait)
                time.sleep(wait)
        raise RuntimeError(f"GET {url} failed after {self.max_retries} retries: {last_exc}")
