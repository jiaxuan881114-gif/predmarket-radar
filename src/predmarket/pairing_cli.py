"""Explicit opt-in LLM matching against a saved snapshot."""
import json
from datetime import datetime, timezone
from pathlib import Path

from .agent.pairing import PairMatcher
from .models import MarketSnapshot


def cmd_match(args):
    if not 1 <= args.limit <= 100 or not 0 <= args.min_similarity <= 1:
        raise ValueError("limit must be 1..100 and min-similarity 0..1")
    data = json.loads(Path(args.snapshot).read_text(encoding="utf-8"))
    markets = [MarketSnapshot.model_validate(m) for m in data["markets"]]
    matcher = PairMatcher()
    report = matcher.match(markets, limit=args.limit, min_similarity=args.min_similarity)
    report.update(generated_at=datetime.now(timezone.utc).isoformat(),
                  source_snapshot=str(args.snapshot), markets_loaded=len(markets),
                  note="LLM equivalence review on saved data; gaps are indicative, not executable arbitrage.")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"wrote": str(out), "candidates": report["candidate_count"],
                      "reviewed": report["reviewed_count"],
                      "confirmed": len(report["confirmed_pairs"]), "errors": len(report["errors"])}))
    return 1 if report["errors"] else 0


def register_match_command(sub):
    parser = sub.add_parser("match", help="LLM-review cross-venue candidates from a saved snapshot")
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--limit", type=int, default=20, help="Maximum paid model calls (1..100)")
    parser.add_argument("--min-similarity", type=float, default=.25)
    parser.add_argument("--out", default="data/pairing_report.json")
    parser.set_defaults(func=cmd_match)
