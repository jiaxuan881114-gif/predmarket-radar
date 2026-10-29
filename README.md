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
| Kalshi | `https://external-api.kalshi.com/trade-api/v2` | `/markets`, `/events` | none (read); trading needs RSA-signed key |

Polymarket prices use 0..1 decimals. Kalshi current fields use `_dollars` price strings
and `_fp` contract counts; legacy integer-cent prices remain supported. Kalshi
ISO-8601 and legacy Unix close times are supported. See the [official market schema](https://docs.kalshi.com/api-reference/market/get-markets).

## Unified data model

All venues normalise to `MarketSnapshot` (`src/predmarket/models.py`):

| Field | Type | Meaning |
|---|---|---|
| `venue` | `polymarket` / `kalshi` | source exchange |
| `market_id` | str | condition_id (Polymarket) or ticker (Kalshi) |
| `question` | str | the binary question |
| `yes_prob` | float 0..1 | YES estimate: Kalshi quote midpoint with last-trade fallback; Polymarket outcome price |
| `yes_bid` / `yes_ask` | float 0..1 | top of book on YES side |
| `volume` / `volume_24h` | float | lifetime / 24h activity in `volume_unit` |
| `volume_unit` | str | USD/USDC turnover (Polymarket) or contracts (Kalshi) |
| `liquidity` / `open_interest` | float | reported depth / venue-specific interest; missing depth uses 0 (unknown), Kalshi interest is contracts |
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
  flags a candidate price gap ≥8pp. Different explicit years, numeric strikes, polarity and closed markets are rejected; settlement equivalence still needs manual verification.

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
git clone https://github.com/jiaxuan881114-gif/predmarket-radar.git
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
PYTHONPATH=src python -m unittest discover -s tests -p test_regressions.py
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

## Verification and remaining limits

- Reviewed against upstream main `20a3bccc6e29f515948c5f1c77456b9dfc9fc79b`.
- Original seven offline checks and twelve additional regression tests pass. The demo
  contains ten fixture markets, anomalies, candidate cross-venue gaps and five mock judgements.
- `demo` always uses MockAnalyst even when credentials exist. Fixtures are bundled
  inside the installed package; output defaults to `samples/demo_report.json` in the working directory.
- Live fetches are on-demand REST snapshots, not streaming subscriptions. Run `run`
  repeatedly to accumulate momentum history; the first snapshot cannot show changes.
- CLOB midpoint/history helper methods exist but are not called by the default pipeline.
- Kalshi contract counts and Polymarket USD/USDC turnover are not equivalent units.
  Screening weights remain a heuristic, not a calibrated cross-exchange value model;
  open interest is not executable order-book depth.
- Fuzzy cross-venue matching yields investigation candidates, not confirmed identical
  settlement contracts or executable arbitrage. Fees, settlement rules and freshness
  are not modelled. Cross-venue pairs appear in the report but are not yet agent inputs.
- With a configured LLM, per-market API/validation failures are logged and omitted;
  the mock is a no-key demonstration mode, not a silent replacement for failed real calls.
- Total market-fetch failure now returns exit code 1 and an empty-current-data report;
  old stored markets are never submitted to the agent as a fresh collection.
- Live connectivity was subsequently verified through an explicitly configured local
  HTTP proxy: two rounds of real API collection succeeded. See
  `samples/live_verification.json` and `samples/live_report_1.json` / `live_report_2.json`.
  These reports use MockAnalyst; real-LLM end-to-end behaviour remains unverified.

## Network troubleshooting and verified live run

On the tested macOS network, direct Kalshi connections timed out and direct
Polymarket TLS connections were reset. Both APIs returned HTTP 200 through the
configured local proxy. The terminal had no proxy environment variables even though
macOS system proxy settings were enabled. This comparison used direct and proxy
routes on the same network; it did not switch Wi-Fi or use a mobile hotspot.

If you use a local proxy, explicitly export its actual address before running:

```bash
# Example only: use the host/port configured by your proxy application.
export HTTP_PROXY=http://127.0.0.1:17891
export HTTPS_PROXY=http://127.0.0.1:17891
PYTHONPATH=src python -m predmarket.cli run --limit 20
```

The proxy application must be running. The project does not hard-code a proxy and
`.env.example` is documentation, not an automatically loaded configuration file.
Do not commit proxy credentials. For a no-LLM connectivity check, unset
`OPENAI_API_KEY` in that shell so `run` selects MockAnalyst.

A successful collection alone cannot guarantee a probability-move signal: the
same market must appear in consecutive snapshots and change by at least 5pp.
Current top-list sampling can change the market universe between runs; persistent
watchlists and streaming are outside the current implementation.
