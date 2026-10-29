# [Your Name]

Data / Quant Engineer — Market Data Pipelines, Applied ML & Agent Systems

📍 [City, Country] · ✉️ you@example.com · 🔗 github.com/&lt;you&gt; · 🔗 linkedin.com/in/&lt;you&gt;

> *Replace bracketed placeholders with your own details. This resume is built around the
> `predmarket-radar` project in this repository as a portfolio centrepiece.*

---

## Summary

Engineer who builds production-grade market-data pipelines and turns raw exchange data
into decision-ready signal. Experienced with REST/websocket ingestion, normalisation,
quant screening heuristics, and LLM agent layers that emit structured, verifiable output.
Comfortable owning a project end-to-end: API research → data model → analysis → agent →
open-source repo.

## Technical Skills

- **Languages:** Python (primary), SQL, bash; working knowledge of TypeScript.
- **Data / quant:** REST & websocket clients, pandas/numpy, time-series, statistical
  screening, cross-venue arbitrage detection, backtesting-lite.
- **LLM / agents:** OpenAI-compatible APIs, structured JSON outputs, prompt design,
  agent orchestration (multi-role pipelines, e.g. TradingAgents-style research loops).
- **Engineering:** git, CI, Docker, FastAPI, Pydantic, pytest, cloud deployment basics.

---

## Selected Project

### predmarket-radar — Prediction-Market Data Pipeline & Analysis Framework
**GitHub:** github.com/&lt;you&gt;/predmarket-radar · Python, requests, Pydantic, OpenAI API

An end-to-end research platform that ingests live markets from **Polymarket** and
**Kalshi**, normalises them into one unified model, screens the market universe for
attention and mispricing, and routes interesting markets through a narrow LLM analyst
that returns a structured judgement.

- **Data ingestion** — built read-only clients on Polymarket's Gamma/CLOB APIs and
  Kalshi's trade API, handling their differing dialects (0..1 decimals vs. integer
  cents, events/markets/tokens hierarchy) into one `MarketSnapshot` schema, with
  retries, timeouts and graceful per-venue degradation.
- **Analysis framework** — composite attention screener (volume × liquidity ×
  information content), probability-move momentum tracker, anomaly detectors (wide
  spread, volume velocity, longshots, thin books), and a fuzzy-matching **cross-venue
  dislocation detector** that flags the same event priced differently across exchanges.
- **Agent layer** — designed a TradingAgents-style narrow analyst (prompt + strict JSON
  output: thesis, direction, conviction, factors, risks, suggested action) on an
  OpenAI-compatible endpoint, plus a deterministic offline mock so the pipeline and CI
  run without keys.
- **Open source** — documented the data model, architecture diagram, and sample outputs
  in the README; offline tests covering screening, cross-venue matching, anomaly flags
  and structured agent output.

*What it demonstrates:* API research & integration, data modelling, quant signal
design, LLM/agent engineering, and clean open-source delivery.

---

## Experience

### [Your Title] — [Company]
*[Month YYYY] – Present*
- [One bullet: a data/engineering outcome with a metric.]
- [One bullet: a pipeline/automation you shipped.]
- [One bullet: collaboration / ownership.]

### [Your Title] — [Previous Company]
*[Month YYYY] – [Month YYYY]*
- [Bullet.]
- [Bullet.]

---

## Education

### [Degree, e.g. B.Sc. in Computer Science / Economics]
[University] · [Month YYYY]
- Relevant coursework: statistics, machine learning, econometrics, distributed systems.

---

## Highlights
- Open-source contributor / side projects (see GitHub).
- Comfortable reading raw OpenAPI/HTTP specs and reverse-engineering undocumented fields.
- Strong focus on reproducibility: fixtures, offline tests, and human-readable sample output.
