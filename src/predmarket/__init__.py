"""predmarket-radar: prediction-market data pipeline + analysis framework + agent layer.

Normalises live markets from Polymarket and Kalshi, screens/momentum/anomaly-scores
them, and routes the interesting ones through an LLM analyst that emits a structured
judgement. Public, read-only data by default.
"""

__version__ = "0.1.0"
