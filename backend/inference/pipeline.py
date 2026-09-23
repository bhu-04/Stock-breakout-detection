"""Live inference pipeline.

For each symbol: fetch latest OHLCV -> build_features (same function used
in training) -> load champion model -> predict calibrated probability ->
attach supporting signals for the dashboard.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd

from backend.config.settings import settings
from backend.data.providers import MarketDataProvider, ProviderUnavailableError
from backend.features.engineering import FEATURE_COLUMNS, build_features
from backend.models.registry import LoadedModel, ModelUnavailableError, load_model

logger = logging.getLogger(__name__)


@dataclass
class SymbolInference:
    symbol: str
    timestamp: datetime
    breakout_probability: Optional[float]
    current_price: float
    rsi: float
    relative_volume: float
    trend_signal: str
    distance_from_resistance_pct: float
    resistance: float
    atr: float
    macd_hist: float
    model_available: bool
    error: Optional[str] = None
    feature_snapshot: dict = field(default_factory=dict)


def _trend_signal(row: pd.Series) -> str:
    if row["ma_crossover_signal"] > 0 and row["dist_from_resistance_pct"] < 0.01:
        return "Bullish MA Crossover"
    if row["vwap_deviation_pct"] > 0:
        return "Above VWAP"
    if row["bb_width"] > 0 and row["close"] >= row.get("bb_upper", row["close"]):
        return "BB Upper Test"
    if row["dist_from_resistance_pct"] < 0:
        return "Above Resistance"
    if row["dist_from_resistance_pct"] < 0.02:
        return "Near Resistance"
    return "Below Resistance" if row["ma_crossover_signal"] <= 0 else "Neutral"


def run_inference_for_symbol(
    symbol: str, provider: MarketDataProvider, model: Optional[LoadedModel], history_len: int = 300
) -> SymbolInference:
    try:
        raw = provider.get_ohlcv(symbol, limit=history_len)
    except ProviderUnavailableError as exc:
        logger.warning("Provider unavailable for %s: %s", symbol, exc)
        now = datetime.now(timezone.utc)
        return SymbolInference(
            symbol=symbol,
            timestamp=now,
            breakout_probability=None,
            current_price=float("nan"),
            rsi=float("nan"),
            relative_volume=float("nan"),
            trend_signal="Data Unavailable",
            distance_from_resistance_pct=float("nan"),
            resistance=float("nan"),
            atr=float("nan"),
            macd_hist=float("nan"),
            model_available=model is not None,
            error=f"provider_unavailable: {exc}",
        )

    feats = build_features(raw)
    latest = feats.iloc[-1]

    ts = latest["timestamp"]
    if not isinstance(ts, datetime):
        ts = pd.to_datetime(ts).to_pydatetime()

    missing_features = [c for c in FEATURE_COLUMNS if pd.isna(latest.get(c))]
    if missing_features or model is None:
        return SymbolInference(
            symbol=symbol,
            timestamp=ts,
            breakout_probability=None,
            current_price=float(latest["close"]),
            rsi=float(latest.get("rsi_14", np.nan)),
            relative_volume=float(latest.get("rel_volume", np.nan)),
            trend_signal="Insufficient Data" if missing_features else "Model Unavailable",
            distance_from_resistance_pct=float(latest.get("dist_from_resistance_pct", np.nan)),
            resistance=float(latest.get("resistance", np.nan)),
            atr=float(latest.get("atr_14", np.nan)),
            macd_hist=float(latest.get("macd_hist", np.nan)),
            model_available=model is not None,
            error="insufficient_history" if missing_features else "model_unavailable",
        )

    X = latest[FEATURE_COLUMNS].to_frame().T.astype(float)
    proba = float(model.predict_proba(X)[0])

    return SymbolInference(
        symbol=symbol,
        timestamp=ts,
        breakout_probability=proba,
        current_price=float(latest["close"]),
        rsi=float(latest["rsi_14"]),
        relative_volume=float(latest["rel_volume"]),
        trend_signal=_trend_signal(latest),
        distance_from_resistance_pct=float(latest["dist_from_resistance_pct"]),
        resistance=float(latest["resistance"]),
        atr=float(latest["atr_14"]),
        macd_hist=float(latest["macd_hist"]),
        model_available=True,
        feature_snapshot={c: float(latest[c]) for c in FEATURE_COLUMNS},
    )


def run_inference_cycle(symbols: list[str], provider: MarketDataProvider) -> tuple[list[SymbolInference], Optional[dict]]:
    """Run inference for every symbol. Returns (results, model_metadata_or_None)."""
    model: Optional[LoadedModel] = None
    model_meta = None
    try:
        model = load_model()
        model_meta = {**model.metadata, "metrics": model.metrics}
    except ModelUnavailableError as exc:
        logger.warning("Inference running without a model: %s", exc)

    results = [run_inference_for_symbol(sym, provider, model) for sym in symbols]
    return results, model_meta


def data_status_summary(results: list["SymbolInference"], provider: MarketDataProvider) -> dict:
    """Aggregate per-symbol provider errors into an overall data-status summary."""
    unavailable = [r.symbol for r in results if r.error and r.error.startswith("provider_unavailable")]
    n = len(results)
    if unavailable and len(unavailable) == n:
        status = "unavailable"
    elif unavailable:
        status = "partial"
    else:
        status = provider.data_status
    return {
        "data_status": status,
        "provider": provider.name,
        "symbols_unavailable": unavailable,
        "latency_ms": round(getattr(provider, "_last_latency_ms", None) or 0, 1) or None,
    }
