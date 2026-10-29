# predmarket-radar

**Prediction-market data pipeline + analysis framework + LLM judgement layer**, built on
[Polymarket](https://polymarket.com) and [Kalshi](https://kalshi.com) public APIs.
Inspired by the agent structure of [tauricresearch/tradingagents](https://github.com/tauricresearch/tradingagents),
but scoped to prediction markets: ingest live markets → screen the interesting ones →
track probability moves → flag anomalies and cross-venue dislocations → have a narrow
analyst agent emit a structured judgement.

> Research / education tool. Read-only. It does not place orders.

---

## Architecture

```
                ┌─────────────────────────────┐
 Polymarket ───▶ │  Gamma /markets  (discovery)
 (gamma-api,    │  CLOB /midpoint, /prices-history
  clob.poly)    │       │
                └───────┼───────────────────┘
                        ▼
 Kalshi ────────▶  ┌──────────────────────────┐   normalize to
 (trade-api/v2,    │  clients/*.py            │──▶ MarketSnapshot
  public reads)    │  (retry / timeout /      │   (unified 0..1 model)
                   │   cents↔prob conversion) │
                   └───────────┬──────────────┘
                               ▼
        ┌──────────────────────────────────────────────┐
        │  analysis/                                    │
        │  screener.py      composite attention score   │
        │  momentum.py      probability moves Δpp       │
        │  anomalies.py     wide spread / velocity /    │
        │                   longshot / thin depth       │
        │  cross_venue.py  Polymarket↔Kalshi price gap │
        └───────────────────────┬──────────────────────┘
                               ▼
        ┌──────────────────────────────────────────────┐
        │  agent/analyst.py                             │
        │  narrow analyst: prompt → JSON judgement       │
        │  (OpenAI-compatible; offline MockAnalyst)     │
        └───────────────────────┬──────────────────────┘
                               ▼
                     report JSON (see samples/)
```

## Data sources

| Venue | Base URL | Used for | Auth |
|---|---|---|---|
| Polymarket Gamma | `https://gamma-api.polymarket.com` | market catalogue (`/markets`, `/events`) | none (read) |
| Polymarket CLOB | `https://clob.polymarket.com` | live midpoint, price history | none (read) |
| Kalshi | `https://api.elections.kalshi.com/trade-api/v2` | `/markets`, `/events` | none (read); trading needs RSA-signed key |

Polymarket prices are already 0..1 decimals; Kalshi prices are integer **cents**
(1..99) which are already the implied probability percent. The clients convert
everything into one unified model.

## Unified data model

All venues normalise to `MarketSnapshot` (`src/predmarket/models.py`):

| Field | Type | Meaning |
|---|---|---|
| `venue` | `polymarket` / `kalshi` | source exchange |
| `market_id` | str | condition_id (Polymarket) or ticker (Kalshi) |
| `question` | str | the binary question |
| `yes_prob` | float 0..1 | midpoint implied probability of YES |
| `yes_bid` / `yes_ask` | float 0..1 | top of book on YES side |
| `volume` / `volume_24h` | float | lifetime / 24h volume (USD) |
| `liquidity` / `open_interest` | float | depth / open interest (USD) |
| `active` / `closed` | bool | lifecycle |
| `end_date` | datetime | resolution/close time |
| `raw` | dict | original venue payload (debug / agent context) |

The agent layer consumes `AgentJudgement` (`thesis`, `direction`, `conviction`,
`key_factors`, `risks`, `suggested_action`, `confidence_in_market`) as strict JSON.

## Analysis framework

* **Screener** — composite 0–100 score from 24h volume (40%), lifetime volume (20%),
  liquidity depth (20%), information content — it actively *penalises* 99/1 trivial
  markets (15%) — and open interest (5%). Log-scaled so no single whale dominates.
* **Momentum** — diffs consecutive snapshots and reports markets that moved ≥5pp.
* **Anomalies** — `wide_spread` (>4pp YES bid/ask → noisy price), `low_liquidity`
  (thin depth with real volume), `extreme_longshot` (≤5%/≥95% with volume),
  `high_velocity` (24h volume ≥30% of lifetime).
* **Cross-venue** — fuzzy-matches the same real-world question across venues (normalised
  tokens + small synonym map: *fed ≡ federal reserve ≡ fomc*, *rates ≡ rate*, …) and
  flags a price dislocation ≥8pp — either an arbitrage, a stale quote, or unpriced news.

## Agent judgement layer

`agent/analyst.py` is deliberately narrow, mirroring TradingAgents' "single-role
expert" idea: it does **not** fetch data and does **not** trade. It receives the
structured feed (probability, spread, volume, recent moves, anomaly flags) and returns
one JSON `AgentJudgement` per market.

* Uses any **OpenAI-compatible** endpoint via `OPENAI_API_KEY` / `OPENAI_BASE_URL` /
  `OPENAI_MODEL` (works with OpenAI, DeepSeek, vLLM, etc.) and `response_format=json_object`.
* Without a key it falls back to a deterministic `MockAnalyst` so the whole pipeline —
  and the bundled samples — run offline and in CI.

## Quickstart

```bash
git clone https://github.com/<you>/predmarket-radar.git
cd predmarket-radar
pip install -r requirements.txt

# 1) Offline demo on bundled fixtures (no network, no LLM key):
PYTHONPATH=src python -m predmarket.cli demo

# 2) Live fetch (needs network access to Polymarket / Kalshi):
PYTHONPATH=src python -m predmarket.cli run --limit 100 --agent-limit 5

# 3) With a real LLM for the judgement layer:
export OPENAI_API_KEY=sk-...        # optional; any OpenAI-compatible endpoint
PYTHONPATH=src python -m predmarket.cli run
```

Run the offline tests:

```bash
PYTHONPATH=src python tests/test_offline.py
```

## Sample output

* [`samples/fixture_polymarket.json`](samples/fixture_polymarket.json) — normalised Polymarket markets.
* [`samples/fixture_kalshi.json`](samples/fixture_kalshi.json) — normalised Kalshi markets (cents converted).
* [`samples/demo_report.json`](samples/demo_report.json) — full pipeline output: screened markets,
  anomalies, a cross-venue dislocation (Dec-2026 Fed cut priced 58% on Polymarket vs
  49% on Kalshi = **9pp gap**), and structured agent judgements.

## Project layout

```
src/predmarket/
  clients/      polymarket.py, kalshi.py, base.py (HTTP + retry)
  pipeline/     collector.py (orchestration), storage.py (JSON snapshots)
  analysis/     screener.py, momentum.py, anomalies.py, cross_venue.py
  agent/        prompts.py, analyst.py (LLM + mock)
  models.py     Pydantic unified models
  cli.py        `demo` and `run` commands
samples/        fixtures + regenerated demo report
tests/          offline tests
```

## Resume

This repo doubles as a portfolio piece. See:

- [`RESUME.md`](RESUME.md) — markdown version
- [`resume/张家轩-简历.pdf`](resume/张家轩-简历.pdf) — PDF version

## Disclaimer

Public, read-only market data for research. Prediction markets carry tail risk; the
agent output is a structured reasoning artefact, not investment advice. Nothing here
submits orders or connects to a trading account.
