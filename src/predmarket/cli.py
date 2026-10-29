"""Command-line entry point.

Examples:
    python -m predmarket.cli run           # live fetch from Polymarket + Kalshi
    python -m predmarket.cli demo          # offline: run the full pipeline on bundled fixtures
    python -m predmarket.cli demo --out samples/agent_report.json
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from .agent import MockAnalyst, build_analyst
from .analysis import detect_anomalies, find_cross_venue_dislocations, screen_markets
from .models import AnomalySignal, MarketSnapshot, ProbabilityMove
from .pipeline import Collector, SnapshotStore

log = logging.getLogger("predmarket")

_SAMPLES = Path(__file__).resolve().parents[2] / "samples"


def _load_fixtures() -> list[MarketSnapshot]:
    """Load bundled normalized snapshots for the offline demo."""
    snaps: list[MarketSnapshot] = []
    for f in sorted(_SAMPLES.glob("fixture_*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        for m in data.get("markets", []):
            snaps.append(MarketSnapshot.model_validate(m))
    return snaps


def cmd_run(args: argparse.Namespace) -> int:
    collector = Collector(store=SnapshotStore(args.data_dir))
    report = collector.collect(limit_per_venue=args.limit, top_n=args.top_n)

    # Agent layer on the top screened markets from the latest stored snapshot.
    analyst = build_analyst()
    latest = collector.store.latest()
    screened = screen_markets(latest, top_n=args.agent_limit)
    moves = [ProbabilityMove.model_validate(m) for m in report.probability_moves]
    anomalies = [AnomalySignal.model_validate(a) for a in report.anomalies]
    judgements = analyst.judge(
        [s.market for s in screened], moves=moves, anomalies=anomalies, limit=args.agent_limit,
    )
    report_dict = report.as_dict()
    report_dict["agent"] = type(analyst).__name__
    report_dict["agent_judgements"] = [j.model_dump(mode="json") for j in judgements]

    out = Path(args.out) if args.out else Path(args.data_dir) / "report_latest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report_dict, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"wrote": str(out), "totals": report.totals, "errors": report.errors}, indent=2))
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    markets = _load_fixtures()
    if not markets:
        print("No fixtures found in samples/.")
        return 1

    screened = screen_markets(markets, top_n=args.top_n)
    anomalies = detect_anomalies(markets)
    pairs = find_cross_venue_dislocations(markets)
    # Demo is deterministic by design: ALWAYS use the offline MockAnalyst regardless of
    # whether OPENAI_API_KEY happens to be set, so the bundled sample output is stable.
    analyst = MockAnalyst()
    judgements = analyst.judge(
        [s.market for s in screened],
        moves=[],
        anomalies=anomalies,
        limit=args.agent_limit,
    )

    report = {
        "generated_at": "demo",
        "agent": "MockAnalyst (deterministic offline)",
        "totals": {
            "markets_fetched": len(markets),
            "polymarket": sum(1 for m in markets if m.venue.value == "polymarket"),
            "kalshi": sum(1 for m in markets if m.venue.value == "kalshi"),
        },
        "top_markets": [
            {"score": s.score, "venue": s.market.venue.value, "question": s.market.question,
             "yes_prob": s.market.yes_prob, "volume_24h": s.market.volume_24h,
             "reasons": s.reasons, "url": s.market.url}
            for s in screened
        ],
        "anomalies": [a.model_dump(mode="json") for a in anomalies],
        "cross_venue_pairs": [p.as_dict() for p in pairs],
        "agent_judgements": [j.model_dump(mode="json") for j in judgements],
        "note": "offline demo on bundled fixtures; agent forced to MockAnalyst (real LLM only via `run`)",
    }
    out = Path(args.out) if args.out else _SAMPLES / "demo_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"wrote": str(out), "totals": report["totals"]}, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="predmarket", description="Prediction-market radar")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="live fetch from exchanges")
    p_run.add_argument("--limit", type=int, default=100)
    p_run.add_argument("--top-n", type=int, default=25)
    p_run.add_argument("--agent-limit", type=int, default=5)
    p_run.add_argument("--data-dir", default="data")
    p_run.add_argument("--out", default=None)
    p_run.set_defaults(func=cmd_run)

    p_demo = sub.add_parser("demo", help="offline run on bundled fixtures")
    p_demo.add_argument("--top-n", type=int, default=10)
    p_demo.add_argument("--agent-limit", type=int, default=5)
    p_demo.add_argument("--out", default=None)
    p_demo.set_defaults(func=cmd_demo)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
