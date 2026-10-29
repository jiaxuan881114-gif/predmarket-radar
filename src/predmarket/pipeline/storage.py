"""Tiny JSON-file snapshot store.

Snapshots are written to `<data_dir>/snapshot_<UTC timestamp>.json`. The most recent
two snapshots are what momentum/move detection reads. No database required — this keeps
the repo dependency-light and the data human-inspectable.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from ..models import MarketSnapshot


class SnapshotStore:
    def __init__(self, data_dir: str | Path = "data"):
        self.dir = Path(data_dir)
        self.dir.mkdir(parents=True, exist_ok=True)

    def write(self, markets: list[MarketSnapshot], label: str = "snapshot") -> Path:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        path = self.dir / f"{label}_{ts}.json"
        payload = {
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "count": len(markets),
            "markets": [m.model_dump(mode="json") for m in markets],
        }
        path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        return path

    def latest(self, label_prefix: str = "snapshot") -> list[MarketSnapshot]:
        files = sorted(self.dir.glob(f"{label_prefix}_*.json"), key=lambda p: p.stem.replace("Z", ".000000") if "." not in p.stem else p.stem[:-1])
        if not files:
            return []
        return self._read(files[-1])

    def previous_two(self, label_prefix: str = "snapshot") -> tuple[list[MarketSnapshot], list[MarketSnapshot]]:
        files = sorted(self.dir.glob(f"{label_prefix}_*.json"), key=lambda p: p.stem.replace("Z", ".000000") if "." not in p.stem else p.stem[:-1])
        if len(files) < 2:
            return [], self.latest(label_prefix)
        return self._read(files[-2]), self._read(files[-1])

    def _read(self, path: Path) -> list[MarketSnapshot]:
        data = json.loads(path.read_text(encoding="utf-8"))
        return [MarketSnapshot.model_validate(m) for m in data.get("markets", [])]
