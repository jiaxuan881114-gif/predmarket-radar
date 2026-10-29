# AGENTS.md — project rules for AI contributors

> Filled in per the vibe-coding workflow. Humans don't need to edit this; an AI that
> opens this repo should read this first.

## Stack
- Language: Python 3.10+
- HTTP: `requests`; validation: `pydantic v2`. No heavy frameworks.
- No database: snapshots are JSON files under `data/`.
- LLM layer: OpenAI-compatible chat completions; offline `MockAnalyst` fallback.

## Layout rules
- `src/predmarket/clients/` — only raw-API calls + normalisation to `MarketSnapshot`.
- `src/predmarket/analysis/` — pure functions over `MarketSnapshot` lists; no network.
- `src/predmarket/agent/` — prompt strings + LLM/mock callers; no data fetching.
- New signal types go in `analysis/anomalies.py` or a new `analysis/*.py`, not in clients.
- Keep every file < ~250 lines; split before it grows into a "god module".

## Conventions
- All probabilities in code are 0..1 floats. Convert Kalshi cents at the client boundary.
- Every public read call must time out (~30s) and retry with backoff; never crash the
  whole pipeline if one venue is unreachable (degrade + record in `errors`).
- Never commit API keys; credentials only via env / `.env` (see `.env.example`).
- Offline tests in `tests/test_offline.py` must pass with no network and no LLM key.

## Acceptance
- `PYTHONPATH=src python -m predmarket.cli demo` produces a report with screened
  markets, ≥1 anomaly, and structured agent judgements.
- `PYTHONPATH=src python tests/test_offline.py` exits 0.
