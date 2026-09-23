"""FastAPI application.

Endpoints:
  GET  /api/health            -> system/status
  GET  /api/opportunities     -> ranked opportunity list (live/demo inference cycle)
  GET  /api/stock/{symbol}    -> candlestick history + detail view data
  GET  /api/model/info        -> current champion model metadata + metrics
  GET  /api/models            -> all trained model pointers (for comparison)
  POST /api/train             -> trigger training (blocking; intended for small demo datasets)
  GET  /api/backtest          -> run historical backtest
  GET  /api/config            -> current tunable configuration (read-only)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from backend.backtesting.backtest import run_backtest
from backend.config.settings import settings
from backend.data.providers import get_provider
from backend.features.engineering import build_features
from backend.inference.pipeline import data_status_summary, run_inference_cycle
from backend.models.registry import ModelUnavailableError, list_available_models, load_model
from backend.ranking.rank import rank_opportunities
from backend.training.train import build_training_dataset, time_aware_split, train_one

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="AI Stock Breakout Detection", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_provider = get_provider()
_start_time = datetime.now(timezone.utc)
_update_count = 0


@app.get("/api/health")
def health():
    model_status = "unavailable"
    try:
        load_model()
        model_status = "loaded"
    except ModelUnavailableError:
        pass

    return {
        "status": "ok",
        "server_time": datetime.now(timezone.utc).isoformat(),
        "uptime_seconds": (datetime.now(timezone.utc) - _start_time).total_seconds(),
        "market_data_provider": _provider.name,
        "is_live_data": _provider.is_live,
        "data_status": _provider.data_status,
        "data_feed": getattr(_provider, "feed", None),
        "model_status": model_status,
        "update_count": _update_count,
        "watchlist_size": len(settings.watchlist_symbols),
    }


@app.get("/api/opportunities")
def opportunities():
    global _update_count
    results, model_meta = run_inference_cycle(settings.watchlist_symbols, _provider)
    ranked = rank_opportunities(results)
    status = data_status_summary(results, _provider)
    _update_count += 1

    n_alerts = sum(1 for r in ranked if r["is_alert"])
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "is_live_data": _provider.is_live,
        "data_status": status["data_status"],
        "data_feed": getattr(_provider, "feed", None),
        "data_latency_ms": status["latency_ms"],
        "symbols_unavailable": status["symbols_unavailable"],
        "provider": _provider.name,
        "model": model_meta,
        "summary": {
            "stocks_monitored": len(ranked),
            "high_probability_opportunities": n_alerts,
            "live_update_count": _update_count,
            "alert_threshold": settings.probability_alert_threshold,
        },
        "opportunities": ranked,
    }


@app.get("/api/stock/{symbol}")
def stock_detail(symbol: str, limit: int = Query(200, ge=30, le=1000)):
    symbol = symbol.upper()
    if symbol not in settings.watchlist_symbols:
        raise HTTPException(status_code=404, detail=f"{symbol} is not in the configured watchlist")

    from backend.data.providers import ProviderUnavailableError

    try:
        raw = _provider.get_ohlcv(symbol, limit=limit)
    except ProviderUnavailableError as exc:
        raise HTTPException(status_code=503, detail=f"Data unavailable for {symbol}: {exc}") from exc
    feats = build_features(raw)
    latest = feats.iloc[-1]

    model_meta = None
    breakout_probability = None
    try:
        model = load_model()
        model_meta = {**model.metadata, "metrics": model.metrics}
        from backend.features.engineering import FEATURE_COLUMNS

        if not feats[FEATURE_COLUMNS].iloc[-1].isna().any():
            X = latest[FEATURE_COLUMNS].to_frame().T.astype(float)
            breakout_probability = round(float(model.predict_proba(X)[0]), 4)
    except ModelUnavailableError:
        pass

    candles = [
        {
            "timestamp": row["timestamp"].isoformat() if hasattr(row["timestamp"], "isoformat") else str(row["timestamp"]),
            "open": round(float(row["open"]), 2),
            "high": round(float(row["high"]), 2),
            "low": round(float(row["low"]), 2),
            "close": round(float(row["close"]), 2),
            "volume": float(row["volume"]),
        }
        for _, row in feats.iterrows()
    ]

    return {
        "symbol": symbol,
        "is_live_data": _provider.is_live,
        "data_status": _provider.data_status,
        "data_feed": getattr(_provider, "feed", None),
        "provider": _provider.name,
        "candles": candles,
        "resistance": round(float(latest["resistance"]), 2) if latest["resistance"] == latest["resistance"] else None,
        "breakout_confirmation_price": (
            round(float(latest["resistance"]) * (1 + settings.confirmation_threshold_pct), 2)
            if latest["resistance"] == latest["resistance"]
            else None
        ),
        "breakout_probability": breakout_probability,
        "indicators": {
            "rsi_14": round(float(latest["rsi_14"]), 2) if latest["rsi_14"] == latest["rsi_14"] else None,
            "macd": round(float(latest["macd"]), 4) if latest["macd"] == latest["macd"] else None,
            "macd_signal": round(float(latest["macd_signal"]), 4) if latest["macd_signal"] == latest["macd_signal"] else None,
            "atr_14": round(float(latest["atr_14"]), 3) if latest["atr_14"] == latest["atr_14"] else None,
            "relative_volume": round(float(latest["rel_volume"]), 2) if latest["rel_volume"] == latest["rel_volume"] else None,
            "vwap_deviation_pct": round(float(latest["vwap_deviation_pct"]) * 100, 2) if latest["vwap_deviation_pct"] == latest["vwap_deviation_pct"] else None,
        },
        "model": model_meta,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/model/info")
def model_info():
    try:
        model = load_model()
    except ModelUnavailableError as exc:
        return {"available": False, "message": str(exc)}
    return {"available": True, "metadata": model.metadata, "metrics": model.metrics, "pointer": model.pointer}


@app.get("/api/models")
def models():
    return {"models": list_available_models()}


@app.post("/api/train")
def train(model: str = Query("xgboost", pattern="^(xgboost|lightgbm|random_forest|logistic_regression)$"), candles: int = Query(1200, ge=200, le=5000)):
    logger.info("Training triggered via API: model=%s candles=%d", model, candles)
    dataset = build_training_dataset(candles_per_symbol=candles)
    if dataset.empty:
        raise HTTPException(status_code=500, detail="Training dataset is empty")
    train_df, val_df, test_df = time_aware_split(dataset)
    pointer = train_one(model, train_df, val_df, test_df)

    import json
    from pathlib import Path

    from backend.models.registry import MODEL_STORE

    champ_path = MODEL_STORE / "champion.json"
    if not champ_path.exists():
        champ_path.write_text(json.dumps(pointer, indent=2))

    return {"trained": True, "pointer": pointer}


@app.get("/api/backtest")
def backtest(threshold: float = Query(None, ge=0.0, le=1.0)):
    result = run_backtest(probability_threshold=threshold)
    return result


@app.get("/api/config")
def config():
    return {
        "resistance_window": settings.resistance_window,
        "prediction_horizon": settings.prediction_horizon,
        "confirmation_threshold_pct": settings.confirmation_threshold_pct,
        "volume_confirmation_multiple": settings.volume_confirmation_multiple,
        "probability_alert_threshold": settings.probability_alert_threshold,
        "watchlist": settings.watchlist_symbols,
        "market_data_provider": settings.market_data_provider,
        "refresh_interval_seconds": settings.refresh_interval_seconds,
    }